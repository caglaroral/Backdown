#!/usr/bin/env python3
# Plan-building step 1 (run in the dry-run work dir)
import re, csv, os, collections
moves, cat = {}, {}
for c in ("pictures","videos","audios"):
    t = re.sub(r"(Warning|Error): [^\n]*\n", "", open(f"dryrun-{c}.log", encoding="utf-8", errors="replace").read())
    for m in re.finditer(r"^'\./(.*)' --> '(.*)'$", t, re.M): moves[m.group(1)] = m.group(2); cat[m.group(1)] = c
rows = {r["SourceFile"][2:]: r for r in csv.DictReader(open("dates.csv", encoding="utf-8", errors="replace"))}
ok = lambda v: bool(v) and not v.startswith("0000")
pat = re.compile(r"(?<!\d)(20\d{2})[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])(?!\d)")
with open("dryrun-plan.tsv", "w", encoding="utf-8") as f:
    f.write("category\tsource\ttarget\tdate_source\tflag\n")
    for p in sorted(moves):
        r = rows.get(p, {}); src = "DateTimeOriginal" if ok(r.get("DateTimeOriginal")) else "CreateDate" if ok(r.get("CreateDate")) else "FileModifyDate"
        y = int(re.search(r"/(?:Pictures|Videos|Audios)/(\d{4})/", moves[p]).group(1))
        flags = []
        if y < 1970: flags.append("BAD_YEAR_<1970")
        if src == "FileModifyDate": flags.append("FALLBACK_MTIME")
        m = pat.search(os.path.basename(p))
        if m and "".join(m.groups()) != re.search(r"/(\d{8})_\d{6}_", moves[p]).group(1): flags.append("NAME_DATE_DIFFERS")
        if re.search(r"-\d+\.[^./]+$", moves[p]): flags.append("SUFFIX")
        f.write(f"{cat[p]}\t{p}\t{moves[p]}\t{src}\t{','.join(flags)}\n")
print(sum(1 for _ in open("dryrun-plan.tsv"))-1, "rows")
