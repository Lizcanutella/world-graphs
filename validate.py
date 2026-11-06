"""Integrity check for this dataset. Standard library only.

    python validate.py

Checks the file hashes in manifest.json, then the structure of every graph: unique node codes,
simple undirected edges between known nodes, and every edge's corroborated flag against its
sources (schema 1: any source; schema 2: a hand decision or at least two independent sources).
"""
import csv
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    man = json.load(open(os.path.join(ROOT, "manifest.json"), encoding="utf-8"))
    for rel, digest in man["sha256"].items():
        with open(os.path.join(ROOT, rel), "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != digest:
                fail(f"sha256 mismatch: {rel}")
    total_e = 0
    for entry in man["index"]:
        sub = "countries" if entry["kind"] == "country" else "world"
        g = json.load(open(os.path.join(ROOT, "data", sub, entry["id"] + ".json"), encoding="utf-8"))
        codes = [n["code"] for n in g["nodes"]]
        if len(set(codes)) != len(codes) or len(codes) != g["n"]:
            fail(f"{g['id']}: node codes not unique or n mismatch")
        known, seen = set(codes), set()
        for e in g["edges"]:
            u, v = e["u"], e["v"]
            if u == v or u not in known or v not in known:
                fail(f"{g['id']}: bad edge {u}-{v}")
            key = tuple(sorted((u, v)))
            if key in seen:
                fail(f"{g['id']}: duplicate edge {u}-{v}")
            seen.add(key)
            src = [x["source"] for x in e["sources"]]
            want = ("hand" in src or len(src) >= 2) if g.get("schema") == "region-adjacency/2" \
                else bool(src)
            if e["corroborated"] != want:
                fail(f"{g['id']}: corroborated flag disagrees with sources on {u}-{v}")
        if len(seen) != g["m"]:
            fail(f"{g['id']}: m mismatch")
        total_e += g["m"]
    with open(os.path.join(ROOT, "data", "edges.csv"), encoding="utf-8") as fh:
        if sum(1 for _ in csv.reader(fh)) - 1 != total_e:
            fail("edges.csv row count differs from the graphs")
    print(f"OK: {len(man['index'])} graphs, {total_e} edges")


if __name__ == "__main__":
    main()
