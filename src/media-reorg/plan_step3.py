#!/usr/bin/env python3
# Plan-building step 3 (run in the dry-run work dir)
import collections
M = "/mnt/caglar/Media"
lines = list(open("dryrun2-plan.tsv", encoding="utf-8"))
plan = [l.rstrip("\n").split("\t") for l in lines[1:]]
moved = set(p[1] for p in plan)
inv = [l.split("\t")[0] for l in open("inventory-before.txt", encoding="utf-8", errors="replace")]
left = sorted(p for p in inv if p not in moved)
targets = set(p[2] for p in plan)
existing = set(f"{M}/{p}" for p in inv)
arch = []
for p in left:
    t = f"{M}/Archive/{p}"
    assert t not in targets and t not in existing, t
    arch.append(["Archive", p, t, "-", "LEFTOVER"])
allrows = plan + arch
assert len(allrows) == len(inv) == len(set(r[1] for r in allrows)), "every file exactly once"
assert len(set(r[2] for r in allrows)) == len(allrows), "unique targets"
with open("dryrun3-plan.tsv", "w", encoding="utf-8") as f:
    f.write(lines[0])
    for r in allrows: f.write("\t".join(r) + "\n")
print("rows:", len(allrows), "= inventory", len(inv))
print(dict(collections.Counter(r[0] for r in allrows)))
tops = collections.Counter(p.split("/")[0] for p in left)
print("Archive/ top folders:", dict(tops))
