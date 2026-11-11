#!/usr/bin/env python3
"""Move extra copies of byte-identical files to Media/Duplicates/<same relative path>.

Input: ~/media-reorg/dupes.tsv from dupes.py (group, size, relative path).
Per group one file is KEPT: non-Archive first, then a name without a -N suffix, then the shortest path.
DB-driven, same safety model as reorgdb.py / trdb.py (nothing deleted or overwritten):
  dryrun : plan into dup.db (status PLANNED), check targets are free and sources still match
  run    : per row: re-check size + first 64KB equal to the kept file -> os.link(src,dst) -> verify inode+size
           -> unlink old name.  PLANNED -> LINKING -> LINKED -> DONE ; FAILED stops (rerun resumes)
  verify : every src gone, every dst present (right size), every kept file present, global count+size unchanged
  status : counts per status
"""
import os, re, random, sqlite3, sys, time, collections

BASE = "/mnt/caglar/Media"
DUPS = f"{BASE}/Duplicates"
DB = os.path.expanduser("~/media-reorg/dup.db")
TSV = os.path.expanduser("~/media-reorg/dupes.tsv")
SUFFIX = re.compile(r"-\d+(\.[^./]+)?$")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def db():
    c = sqlite3.connect(DB, isolation_level=None)
    c.execute("PRAGMA synchronous=FULL")
    c.execute("""CREATE TABLE IF NOT EXISTS ops(id INTEGER PRIMARY KEY, grp INTEGER, src TEXT UNIQUE, dst TEXT UNIQUE,
                 keep TEXT, size INTEGER, status TEXT, error TEXT, updated_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    return c


def lstat_retry(p, tries=6):
    """NFS to this NAS sometimes says 'missing' for existing files: refresh dir, wait, retry."""
    for k in range(tries):
        try:
            return os.lstat(p)
        except FileNotFoundError:
            if k == tries - 1:
                raise
            log(f"lstat retry {k + 1}: {p}")
            os.listdir(os.path.dirname(p))
            time.sleep(10 if k == 0 else random.uniform(1, 2))


def totals():
    n = s = 0
    for r, _, fs in os.walk(BASE):
        for f in fs:
            n += 1
            s += lstat_retry(os.path.join(r, f)).st_size
    return n, s


def head(p):
    with open(p, "rb") as f:
        return f.read(65536)


def keep_key(rel):
    stem = os.path.basename(rel)
    return (rel.startswith("Archive/"), bool(SUFFIX.search(stem)), len(rel), rel)


def cmd_dryrun():
    c = db()
    if c.execute("SELECT count(*) FROM ops").fetchone()[0]:
        sys.exit("plan already in dup.db - not overwriting")
    groups = collections.defaultdict(list)
    for line in open(TSV, encoding="utf-8", errors="surrogateescape"):
        g, s, p = line.rstrip("\n").split("\t")
        groups[int(g)].append((int(s), p))
    plan, problems = [], []
    for g, fs in sorted(groups.items()):
        fs.sort(key=lambda f: keep_key(f[1]))
        keep = fs[0][1]
        if not os.path.exists(f"{BASE}/{keep}"):
            problems.append(f"kept file missing: {keep}")
        for size, rel in fs[1:]:
            src, dst = f"{BASE}/{rel}", f"{DUPS}/{rel}"
            if not os.path.exists(src) or os.lstat(src).st_size != size:
                problems.append(f"source missing/changed: {rel}")
            if os.path.lexists(dst):
                problems.append(f"target exists: {dst}")
            plan.append((g, src, dst, f"{BASE}/{keep}", size))
    if problems:
        for p in problems[:30]:
            log("PROBLEM " + p)
        sys.exit(f"{len(problems)} problems - nothing planned")
    n, s = totals()
    c.execute("BEGIN")
    for row in plan:
        c.execute("INSERT INTO ops(grp,src,dst,keep,size,status,updated_at) VALUES(?,?,?,?,?,'PLANNED',datetime('now'))", row)
    c.execute("INSERT OR REPLACE INTO meta VALUES('files',?)", (str(n),))
    c.execute("INSERT OR REPLACE INTO meta VALUES('bytes',?)", (str(s),))
    c.execute("COMMIT")
    by = collections.Counter(p[1][len(BASE) + 1:].split("/")[0] for p in plan)
    log(f"planned {len(plan)} moves in {len(groups)} groups, {sum(p[4] for p in plan) / 1e9:.2f} GB; by folder {dict(by)}")
    log(f"totals {n} files {s} bytes")
    for g, src, dst, keep, _ in plan[:5]:
        print(f"  keep {keep[len(BASE) + 1:]}\n   move {src[len(BASE) + 1:]} -> {dst[len(BASE) + 1:]}")


FIRST_WAIT, RETRIES, PAUSE = 10, 5, (1.0, 2.0)  # the NAS can't take bursts


def cmd_run():
    c = db()
    ids = [r[0] for r in c.execute("SELECT id FROM ops WHERE status NOT IN ('DONE','VERIFIED') ORDER BY id")]
    done = 0
    for id_ in ids:
        for attempt in range(RETRIES + 1):
            try:
                move_one(c, id_)
                break
            except FileNotFoundError as e:
                # NFS sometimes reports existing files as missing under load: refresh the dir listing, wait, retry
                src, keep = c.execute("SELECT src,keep FROM ops WHERE id=?", (id_,)).fetchone()
                if attempt == RETRIES:
                    c.execute("UPDATE ops SET status='FAILED',error=?,updated_at=datetime('now') WHERE id=?", (str(e), id_))
                    sys.exit(f"FAILED op {id_} after {RETRIES} retries: {e}")
                log(f"op {id_}: {e.strerror} - retry {attempt + 1}/{RETRIES}")
                for d in {os.path.dirname(src), os.path.dirname(keep)}:
                    try:
                        os.listdir(d)
                    except OSError:
                        pass
                time.sleep(FIRST_WAIT if attempt == 0 else random.uniform(*PAUSE))
        done += 1
        if done % 250 == 0:
            log(f"{done}/{len(ids)} moved")
        time.sleep(random.uniform(*PAUSE))
    log(f"run finished: {done} moved")


def move_one(c, id_):
    src, dst, keep, size, st = c.execute("SELECT src,dst,keep,size,status FROM ops WHERE id=?", (id_,)).fetchone()
    if True:
        try:
            if st in ("PLANNED", "FAILED", "LINKING"):
                if not (st == "LINKING" and os.path.exists(dst)):
                    if os.lstat(src).st_size != size or os.lstat(keep).st_size != size or head(src) != head(keep):
                        raise RuntimeError("source no longer matches kept file - not moved")
                c.execute("UPDATE ops SET status='LINKING',updated_at=datetime('now') WHERE id=?", (id_,))
                if not (st == "LINKING" and os.path.exists(dst)):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    os.link(src, dst)  # FileExistsError instead of overwrite
                a, b = os.lstat(src), os.lstat(dst)
                if (a.st_ino, a.st_dev) != (b.st_ino, b.st_dev) or b.st_size != size:
                    raise RuntimeError("link verify failed (nothing removed)")
                c.execute("UPDATE ops SET status='LINKED',updated_at=datetime('now') WHERE id=?", (id_,))
                st = "LINKED"
            if st == "LINKED":
                if not os.path.exists(src):  # NFS may say "missing" falsely: refresh and look again
                    os.listdir(os.path.dirname(src))
                    time.sleep(random.uniform(*PAUSE))
                if os.path.exists(src):
                    a, b = os.lstat(src), os.lstat(dst)
                    if (a.st_ino, a.st_dev) != (b.st_ino, b.st_dev):
                        raise RuntimeError("src and dst are different files - refusing unlink")
                    os.unlink(src)
                c.execute("UPDATE ops SET status='DONE',error=NULL,updated_at=datetime('now') WHERE id=?", (id_,))
        except FileNotFoundError:
            raise  # retried by cmd_run
        except Exception as e:
            c.execute("UPDATE ops SET status='FAILED',error=?,updated_at=datetime('now') WHERE id=?", (str(e), id_))
            sys.exit(f"FAILED op {id_}: {src} -> {dst}: {e}")


def cmd_verify():
    c = db()
    bad = 0
    for id_, src, dst, keep, size in c.execute("SELECT id,src,dst,keep,size FROM ops").fetchall():
        if os.path.lexists(src) or not os.path.exists(dst) or os.lstat(dst).st_size != size or not os.path.exists(keep):
            bad += 1
            log(f"BAD {id_}: {src} -> {dst}")
    n, s = totals()
    en, es = (int(c.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()[0]) for k in ("files", "bytes"))
    log(f"global: files {n} (expected {en}), bytes {s} (expected {es}); bad rows {bad}")
    if bad or n != en or s != es:
        sys.exit("NOT verified")
    c.execute("UPDATE ops SET status='VERIFIED' WHERE status='DONE'")
    log("VERIFIED")


def cmd_status():
    for r in db().execute("SELECT status,count(*) FROM ops GROUP BY status"):
        print(*r)


if __name__ == "__main__":
    {"dryrun": cmd_dryrun, "run": cmd_run, "verify": cmd_verify, "status": cmd_status}[sys.argv[1]]()
