# Project Knowledge Graph

A knowledge graph of all my GitHub projects: what each one is built with, what it's about, which services it calls, who worked on it, and how projects connect to each other (shared stacks and reused code).

It rebuilds itself every Monday, commits the updated graphs here, publishes interactive viewers to GitHub Pages, and loads everything into Neo4j.

## What's in the graph

| Node | Examples | Comes from |
|---|---|---|
| **Project** | Shield, ResearchReel, Labsmart | `repos.txt` + git history (commits, last activity, status) |
| **Component** | `frontend`, `backend`, `ml_service` | sub-folders with their own `package.json` / `requirements.txt` / `Dockerfile` |
| **Technology** | React, FastAPI, PostgreSQL, LangChain, PyTorch | dependencies, Python imports, Dockerfiles, docker-compose images |
| **Library** | every declared npm / pip package | `package.json`, `requirements*.txt`, `pyproject.toml` |
| **Service** | OpenAI API, OpenRouter, MapmyIndia, Redis | `.env.example` variable **names** (values are never read) and compose files |
| **Platform** | Docker, GitHub Actions, Render, Vercel, Kaggle | workflows, deploy configs, notebooks |
| **Concept** | RAG, Healthcare, Route optimisation | README keywords + `project_notes.yml` |
| **Language** | Python, TypeScript | file extensions |
| **Person** | contributors | git authors (names only; emails are never stored) |

| Relationship | Meaning |
|---|---|
| `USES`, `DEPENDS_ON`, `WRITTEN_IN`, `CONNECTS_TO`, `DEPLOYS_WITH`, `AUTOMATED_BY` | project → its stack |
| `HAS_COMPONENT` | project → sub-app (components also `USES` technologies) |
| `ABOUT` | project → concept (`source: manual` when it comes from `project_notes.yml`) |
| `CONTRIBUTED_TO` | person → project, with commit count |
| `IMPLEMENTS` | library → technology (e.g. `mongoose` → MongoDB) |
| `SIMILAR_STACK` | project ↔ project with high technology overlap (`score`, `shared`) |
| `SHARES_CODE_WITH` | newer project → older project with identical source files (`identical_files`, `examples`) |
| `EVOLVED_INTO`, `STARTED_FROM_TEMPLATE_OF` | hand-written links from `project_notes.yml` |

## Files

```
repos.txt                    which repos to scan (owner/name, one per line)
project_notes.yml            hand-written descriptions and concept fixes
scripts/build_graph.py       scanner + graph builder
scripts/load_neo4j.py        loads the graph into Neo4j
scripts/viewer_template.html interactive viewer
graphs/all/                  combined graph: graph.json, graph.cypher, index.html
graphs/projects/<name>/      one graph per project, same three files
graphs/summary.md            table of all projects, top technologies, code reuse
.github/workflows/build-graph.yml   weekly rebuild + Neo4j load + Pages deploy
```

## Viewing it

- **On GitHub Pages** (after making the repo public and setting **Settings → Pages → Source** to *GitHub Actions*): the combined graph is at `https://goldypahal.github.io/project-knowledge-graph/` and each project at `.../projects/<name>/`.
- **Locally:** open `graphs/all/index.html` (or any project's `index.html`) in a browser.
- **Summary:** [graphs/summary.md](graphs/summary.md).

## Setting up Neo4j (one time)

1. Create a free instance at [Neo4j AuraDB](https://neo4j.com/cloud/platform/aura-graph-database/) and download the credentials file it gives you.
2. In this repo go to **Settings → Secrets and variables → Actions** and add:
   - `NEO4J_URI` (looks like `neo4j+s://xxxxxxxx.databases.neo4j.io`)
   - `NEO4J_USERNAME` (usually `neo4j`)
   - `NEO4J_PASSWORD`
3. Go to **Actions → Build project knowledge graph → Run workflow**.

Or load it from your own machine:

```bash
pip install neo4j
export NEO4J_URI=... NEO4J_USERNAME=neo4j NEO4J_PASSWORD=...
python scripts/load_neo4j.py --replace
```

You can also paste `graphs/all/graph.cypher` straight into Neo4j Browser.

## Useful Cypher queries

```cypher
// Everything one project is built with
MATCH (p:Project {name: "Shield"})-[r]->(x) RETURN p, r, x;

// Which projects use FastAPI and PostgreSQL? (find code to copy)
MATCH (p:Project)-[:USES]->(:Technology {name: "FastAPI"}),
      (p)-[:USES]->(:Technology {name: "PostgreSQL"})
RETURN p.name, p.last_commit ORDER BY p.last_commit DESC;

// If I upgrade a library, which projects are affected?
MATCH (l:Library {name: "langchain"})<-[:DEPENDS_ON]-(p:Project) RETURN p.name;

// All my RAG work
MATCH (p:Project)-[:ABOUT]->(:Concept {name: "Retrieval-Augmented Generation (RAG)"})
RETURN p.name, p.description;

// Which external APIs do I depend on, and where?
MATCH (p:Project)-[:CONNECTS_TO]->(s:Service)
RETURN s.name, collect(p.name) AS projects ORDER BY size(projects) DESC;

// Code reused between projects
MATCH (a:Project)-[r:SHARES_CODE_WITH]->(b:Project)
RETURN a.name, b.name, r.identical_files, r.examples;

// Projects I haven't touched in 3 months
MATCH (p:Project {status: "dormant"}) RETURN p.name, p.last_commit;

// Who have I worked with, and on what?
MATCH (me:Person {name: "Goldy Pahal"})-[:CONTRIBUTED_TO]->(p)<-[:CONTRIBUTED_TO]-(other:Person)
RETURN other.name, collect(p.name);

// My most-used technologies
MATCH (t:Technology)<-[:USES]-(p:Project)
RETURN t.name, t.category, count(p) AS projects ORDER BY projects DESC LIMIT 20;
```

## Keeping it up to date

- **New repo:** add `owner/name` to `repos.txt` and push. The workflow rebuilds automatically.
- **Wrong or missing description / topic:** edit `project_notes.yml` and push.
- **Private repos:** create a fine-grained token with read access to those repos and add it as the `REPOS_TOKEN` secret.
- **Run locally:** `pip install pyyaml && python scripts/build_graph.py --clone`

## Privacy

`.env` files are only read for variable names, never values. Emails are only used to merge author identities and are never written to the graph. The scanner prints a warning when a committed `.env` looks like it holds real secrets.
