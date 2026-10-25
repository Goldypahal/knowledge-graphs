#!/usr/bin/env python3
"""
Build a knowledge graph of all projects listed in repos.txt.

Usage:
    python scripts/build_graph.py --repos-dir ./_repos --out ./graphs [--clone]

For every repo it extracts:
  Project, Component (sub-apps like frontend/backend), Language, Technology
  (frameworks, databases, ML/LLM tools...), Library (every declared dependency),
  Service (external APIs / infra), Concept (what the project is about), Person
  (git authors), plus cross-project links: SIMILAR_TO and SHARES_CODE_WITH.

Outputs:
  graphs/all/graph.json, graphs/all/graph.cypher, graphs/all/index.html
  graphs/projects/<name>/graph.json, graph.cypher, index.html
  graphs/summary.md

Privacy: .env files are read for variable NAMES only, never values.
Emails are used only to merge author identities and are never written out.
"""
import argparse, hashlib, json, os, re, subprocess, sys, time
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build",
             ".next", ".claude", "coverage", ".cache", "vendor", "site-packages", ".expo",
             "android", "ios", ".idea", ".vscode", ".pytest_cache", "out", "target"}
SRC_EXT = {".py": "Python", ".ipynb": "Jupyter Notebook", ".js": "JavaScript", ".jsx": "JavaScript",
           ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".go": "Go", ".rs": "Rust",
           ".cpp": "C++", ".c": "C", ".cs": "C#", ".kt": "Kotlin", ".dart": "Dart", ".php": "PHP",
           ".rb": "Ruby", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".sql": "SQL",
           ".sh": "Shell", ".prisma": "Prisma", ".sol": "Solidity", ".swift": "Swift", ".r": "R"}

# ---------------------------------------------------------------- tech catalogue
# key = lowercase dependency / import / docker image name -> (canonical name, category)
T = {}
def _add(cat, *pairs):
    for p in pairs:
        if isinstance(p, tuple):
            canon, keys = p[0], p[1:]
        else:
            canon, keys = p, (p.lower(),)
        for k in keys:
            T[k.lower()] = (canon, cat)

_add("Frontend framework", ("React", "react"), ("Next.js", "next"), ("Vue", "vue"), ("Angular", "@angular/core"),
     ("Svelte", "svelte"), ("Vite", "vite"), ("React Router", "react-router-dom", "react-router"),
     ("Redux", "redux", "@reduxjs/toolkit"), ("Zustand", "zustand"), ("TanStack Query", "@tanstack/react-query"),
     ("React Native", "react-native"), ("Expo", "expo"), ("Capacitor", "@capacitor/core"),
     ("Electron", "electron"), ("Three.js", "three", "@react-three/fiber"))
_add("UI / styling", ("Tailwind CSS", "tailwindcss", "@tailwindcss/vite"), ("shadcn/ui", "@radix-ui/react-slot", "class-variance-authority"),
     ("Material UI", "@mui/material"), ("Chakra UI", "@chakra-ui/react"), ("Bootstrap", "bootstrap", "react-bootstrap"),
     ("Framer Motion", "framer-motion", "motion"), ("Lucide icons", "lucide-react"), ("Ant Design", "antd"),
     ("GSAP", "gsap"), ("Sass", "sass"))
_add("Charts / visualisation", ("Recharts", "recharts"), ("Chart.js", "chart.js", "react-chartjs-2"), ("D3", "d3"),
     ("Plotly", "plotly", "plotly.js", "react-plotly.js"), ("Matplotlib", "matplotlib"), ("Seaborn", "seaborn"))
_add("Maps / geo", ("Leaflet", "leaflet", "react-leaflet"), ("Mapbox", "mapbox-gl"), ("Google Maps", "@react-google-maps/api", "googlemaps"),
     ("MapmyIndia", "mapmyindia"), ("OSRM / routing", "osrm"), ("OSMnx", "osmnx"), ("GeoPandas", "geopandas"))
_add("Backend framework", ("Express", "express"), ("FastAPI", "fastapi"), ("Flask", "flask"), ("Django", "django"),
     ("NestJS", "@nestjs/core"), ("Fastify", "fastify"), ("Uvicorn", "uvicorn"), ("Gunicorn", "gunicorn"),
     ("Streamlit", "streamlit"), ("Gradio", "gradio"), ("Celery", "celery"), ("Pydantic", "pydantic"),
     ("Hono", "hono"), ("Koa", "koa"))
_add("Database / storage", ("PostgreSQL", "pg", "psycopg2", "psycopg2-binary", "psycopg", "asyncpg", "postgres", "postgis/postgis", "postgresql"),
     ("MongoDB", "mongodb", "mongoose", "pymongo", "mongo", "motor"), ("MySQL", "mysql", "mysql2", "pymysql"),
     ("SQLite", "sqlite3", "better-sqlite3", "sqlite"), ("Redis", "redis", "ioredis", "redis-py"),
     ("Prisma", "prisma", "@prisma/client"), ("SQLAlchemy", "sqlalchemy"), ("Alembic", "alembic"),
     ("Sequelize", "sequelize"), ("Drizzle ORM", "drizzle-orm"), ("Supabase", "@supabase/supabase-js", "supabase"),
     ("Firebase", "firebase", "firebase-admin"), ("Neo4j", "neo4j", "neo4j-driver"), ("MinIO / S3", "minio", "boto3", "@aws-sdk/client-s3"),
     ("Elasticsearch", "elasticsearch", "@elastic/elasticsearch"), ("TimescaleDB", "timescale/timescaledb"))
_add("Vector database", ("ChromaDB", "chromadb"), ("FAISS", "faiss", "faiss-cpu", "faiss-gpu"), ("Pinecone", "pinecone", "pinecone-client", "@pinecone-database/pinecone"),
     ("Qdrant", "qdrant-client", "qdrant/qdrant", "qdrant"), ("Weaviate", "weaviate-client"), ("pgvector", "pgvector", "pgvector/pgvector"),
     ("Milvus", "pymilvus"), ("LanceDB", "lancedb"), ("BM25", "rank-bm25", "rank_bm25"))
_add("LLM / GenAI", ("OpenAI API", "openai"), ("Anthropic API", "anthropic", "@anthropic-ai/sdk"),
     ("Google Gemini", "google-generativeai", "google.generativeai", "@google/generative-ai", "@google/genai", "google-genai"),
     ("Groq", "groq", "groq-sdk"), ("LangChain", "langchain", "langchain-core", "langchain-community", "langchain-openai", "@langchain/core", "langchain_community", "langchain_core", "langchain_openai"),
     ("LangGraph", "langgraph"), ("LlamaIndex", "llama-index", "llama_index"), ("Hugging Face Transformers", "transformers"),
     ("Sentence Transformers", "sentence-transformers", "sentence_transformers"), ("Ollama", "ollama"), ("LiteLLM", "litellm"),
     ("tiktoken", "tiktoken"), ("CrewAI", "crewai"), ("AutoGen", "autogen", "pyautogen"), ("vLLM", "vllm"),
     ("OpenRouter", "openrouter"), ("Mistral", "mistralai"), ("Cohere", "cohere"), ("Vercel AI SDK", "ai"))
_add("ML / data science", ("PyTorch", "torch", "torchvision", "torchaudio"), ("TensorFlow", "tensorflow", "tensorflow-cpu", "@tensorflow/tfjs"),
     ("Keras", "keras"), ("scikit-learn", "scikit-learn", "sklearn"), ("XGBoost", "xgboost"), ("LightGBM", "lightgbm"),
     ("CatBoost", "catboost"), ("NumPy", "numpy"), ("pandas", "pandas"), ("SciPy", "scipy"), ("statsmodels", "statsmodels"),
     ("Optuna", "optuna"), ("Jupyter", "jupyter", "ipykernel", "notebook"), ("Polars", "polars"), ("NetworkX", "networkx"),
     ("PyTorch Lightning", "pytorch-lightning", "lightning"), ("Hugging Face Datasets", "datasets"), ("ONNX", "onnx", "onnxruntime", "onnxruntime-web"),
     ("PEFT / LoRA", "peft"), ("Accelerate", "accelerate"), ("Weights & Biases", "wandb"), ("MLflow", "mlflow"), ("joblib", "joblib"),
     ("Prophet", "prophet"), ("SHAP", "shap"), ("NLTK", "nltk"), ("spaCy", "spacy"))
_add("Computer vision / audio", ("OpenCV", "opencv-python", "opencv-python-headless", "cv2"), ("Ultralytics YOLO", "ultralytics"),
     ("Pillow", "pillow", "pil"), ("MediaPipe", "mediapipe"), ("librosa", "librosa"), ("Whisper", "openai-whisper", "whisper", "faster-whisper"),
     ("SpeechRecognition", "speechrecognition", "speech_recognition"), ("pyttsx3", "pyttsx3"), ("DeepFace", "deepface"),
     ("face_recognition", "face_recognition", "face-recognition"), ("FFmpeg", "ffmpeg-python", "fluent-ffmpeg", "ffmpeg"),
     ("TensorFlow Lite", "tflite-runtime", "tflite"), ("sounddevice", "sounddevice"), ("PyAudio", "pyaudio"))
_add("Documents / parsing", ("PyPDF", "pypdf", "pypdf2"), ("PyMuPDF", "pymupdf", "fitz"), ("pdfplumber", "pdfplumber"),
     ("python-docx", "python-docx", "docx"), ("BeautifulSoup", "beautifulsoup4", "bs4"), ("pdf.js", "pdfjs-dist", "react-pdf"),
     ("jsPDF", "jspdf"), ("Puppeteer", "puppeteer"), ("Playwright", "playwright", "@playwright/test"), ("Selenium", "selenium"),
     ("arXiv API", "arxiv"), ("Unstructured", "unstructured"))
_add("Auth / security", ("JWT", "jsonwebtoken", "pyjwt", "jwt", "jose", "python-jose", "jwt-decode", "jose"), ("bcrypt", "bcrypt", "bcryptjs", "passlib"),
     ("Passport.js", "passport"), ("NextAuth", "next-auth", "@auth/core"), ("Clerk", "@clerk/clerk-react", "@clerk/nextjs"),
     ("Helmet", "helmet"), ("CORS", "cors"), ("express-rate-limit", "express-rate-limit"), ("Cryptography", "cryptography"))
_add("Realtime / messaging", ("Socket.IO", "socket.io", "socket.io-client", "python-socketio"), ("WebSockets", "ws", "websockets"),
     ("MQTT", "mqtt", "paho-mqtt", "eclipse-mosquitto"), ("Kafka", "kafkajs", "kafka-python", "confluentinc/cp-kafka", "bitnami/kafka"),
     ("RabbitMQ", "amqplib", "pika", "rabbitmq"), ("WebRTC", "simple-peer", "peerjs", "aiortc"), ("BullMQ", "bullmq"),
     ("Yjs (collab editing)", "yjs", "y-websocket"), ("Monaco Editor", "@monaco-editor/react", "monaco-editor"))
_add("Testing", ("pytest", "pytest"), ("Jest", "jest"), ("Vitest", "vitest"), ("Testing Library", "@testing-library/react"),
     ("Cypress", "cypress"), ("Supertest", "supertest"))
_add("Tooling", ("ESLint", "eslint"), ("Prettier", "prettier"), ("TypeScript", "typescript"), ("Axios", "axios"),
     ("Zod", "zod"), ("Nodemon", "nodemon"), ("dotenv", "dotenv", "python-dotenv"), ("Requests / HTTPX", "requests", "httpx", "aiohttp"),
     ("Multer (uploads)", "multer"), ("Nodemailer", "nodemailer"), ("Stripe", "stripe"), ("Razorpay", "razorpay"),
     ("Twilio", "twilio"), ("GitPython", "gitpython", "git"), ("Rich (CLI)", "rich"), ("Typer / Click", "typer", "click"),
     ("Docker SDK", "docker"), ("Pino / Winston logging", "pino", "winston"), ("Swagger / OpenAPI", "swagger-ui-express", "swagger-jsdoc"))

# python import name -> requirement key (when they differ)
IMPORT_ALIAS = {"sklearn": "sklearn", "cv2": "cv2", "PIL": "pil", "bs4": "bs4", "fitz": "fitz", "yaml": None,
                "google": None, "dotenv": "python-dotenv", "jwt": "pyjwt", "jose": "python-jose", "docx": "docx",
                "paho": "paho-mqtt", "speech_recognition": "speech_recognition", "faiss": "faiss"}

# env-var name fragments -> external service
ENV_SERVICES = [
    (r"OPENAI", "OpenAI API", "LLM / GenAI"), (r"OPENROUTER", "OpenRouter", "LLM / GenAI"),
    (r"ANTHROPIC|CLAUDE", "Anthropic API", "LLM / GenAI"), (r"GEMINI|GOOGLE_API_KEY|GOOGLE_GENAI", "Google Gemini", "LLM / GenAI"),
    (r"GROQ", "Groq", "LLM / GenAI"), (r"HUGGING|HF_TOKEN|HF_API", "Hugging Face Hub", "LLM / GenAI"),
    (r"MISTRAL", "Mistral", "LLM / GenAI"), (r"COHERE", "Cohere", "LLM / GenAI"), (r"OLLAMA", "Ollama", "LLM / GenAI"),
    (r"PINECONE", "Pinecone", "Vector database"), (r"QDRANT", "Qdrant", "Vector database"),
    (r"SUPABASE", "Supabase", "Database / storage"), (r"FIREBASE", "Firebase", "Database / storage"),
    (r"MONGO", "MongoDB", "Database / storage"), (r"REDIS", "Redis", "Database / storage"),
    (r"POSTGRES|PGHOST|PG_", "PostgreSQL", "Database / storage"), (r"NEO4J", "Neo4j", "Database / storage"),
    (r"MINIO|S3_|AWS_", "AWS / S3", "Cloud"), (r"CLOUDINARY", "Cloudinary", "Cloud"), (r"MQTT", "MQTT", "Realtime / messaging"),
    (r"MAPMYINDIA|MAPPLS", "MapmyIndia", "Maps / geo"), (r"MAPBOX", "Mapbox", "Maps / geo"), (r"GOOGLE_MAPS", "Google Maps", "Maps / geo"),
    (r"ORS_|OPENROUTESERVICE", "OpenRouteService", "Maps / geo"), (r"STRIPE", "Stripe", "Tooling"), (r"RAZORPAY", "Razorpay", "Tooling"),
    (r"TWILIO", "Twilio", "Tooling"), (r"SMTP|MAIL_|SENDGRID|RESEND", "Email (SMTP)", "Tooling"),
    (r"GITHUB_TOKEN|GH_TOKEN", "GitHub API", "Cloud"), (r"KAGGLE", "Kaggle", "Cloud"), (r"WANDB", "Weights & Biases", "ML / data science"),
    (r"CLERK", "Clerk", "Auth / security"), (r"JWT", "JWT", "Auth / security"), (r"YOUTUBE", "YouTube API", "Cloud"),
    (r"SERPAPI|TAVILY|BRAVE_|SERPER", "Web search API", "LLM / GenAI"), (r"ELEVENLABS", "ElevenLabs", "Computer vision / audio"),
    (r"JUDGE0|RAPIDAPI", "Judge0 / RapidAPI", "Cloud"), (r"SEMANTIC_SCHOLAR|ARXIV", "Scholarly APIs", "Documents / parsing"),
]

# README / description keywords -> concept
CONCEPTS = [
    ("Retrieval-Augmented Generation (RAG)", r"\bRAG\b|retrieval[- ]augmented"),
    ("LLM agents", r"\bagents?\b.*\bLLM\b|\bLLM\b.*\bagents?\b|autonomous agent|multi-agent|agentic"),
    ("Multi-agent systems", r"multi-agent|multi agent|multiagent"),
    ("Vector / hybrid search", r"vector (search|store|retrieval|database)|hybrid (retrieval|search)|embedding"),
    ("Research paper / benchmark", r"research paper|benchmark|empirical|ablation|arxiv|hypothesis|reproducib"),
    ("LLM evaluation", r"LLM[- ]as[- ]a?[- ]?judge|evaluation harness|hallucination|faithfulness"),
    ("Time-series forecasting", r"time[- ]series|forecast"),
    ("Transformers / deep learning", r"\btransformer\b|deep learning|neural network|attention mechanism"),
    ("Computer vision", r"computer vision|object detection|\bYOLO\b|face recognition|image classification|CCTV|video analytics"),
    ("Video intelligence / surveillance", r"CCTV|surveillance|video intelligence|video analytics"),
    ("Audio / speech", r"speech|voice|audio|scream|whisper"),
    ("Personal AI assistant", r"personal assistant|AI assistant|jarvis|voice assistant"),
    ("CI/CD & DevOps", r"CI/CD|continuous integration|github actions|devops|pipeline.*deploy"),
    ("Automated code repair", r"generat\w* (and applies )?(verified )?patch|regressions? introduced|program repair|self-healing"),
    ("Authentication & access control", r"\bJWT\b|authentication|role-based|RBAC|access control|login"),
    ("Cybersecurity", r"cyber ?security|privacy and security|vulnerab|threat model|jailbreak"),
    ("Healthcare / diagnostics", r"\bpatients?\b|\bdoctors?\b|clinic|hospital|pathology|\bLIMS\b|\bEMR\b|medical"),
    ("Education / ed-tech", r"\bstudents?\b|learning platform|education|aptitude|\bquiz|classroom|educator"),
    ("Career guidance & skills", r"career|resume|skill gap|job|placement|interview"),
    ("Transportation & mobility", r"ride ?shar|carpool|\bbus(es)?\b tracker|bus route|vehicle|transport|commut|\bEV\b|charging station"),
    ("Real-time tracking / IoT", r"real-time tracking|\bGPS\b|\bIoT\b|telemetry|\bMQTT\b|live location"),
    ("Route optimisation", r"route optimi|shortest path|optimal (route|charging)|routing engine|dijkstra|A\*"),
    ("Women / personal safety", r"women safety|personal safety|SOS|emergency alert|safe route|panic"),
    ("Enterprise AI platform", r"enterprise|component store|VPC|air-gapped|sovereign"),
    ("Short-form video / social", r"\breels?\b|short-form video|social feed"),
    ("Microservices", r"microservice"),
    ("HR / workforce management", r"employee|attendance|payroll|workforce"),
    ("Hackathon project", r"hackathon"),
    ("Portfolio / personal site", r"portfolio"),
    ("Agriculture / environment", r"agricultur|\bcrops?\b|\bfarm|\bplants?\b|garden"),
    ("Supply chain / demand", r"supply chain|inventory|demand forecast|intermittent demand"),
    ("Collaborative coding / interviews", r"code[- ]collab|collaborative (code|editor)|group discussion|\bGD\b"),
    ("Fraud / financial risk", r"fraud|credit|financial risk|transaction"),
]

def tech_of(name):
    return T.get(name.lower().strip())

# ---------------------------------------------------------------- helpers
def walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".") or d == ".github"]
        for fn in fns:
            yield Path(dp) / fn

def read(p, limit=400_000):
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except Exception:
        return ""

def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""

def norm_pkg(s):
    s = s.strip().lower()
    return re.split(r"[<>=!~;\[ @]", s, maxsplit=1)[0].strip().replace("_", "-") if s else ""

def parse_requirements(text):
    out = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        n = norm_pkg(line)
        if n:
            out.append(n)
    return out

def parse_pyproject(text):
    out = []
    for m in re.finditer(r'^\s*"([A-Za-z0-9_.\-\[\]]+)\s*[<>=!~^]?', text, re.M):
        out.append(norm_pkg(m.group(1)))
    for m in re.finditer(r'^([A-Za-z0-9_\-]+)\s*=\s*["{]', text, re.M):
        k = m.group(1).lower()
        if k not in {"python", "name", "version", "description", "readme", "license", "requires-python", "build-backend", "authors"}:
            out.append(k)
    return [o for o in out if o]

PY_IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w]*)[\w.]*\s+import|import\s+([A-Za-z_][\w]*))", re.M)

def py_imports(text):
    s = set()
    for a, b in PY_IMPORT.findall(text):
        s.add(a or b)
    return s

def notebook_code(p):
    try:
        nb = json.loads(read(p, 5_000_000))
        return "\n".join("".join(c.get("source", [])) for c in nb.get("cells", []) if c.get("cell_type") == "code")
    except Exception:
        return ""

def readme_summary(text):
    """First meaningful paragraph of a README, markdown stripped."""
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|\[!\[.*?\]\(.*?\)\]\(.*?\)", " ", text)
    title = None
    for line in text.splitlines():
        l = line.strip()
        if l.startswith("#") and not title:
            title = l.lstrip("#").strip()
            continue
        if len(l) > 60 and not l.startswith(("#", "|", "-", "*", "`", ">", "[")) or (l.startswith(">") and len(l) > 40):
            l = re.sub(r"[*_`>]", "", l)
            l = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", l)
            return title, l[:400]
    return title, ""

TEMPLATE_README = re.compile(r"This template provides a minimal setup|Getting Started with Create React App|bootstrapped with \[?create-next-app", re.I)

# ---------------------------------------------------------------- scanning
def scan_repo(path: Path, full_name: str):
    name = path.name
    p = {"name": name, "full_name": full_name, "url": f"https://github.com/{full_name}",
         "owner": full_name.split("/")[0], "components": [], "languages": Counter(),
         "techs": defaultdict(set), "libs": defaultdict(set), "services": defaultdict(set),
         "concepts": Counter(), "people": Counter(), "hashes": {}, "env_vars": set(),
         "ci": set(), "deploy": set(), "text": "", "secret_files": []}

    manifests = defaultdict(list)  # dir -> [manifest files]
    readmes, texts, py_text = [], [], []
    for f in walk(path):
        rel = f.relative_to(path)
        parts_l = [x.lower() for x in rel.parts]
        ext = f.suffix.lower()
        fn = f.name.lower()
        try:
            size = f.stat().st_size
        except Exception:
            continue
        if ext in SRC_EXT and size < 2_000_000:
            p["languages"][SRC_EXT[ext]] += 1
        if fn in {"package.json", "requirements.txt", "pyproject.toml", "dockerfile", "pom.xml", "go.mod", "cargo.toml"} \
                or (fn.startswith("requirements") and fn.endswith(".txt")) or fn.startswith("docker-compose"):
            if "tests" not in parts_l[:-1] and "test" not in parts_l[:-1]:
                manifests[str(rel.parent)].append(f)
        if fn.startswith("readme") and not set(parts_l[:-1]) & {"tests", "test", "alembic", "docs", "archive", "data for test"}:
            readmes.append(f)
        if fn in {".env", ".env.example", ".env.sample", ".env.local", ".env.template"} or fn.startswith(".env."):
            body = read(f, 50_000)
            names = re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=", body, re.M)
            p["env_vars"].update(names)
            if fn == ".env" and any(re.search(r"SECRET|KEY|TOKEN|PASSWORD", n) for n in names):
                # flag only; values are never read into the graph
                vals = [l.split("=", 1)[1].strip() for l in body.splitlines() if "=" in l and re.search(r"SECRET|KEY|TOKEN|PASSWORD", l.split("=")[0])]
                if any(len(v) > 8 and not re.search(r"your|change|xxx|example|<|placeholder", v, re.I) for v in vals):
                    p["secret_files"].append(str(rel))
        if ".github" in rel.parts and "workflows" in rel.parts:
            p["ci"].add("GitHub Actions")
            body = read(f, 50_000).lower()
            for kw, svc in [("vercel", "Vercel"), ("render", "Render"), ("netlify", "Netlify"), ("docker", "Docker"),
                            ("heroku", "Heroku"), ("gh-pages", "GitHub Pages"), ("pages", "GitHub Pages"), ("aws", "AWS"), ("gcloud", "Google Cloud"), ("railway", "Railway")]:
                if kw in body:
                    p["deploy"].add(svc)
        if fn in {"vercel.json"}: p["deploy"].add("Vercel")
        if fn in {"render.yaml"} or fn.startswith("requirements-render"): p["deploy"].add("Render")
        if fn in {"netlify.toml"}: p["deploy"].add("Netlify")
        if fn == ".replit": p["deploy"].add("Replit")
        if fn == "procfile": p["deploy"].add("Heroku")
        if ext == ".py" and size < 1_000_000:
            py_text.append(read(f))
        if ext == ".ipynb" and size < 20_000_000:
            code = notebook_code(f)
            py_text.append(code)
            if "kaggle" in code.lower() or "kaggle" in fn: p["deploy"].add("Kaggle")
            if "google.colab" in code: p["deploy"].add("Google Colab")
        if ext in {".py", ".js", ".jsx", ".ts", ".tsx"} and 300 < size < 500_000:
            h = hashlib.sha1(re.sub(rb"\s+", b"", open(f, "rb").read())).hexdigest()
            p["hashes"][h] = str(rel)
        if fn == "index.html" and len(rel.parts) <= 3:
            m = re.search(r"<title>(.*?)</title>", read(f, 20_000), re.S | re.I)
            if m: texts.append(m.group(1).strip())

    # ---- manifests -> components, libraries, technologies
    for d, files in sorted(manifests.items()):
        comp_libs = set()
        eco = set()
        comp_desc = ""
        for f in files:
            fn = f.name.lower()
            body = read(f)
            if fn == "package.json":
                eco.add("npm")
                try:
                    j = json.loads(body)
                except Exception:
                    j = {}
                for sec in ("dependencies", "devDependencies", "peerDependencies"):
                    for k in (j.get(sec) or {}):
                        comp_libs.add(("npm", k.lower()))
                comp_desc = j.get("description") or comp_desc
                if j.get("name") and not comp_desc:
                    texts.append(str(j.get("name")))
            elif fn.startswith("requirements"):
                eco.add("pip")
                comp_libs.update(("pip", x) for x in parse_requirements(body))
            elif fn == "pyproject.toml":
                eco.add("pip")
                comp_libs.update(("pip", x) for x in parse_pyproject(body))
                m = re.search(r'description\s*=\s*"([^"]+)"', body)
                if m: comp_desc = comp_desc or m.group(1)
            elif fn == "dockerfile":
                p["deploy"].add("Docker")
                for img in re.findall(r"^\s*FROM\s+([^\s:]+)", body, re.M | re.I):
                    t = tech_of(img) or tech_of(img.split("/")[-1])
                    if t: p["techs"][t].add(d)
            elif fn.startswith("docker-compose"):
                p["deploy"].add("Docker Compose")
                for img in re.findall(r"image:\s*['\"]?([^\s:'\"]+)", body):
                    key = img.lower()
                    t = tech_of(key) or tech_of(key.split("/")[-1])
                    if t:
                        p["services"][t].add("docker-compose")
                        p["techs"][t].add(d)
            elif fn == "go.mod":
                p["languages"]["Go"] += 1
            elif fn == "pom.xml":
                p["languages"]["Java"] += 1
        for eco_name, lib in comp_libs:
            p["libs"][(eco_name, lib)].add(d)
            t = tech_of(lib)
            if t: p["techs"][t].add(d)
        if d != "." and comp_libs or (d != "." and any(f.name.lower() == "dockerfile" for f in files)):
            p["components"].append({"path": d, "ecosystems": sorted(eco), "libs": sorted(l for _, l in comp_libs),
                                    "description": comp_desc})

    # ---- python imports (catches notebooks/scripts with no requirements file)
    imports = set()
    for t in py_text:
        imports |= py_imports(t)
    for imp in imports:
        key = IMPORT_ALIAS.get(imp, imp.lower()) if imp in IMPORT_ALIAS else imp.lower()
        if key is None:
            continue
        t = tech_of(key)
        if t:
            p["techs"][t].add("imports")
    if any("google.generativeai" in t or "from google import genai" in t for t in py_text):
        p["techs"][("Google Gemini", "LLM / GenAI")].add("imports")
    if any(re.search(r"openrouter\.ai", t) for t in py_text):
        p["services"][("OpenRouter", "LLM / GenAI")].add("code")

    # ---- env vars -> external services
    for v in p["env_vars"]:
        for rx, svc, cat in ENV_SERVICES:
            if re.search(rx, v):
                p["services"][(svc, cat)].add("env")

    # ---- README / description
    desc, title = "", None
    for r in sorted(readmes, key=lambda x: len(x.relative_to(path).parts)):
        body = read(r, 200_000)
        texts.append(body[:30_000])
        if not desc and not TEMPLATE_README.search(body[:600]):
            title, desc = readme_summary(body)
    if not desc:
        for c in p["components"]:
            if c["description"]:
                desc = c["description"]; break
    p["title"] = title or name
    p["description"] = desc
    alltext = "\n".join(texts) + "\n" + name.replace("-", " ")
    p["text"] = alltext
    for concept, rx in CONCEPTS:
        hits = len(re.findall(rx, alltext, re.I))
        if hits:
            p["concepts"][concept] = hits

    # ---- git history
    log = git(path, "log", "--format=%an\t%ae\t%at")
    times = []
    for line in log.splitlines():
        try:
            an, ae, at = line.split("\t")
        except ValueError:
            continue
        times.append(int(at))
        p["people"][normalise_person(an, ae)] += 1
    p["commits"] = len(times)
    p["first_commit"] = time.strftime("%Y-%m-%d", time.gmtime(min(times))) if times else ""
    p["last_commit"] = time.strftime("%Y-%m-%d", time.gmtime(max(times))) if times else ""
    days = (time.time() - max(times)) / 86400 if times else 9999
    p["status"] = "active" if days <= 30 else "recent" if days <= 90 else "dormant"
    p["files"] = len(git(path, "ls-files").splitlines())
    return p

ME_RX = re.compile(r"goldy|pahal", re.I)
def normalise_person(name, email):
    if ME_RX.search(name) or ME_RX.search(email):
        return "Goldy Pahal"
    return name.strip()

# ---------------------------------------------------------------- graph assembly
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def build(projects):
    nodes, edges = {}, []
    def node(nid, label, ntype, **props):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "type": ntype, "props": {}}
        nodes[nid]["props"].update({k: v for k, v in props.items() if v not in (None, "", [], {})})
        return nid
    def edge(a, b, etype, **props):
        edges.append({"source": a, "target": b, "type": etype, "props": props})

    lib_users = defaultdict(set)
    for p in projects.values():
        for (eco, lib) in p["libs"]:
            lib_users[(eco, lib)].add(p["name"])

    for p in projects.values():
        pid = node(f"project:{p['name']}", p["name"], "Project", title=p["title"], description=p["description"],
                   url=p["url"], owner=p["owner"], status=p["status"], commits=p["commits"], files=p["files"],
                   first_commit=p["first_commit"], last_commit=p["last_commit"], kind=p.get("kind", ""))
        total = sum(p["languages"].values()) or 1
        for lang, n in p["languages"].most_common(8):
            if n / total < 0.02 and n < 3: continue
            edge(pid, node(f"language:{lang}", lang, "Language"), "WRITTEN_IN", files=n, share=round(n / total, 3))
        comp_ids = {}
        for c in p["components"]:
            cid = node(f"component:{p['name']}/{c['path']}", c["path"], "Component", project=p["name"],
                       role=component_role(c), ecosystems=c["ecosystems"], description=c["description"])
            comp_ids[c["path"]] = cid
            edge(pid, cid, "HAS_COMPONENT")
        for (tname, cat), where in sorted(p["techs"].items()):
            tid = node(f"tech:{tname}", tname, "Technology", category=cat)
            edge(pid, tid, "USES", via=sorted(where))
            for w in where:
                if w in comp_ids:
                    edge(comp_ids[w], tid, "USES")
        for (eco, lib), where in sorted(p["libs"].items()):
            lid = node(f"lib:{eco}:{lib}", lib, "Library", ecosystem=eco, used_by_projects=len(lib_users[(eco, lib)]),
                       technology=(tech_of(lib) or (None,))[0])
            edge(pid, lid, "DEPENDS_ON", via=sorted(where))
            t = tech_of(lib)
            if t:
                edge(lid, f"tech:{t[0]}", "IMPLEMENTS")
        for (sname, cat), src in sorted(p["services"].items()):
            sid = node(f"service:{sname}", sname, "Service", category=cat)
            edge(pid, sid, "CONNECTS_TO", detected_from=sorted(src))
        for d in sorted(p["deploy"] | p["ci"]):
            did = node(f"platform:{d}", d, "Platform")
            edge(pid, did, "DEPLOYS_WITH" if d not in p["ci"] else "AUTOMATED_BY")
        for concept, hits in p["concepts"].most_common(9):
            if hits < 2 and concept not in {"Hackathon project", "Portfolio / personal site", "Research paper / benchmark", "Microservices"}:
                continue
            edge(pid, node(f"concept:{concept}", concept, "Concept"), "ABOUT",
                 source="manual" if hits >= 1000 else "readme", mentions=hits % 1000)
        for other, rel in (p.get("related") or {}).items():
            if other in projects:
                edge(pid, f"project:{other}", re.sub(r"[^A-Z_]", "", rel.upper()) or "RELATED_TO", source="manual")
        for person, n in p["people"].most_common():
            edge(node(f"person:{person}", person, "Person"), pid, "CONTRIBUTED_TO", commits=n)

    # cross-project: similarity by technology overlap
    names = list(projects)
    tech_sets = {n: {t for t, _ in projects[n]["techs"]} for n in names}
    for i, a in enumerate(names):
        scores = []
        for b in names:
            if a == b: continue
            sa, sb = tech_sets[a], tech_sets[b]
            if not sa or not sb: continue
            shared = sa & sb
            j = len(shared) / len(sa | sb)
            if len(shared) >= 4 and j >= 0.3:
                scores.append((j, b, sorted(shared)))
        for j, b, shared in sorted(scores, reverse=True)[:3]:
            if a < b or not any(e for e in edges if e["type"] == "SIMILAR_STACK" and e["source"] == f"project:{b}" and e["target"] == f"project:{a}"):
                edge(f"project:{a}", f"project:{b}", "SIMILAR_STACK", score=round(j, 2), shared=shared[:15])

    # cross-project: identical source files (code reuse)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = set(projects[a]["hashes"]) & set(projects[b]["hashes"])
            if len(shared) >= 3:
                newer, older = (a, b) if projects[a]["first_commit"] > projects[b]["first_commit"] else (b, a)
                sample = sorted(projects[newer]["hashes"][h] for h in shared)[:8]
                edge(f"project:{newer}", f"project:{older}", "SHARES_CODE_WITH", identical_files=len(shared), examples=sample)

    # dedupe: one edge per (source, type, target); SIMILAR_STACK is undirected
    seen, out = set(), []
    for e in edges:
        k = (tuple(sorted((e["source"], e["target"]))) if e["type"] == "SIMILAR_STACK" else (e["source"], e["target"]), e["type"])
        if k in seen: continue
        seen.add(k)
        out.append(e)
    return {"nodes": list(nodes.values()), "edges": out}

def component_role(c):
    path = c["path"].lower()
    libs = set(c["libs"])
    for role, keys in [("frontend", ["frontend", "client", "web", "portal", "dashboard", "app", "ui"]),
                       ("backend", ["backend", "server", "api"]),
                       ("ml", ["ml", "model", "rag", "engine", "research"])]:
        if any(k in path for k in keys):
            return role
    if libs & {"react", "next", "vue", "vite"}: return "frontend"
    if libs & {"express", "fastapi", "flask", "django"}: return "backend"
    if libs & {"torch", "tensorflow", "scikit-learn", "transformers"}: return "ml"
    return "module"

def subgraph(g, project):
    pid = f"project:{project}"
    keep = {pid}
    for e in g["edges"]:
        if e["source"] == pid: keep.add(e["target"])
        if e["target"] == pid: keep.add(e["source"])
    comp = {n for n in keep if n.startswith("component:")}
    nodes = [n for n in g["nodes"] if n["id"] in keep]
    edges = [e for e in g["edges"] if e["source"] in keep and e["target"] in keep and
             (pid in (e["source"], e["target"]) or e["source"] in comp or e["type"] == "IMPLEMENTS")]
    return {"nodes": nodes, "edges": edges}

# ---------------------------------------------------------------- writers
def cypher_str(v):
    return json.dumps(v, ensure_ascii=False)

def to_cypher(g):
    lines = ["// Generated by scripts/build_graph.py. Safe to re-run: everything uses MERGE.",
             "CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;"]
    for n in g["nodes"]:
        props = {"name": n["label"], **{k: v for k, v in n["props"].items() if isinstance(v, (str, int, float, bool, list))}}
        sets = ", ".join(f"n.`{k}` = {cypher_str(v)}" for k, v in props.items())
        lines.append(f"MERGE (n:Entity {{id: {cypher_str(n['id'])}}}) SET n:{n['type']}, {sets};")
    for e in g["edges"]:
        props = {k: v for k, v in e["props"].items() if isinstance(v, (str, int, float, bool, list))}
        sets = (" SET " + ", ".join(f"r.`{k}` = {cypher_str(v)}" for k, v in props.items())) if props else ""
        lines.append(f"MATCH (a:Entity {{id: {cypher_str(e['source'])}}}), (b:Entity {{id: {cypher_str(e['target'])}}}) "
                     f"MERGE (a)-[r:{e['type']}]->(b){sets};")
    return "\n".join(lines) + "\n"

def to_html(g, title, subtitle, template, page_title, pages_base=""):
    data = json.dumps(g, ensure_ascii=False).replace("</", "<\\/")
    for k, v in {"__PAGE_TITLE__": page_title, "__TITLE__": title, "__SUBTITLE__": subtitle,
                 "__PAGES_BASE__": pages_base}.items():
        template = template.replace(k, v.replace("<", "&lt;"))
    return template.replace("__GRAPH_DATA__", data)

def write_outputs(g, projects, out: Path):
    tpl = (ROOT / "scripts" / "viewer_template.html").read_text()
    (out / "all").mkdir(parents=True, exist_ok=True)
    (out / "all" / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    (out / "all" / "graph.cypher").write_text(to_cypher(g))
    (out / "all" / "index.html").write_text(to_html(g, "Project Knowledge Graph",
        f"{len(projects)} GitHub projects, scanned {time.strftime('%d %b %Y', time.gmtime())}", tpl,
        "Project Knowledge Graph", "../projects/"))
    for name in projects:
        sg = subgraph(g, name)
        d = out / "projects" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "graph.json").write_text(json.dumps(sg, indent=1, ensure_ascii=False))
        (d / "graph.cypher").write_text(to_cypher(sg))
        (d / "index.html").write_text(to_html(sg, name, projects[name]["title"] if projects[name]["title"] != name else projects[name]["description"][:90],
                                           tpl, f"{name} Graph"))
    (out / "summary.md").write_text(summary_md(g, projects))
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Project Knowledge Graph</title>'
                                    '<meta http-equiv="refresh" content="0; url=all/index.html"><a href="all/index.html">Open the graph</a>')

def summary_md(g, projects):
    by = defaultdict(list)
    for e in g["edges"]: by[e["source"]].append(e)
    name_of = {n["id"]: n["label"] for n in g["nodes"]}
    rows = ["| Project | Status | Last commit | Main stack | About |", "|---|---|---|---|---|"]
    for name, p in sorted(projects.items(), key=lambda kv: kv[1]["last_commit"], reverse=True):
        es = by[f"project:{name}"]
        stack = [name_of[e["target"]] for e in es if e["type"] == "USES" and
                 next(n for n in g["nodes"] if n["id"] == e["target"])["props"].get("category") not in {"Tooling", "Testing", "UI / styling"}][:6]
        about = [name_of[e["target"]] for e in es if e["type"] == "ABOUT"][:3]
        rows.append(f"| [{name}](projects/{name}/index.html) | {p['status']} | {p['last_commit']} | {', '.join(stack)} | {', '.join(about)} |")
    tech_count = Counter()
    for e in g["edges"]:
        if e["type"] == "USES" and e["source"].startswith("project:"):
            tech_count[name_of[e["target"]]] += 1
    reuse = [f"- **{name_of[e['source']]}** shares {e['props']['identical_files']} identical source files with **{name_of[e['target']]}**"
             for e in g["edges"] if e["type"] == "SHARES_CODE_WITH"]
    sim = [f"- {name_of[e['source']]} ↔ {name_of[e['target']]} (score {e['props']['score']}: {', '.join(e['props']['shared'][:6])})"
           for e in g["edges"] if e["type"] == "SIMILAR_STACK"]
    types = Counter(n["type"] for n in g["nodes"])
    return "\n".join([
        "# Project knowledge graph: summary", "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. "
        f"{len(g['nodes'])} nodes ({', '.join(f'{v} {k}' for k, v in types.most_common())}), {len(g['edges'])} relationships.", "",
        "## Projects", *rows, "",
        "## Most used technologies", *[f"- {t}: {n} projects" for t, n in tech_count.most_common(20)], "",
        "## Code reuse between projects", *(reuse or ["- none detected"]), "",
        "## Projects with similar stacks", *(sim or ["- none"]), ""])

# ---------------------------------------------------------------- manual notes
def apply_notes(projects, path):
    if not path.exists():
        return
    try:
        import yaml
    except ImportError:
        print("pyyaml not installed; skipping project_notes.yml", file=sys.stderr); return
    notes = yaml.safe_load(path.read_text()) or {}
    for name, n in notes.items():
        p = projects.get(name)
        if not p or not n:
            continue
        if n.get("description"): p["description"] = n["description"]
        p["kind"] = n.get("kind", "")
        for c in n.get("remove_concepts") or []: p["concepts"].pop(c, None)
        for c in n.get("add_concepts") or []: p["concepts"][c] = max(p["concepts"].get(c, 0), 1000)
        p["related"] = n.get("related") or {}

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos-file", default=str(ROOT / "repos.txt"))
    ap.add_argument("--repos-dir", default=str(ROOT / "_repos"))
    ap.add_argument("--out", default=str(ROOT / "graphs"))
    ap.add_argument("--clone", action="store_true", help="clone / update repos before scanning")
    a = ap.parse_args()
    repos = [l.strip() for l in open(a.repos_file) if l.strip() and not l.startswith("#")]
    rdir = Path(a.repos_dir); rdir.mkdir(parents=True, exist_ok=True)
    projects, warnings = {}, []
    for full in repos:
        name = full.split("/")[1]
        path = rdir / name
        if a.clone:
            if path.exists():
                subprocess.run(["git", "-C", str(path), "pull", "-q", "--ff-only"], capture_output=True)
            else:
                subprocess.run(["git", "clone", "-q", "--filter=blob:limit=2m", f"https://github.com/{full}.git", str(path)], capture_output=True)
        if not path.exists():
            print(f"skip {full}: not found", file=sys.stderr); continue
        p = scan_repo(path, full)
        projects[name] = p
        for s in p["secret_files"]:
            warnings.append(f"{full}: {s} is committed and appears to contain real secrets")
        print(f"scanned {name:40s} techs={len(p['techs']):3d} libs={len(p['libs']):4d} concepts={len(p['concepts'])}")
    apply_notes(projects, ROOT / "project_notes.yml")
    g = build(projects)
    write_outputs(g, projects, Path(a.out))
    print(f"graph: {len(g['nodes'])} nodes, {len(g['edges'])} edges -> {a.out}")
    for w in warnings:
        print("WARNING:", w, file=sys.stderr)

if __name__ == "__main__":
    main()
