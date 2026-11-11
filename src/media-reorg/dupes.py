#!/usr/bin/env python3
"""Read-only: find byte-identical files under /mnt/caglar/Media (size -> first 64KB hash -> full sha256)."""
import os, hashlib, collections, time
BASE = "/mnt/caglar/Media"
OUT = os.path.expanduser("~/media-reorg/dupes.tsv")
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def h(p, n=None):
    x = hashlib.sha256()
    with open(p, "rb") as f:
        if n: x.update(f.read(n))
        else:
            for b in iter(lambda: f.read(1 << 20), b""): x.update(b)
    return x.hexdigest()
by_size = collections.defaultdict(list)
for r, _, fs in os.walk(BASE):
    for f in fs:
        p = os.path.join(r, f); by_size[os.lstat(p).st_size].append(p)
cand = {s: ps for s, ps in by_size.items() if len(ps) > 1 and s > 0}
log(f"same-size candidates: {sum(len(v) for v in cand.values())} files, {sum(s*len(v) for s,v in cand.items())/1e9:.1f} GB")
groups = []
for s, ps in cand.items():
    pre = collections.defaultdict(list)
    for p in ps: pre[h(p, 65536)].append(p)
    for qs in pre.values():
        if len(qs) < 2: continue
        full = collections.defaultdict(list)
        for p in qs: full[h(p) if s > 65536 else "small"].append(p)
        groups += [(s, g) for g in full.values() if len(g) > 1]
zero = by_size.get(0, [])
groups.sort(key=lambda g: -g[0] * (len(g[1]) - 1))
with open(OUT, "w", encoding="utf-8", errors="surrogateescape") as o:
    for i, (s, g) in enumerate(groups, 1):
        for p in sorted(g): o.write(f"{i}\t{s}\t{p[len(BASE)+1:]}\n")
extra = sum(len(g) - 1 for _, g in groups)
log(f"groups {len(groups)} | files in groups {sum(len(g) for _,g in groups)} | extra copies {extra} | reclaimable {sum(s*(len(g)-1) for s,g in groups)/1e9:.2f} GB | empty files {len(zero)}")
cats = collections.Counter(g[0][len(BASE)+1:].split('/')[0] for _, g in groups for _ in g[1:])
log(f"extra copies by top folder: {dict(cats)}")
log(f"written {OUT}")
