#!/usr/bin/env python3
"""
Load graphs/all/graph.json into Neo4j.

Credentials come from environment variables (never hard-code them):
    NEO4J_URI       e.g. neo4j+s://xxxxxxxx.databases.neo4j.io
    NEO4J_USERNAME  usually "neo4j"
    NEO4J_PASSWORD

Usage:
    python scripts/load_neo4j.py              # upsert (MERGE) everything
    python scripts/load_neo4j.py --replace    # delete previously loaded nodes first, then load
    python scripts/load_neo4j.py --dry-run    # print what would be loaded

Every node gets the label :Entity plus its type label (:Project, :Technology, ...)
and a unique `id`, so re-running is safe.
"""
import argparse, json, os, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = {"Project", "Component", "Technology", "Library", "Language", "Service", "Platform", "Concept", "Person"}


def flat(props):
    """Neo4j properties must be primitives or lists of primitives."""
    out = {}
    for k, v in props.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=str(ROOT / "graphs" / "all" / "graph.json"))
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    g = json.loads(Path(a.graph).read_text())

    nodes_by_label = defaultdict(list)
    for n in g["nodes"]:
        if n["type"] not in LABELS:
            continue
        nodes_by_label[n["type"]].append({"id": n["id"], "props": {"name": n["label"], **flat(n["props"])}})
    rels_by_type = defaultdict(list)
    for e in g["edges"]:
        t = e["type"]
        if not t.replace("_", "").isalnum():
            continue
        rels_by_type[t].append({"s": e["source"], "t": e["target"], "props": flat(e["props"])})

    print(f"{sum(map(len, nodes_by_label.values()))} nodes, {sum(map(len, rels_by_type.values()))} relationships")
    if a.dry_run:
        for k, v in nodes_by_label.items(): print(f"  :{k:12s} {len(v)}")
        for k, v in rels_by_type.items(): print(f"  [:{k}] {len(v)}")
        return

    uri, user, pw = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"))
    if not (uri and pw):
        sys.exit("Set NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD first.")
    from neo4j import GraphDatabase

    with GraphDatabase.driver(uri, auth=(user or "neo4j", pw)) as driver:
        driver.verify_connectivity()
        with driver.session() as s:
            s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE").consume()
            if a.replace:
                s.run("MATCH (n:Entity) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS").consume()
            for label, rows in nodes_by_label.items():
                # label comes from the fixed LABELS allow-list, so formatting it in is safe
                s.run(f"UNWIND $rows AS row MERGE (n:Entity {{id: row.id}}) SET n:{label}, n += row.props",
                      rows=rows).consume()
            for rtype, rows in rels_by_type.items():
                s.run(f"UNWIND $rows AS row MATCH (a:Entity {{id: row.s}}), (b:Entity {{id: row.t}}) "
                      f"MERGE (a)-[r:{rtype}]->(b) SET r += row.props", rows=rows).consume()
            n = s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
            r = s.run("MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS c").single()["c"]
    print(f"Loaded. Database now has {n} nodes and {r} relationships.")


if __name__ == "__main__":
    main()
