#!/usr/bin/env python3
# Plan-building step 2 (run in the dry-run work dir)
import re, csv, os, collections, datetime as dt
CAT = {}
for e in "jpg jpeg png webp heic bmp gif".split(): CAT[e]="Pictures"
for e in "mov mp4 mpg 3gp ts".split(): CAT[e]="Videos"
for e in "opus mp3 m4a aac".split(): CAT[e]="Audios"
M = "/mnt/caglar/Media"
inv = set(l.split("\t")[0] for l in open("inventory-before.txt", encoding="utf-8", errors="replace"))
rows = {r["SourceFile"][2:]: r for r in csv.DictReader(open("dates.csv", encoding="utf-8", errors="replace"))}
DRE = re.compile(r"^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")
def parse(v):
    m = DRE.match(v or "")
    if not m: return None
    try: return dt.datetime(*map(int, m.groups()))
    except ValueError: return None
NRE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[-_. ]?([01]\d|2[0-3])[-_.]?([0-5]\d)[-_.]?([0-5]\d))?(?!\d)")
NOW = dt.datetime(2026, 11, 12)
def namedate(fn):
    for m in NRE.finditer(fn):
        y, mo, d, H, Mi, S = m.groups()
        try: t = dt.datetime(int(y), int(mo), int(d), int(H or 0), int(Mi or 0), int(S or 0))
        except ValueError: continue
        if dt.datetime(1990,1,1) <= t <= NOW: return t
    return None
def add66(t):
    try: return t.replace(year=t.year+66)
    except ValueError: return t.replace(year=t.year+66, day=28)
plan, srcs = [], collections.Counter()
for p in sorted(rows):
    fn = os.path.basename(p); ext = fn.rsplit(".",1)[-1]
    cat = CAT.get(ext.lower())
    if not cat: continue
    r = rows[p]; flags = []
    dto, cd, mt = parse(r.get("DateTimeOriginal")), parse(r.get("CreateDate")), parse(r.get("FileModifyDate"))
    if dto and dto.year < 1970: dto = None
    nd = namedate(fn)
    if dto: t, s = dto, "DateTimeOriginal"
    elif cd and cd.year >= 1970: t, s = cd, "CreateDate"
    elif cd and cd.year < 1970: t, s = add66(cd), "CreateDate+66y"
    elif nd: t, s = nd, "FileNameDate"
    else: t, s = mt, "FileModifyDate"
    if nd and nd.date() != t.date(): flags.append("NAME_DATE_DIFFERS")
    if t.year < 1990 or t > NOW: flags.append("SUSPICIOUS_YEAR")
    srcs[(cat, s)] += 1
    plan.append([cat, p, t, s, flags])
# names + suffix (like exiftool %-c), never collide with planned or existing non-moved files
taken = set(f"{M}/{x}" for x in inv) - set(f"{M}/{x[1]}" for x in plan)
out = []
for cat, p, t, s, flags in plan:
    fn = os.path.basename(p); stem, ext = fn.rsplit(".",1)
    base = f"{M}/{cat}/{t:%Y}/{t:%Y-%m}/{t:%Y%m%d_%H%M%S}_{stem}"
    tgt, n = f"{base}.{ext}", 0
    while tgt in taken: n += 1; tgt = f"{base}-{n}.{ext}"
    taken.add(tgt)
    if n: flags.append("SUFFIX")
    out.append((cat, p, tgt, s, ",".join(flags)))
with open("dryrun2-plan.tsv", "w", encoding="utf-8") as f:
    f.write("category\tsource\ttarget\tdate_source\tflags\n")
    for o in out: f.write("\t".join(o) + "\n")
# compare with v1
v1 = {}
for line in list(open("dryrun-plan.tsv", encoding="utf-8"))[1:]:
    c = line.rstrip("\n").split("\t"); v1[c[1]] = c[2]
print("planned:", len(out), "| unique targets:", len(set(o[2] for o in out)))
print("by category:", dict(collections.Counter(o[0] for o in out)))
print("date source:")
for k, v in sorted(srcs.items()): print(f"   {k[0]:8s} {k[1]:18s} {v}")
yrs = collections.Counter(re.search(r"/(\d{4})/\d{4}-", o[2]).group(1) for o in out)
print("years:", dict(sorted(yrs.items())))
fl = collections.Counter(f for o in out for f in o[4].split(",") if f)
print("flags:", dict(fl))
ch = sum(1 for o in out if v1.get(o[1]) != o[2])
print("targets changed vs dry run 1:", ch)
print("examples (+66y):"); [print("   ", o[1], "->", o[2].replace(M+"/","")) for o in out if o[3]=="CreateDate+66y"][:0]
for o in [o for o in out if o[3]=="CreateDate+66y"][:3]: print("   ", o[1], "->", o[2].replace(M+"/",""))
print("examples (name date):")
for o in [o for o in out if o[3]=="FileNameDate"][:4]: print("   ", o[1], "->", o[2].replace(M+"/",""))
print("suspicious:")
for o in [o for o in out if "SUSPICIOUS_YEAR" in o[4]][:8]: print("   ", o[1], "->", o[2].replace(M+"/",""), o[3])
