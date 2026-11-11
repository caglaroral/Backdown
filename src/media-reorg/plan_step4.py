#!/usr/bin/env python3
# Plan-building step 4 (run in the dry-run work dir)
import re, csv, os, collections, datetime as dt
M = "/mnt/caglar/Media"
DOC = set("pdf doc docx xls xlsx ppt pptx odt ods odp txt rtf".split())
lines = list(open("dryrun3-plan.tsv", encoding="utf-8")); hdr = lines[0]
plan = [l.rstrip("\n").split("\t") for l in lines[1:]]
rows = {r["SourceFile"][2:]: r for r in csv.DictReader(open("dates-docs.csv", encoding="utf-8", errors="replace"))}
DRE = re.compile(r"^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")
NOW = dt.datetime(2026, 11, 12)
def parse(v):
    m = DRE.match(v or "")
    if not m: return None
    try: t = dt.datetime(*map(int, m.groups()))
    except ValueError: return None
    return t if dt.datetime(1990,1,1) <= t <= NOW else None
NRE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[-_. ]?([01]\d|2[0-3])[-_.]?([0-5]\d)[-_.]?([0-5]\d))?(?!\d)")
def namedate(fn):
    for m in NRE.finditer(fn):
        y, mo, d, H, Mi, S = m.groups()
        try: t = dt.datetime(int(y), int(mo), int(d), int(H or 0), int(Mi or 0), int(S or 0))
        except ValueError: continue
        if dt.datetime(1990,1,1) <= t <= NOW: return t
    return None
taken = set(r[2] for r in plan)
out, srcs, changed = [], collections.Counter(), 0
for r in plan:
    cat, p = r[0], r[1]
    fn = os.path.basename(p); ext = fn.rsplit(".",1)[-1].lower() if "." in fn else ""
    if cat == "Archive" and ext in DOC:
        d = rows.get(p, {})
        dto, cd, mt, nd = parse(d.get("DateTimeOriginal")), parse(d.get("CreateDate")), parse(d.get("FileModifyDate")), namedate(fn)
        t, s = (dto, "DateTimeOriginal") if dto else (cd, "CreateDate") if cd else (nd, "FileNameDate") if nd else (mt, "FileModifyDate")
        flags = ["NAME_DATE_DIFFERS"] if nd and nd.date() != t.date() else []
        taken.discard(r[2])
        stem, e = fn.rsplit(".",1); base = f"{M}/Documents/{t:%Y}/{t:%Y-%m}/{t:%Y%m%d_%H%M%S}_{stem}"
        tgt, n = f"{base}.{e}", 0
        while tgt in taken: n += 1; tgt = f"{base}-{n}.{e}"
        if n: flags.append("SUFFIX")
        taken.add(tgt); srcs[s] += 1; changed += 1
        out.append(["Documents", p, tgt, s, ",".join(flags)])
    else: out.append(r)
assert len(out) == 23319 and len(set(o[1] for o in out)) == 23319 and len(set(o[2] for o in out)) == 23319
with open("dryrun4-plan.tsv", "w", encoding="utf-8") as f:
    f.write(hdr); [f.write("\t".join(o) + "\n") for o in out]
print("documents moved to Documents/:", changed, "| date source:", dict(srcs))
print("by category:", dict(collections.Counter(o[0] for o in out)))
docs = [o for o in out if o[0] == "Documents"]
print("doc types:", dict(collections.Counter(o[1].rsplit(".",1)[-1].lower() for o in docs)))
yrs = collections.Counter(re.search(r"/Documents/(\d{4})/", o[2]).group(1) for o in docs)
print("years:", dict(sorted(yrs.items())))
print("from folders:", dict(collections.Counter(o[1].split("/")[0] for o in docs)))
print("flags:", dict(collections.Counter(f for o in docs for f in o[4].split(",") if f)))
for o in docs[:5]: print("   ", o[1], "->", o[2].replace(M+"/",""), "|", o[3])
arch = [o for o in out if o[0] == "Archive"]
print("still in Archive:", len(arch), dict(collections.Counter((o[1].rsplit(".",1)[-1].lower() if "." in os.path.basename(o[1]) else "(no ext)") for o in arch).most_common(10)))
