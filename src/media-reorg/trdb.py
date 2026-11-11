#!/usr/bin/env python3
"""Rename files under /mnt/caglar/Media: Turkish letters -> ASCII (ç->c, ğ->g, ı->i, İ->I, ö->o, ş->s, ü->u).

DB-driven, same safety model as reorgdb.py:
  dryrun : scan, plan every rename into tr.db (status PLANNED), nothing touched on disk
  run    : walk the DB; os.link(old,new) (never overwrites) -> verify inode+size -> unlink old name
           status per row: PLANNED -> LINKING -> LINKED -> DONE ; FAILED stops the run
  verify : every old name gone, every new name present with the right size, global count+size unchanged
  status : counts per status
Name collisions get a -N suffix before the extension; nothing is ever deleted or overwritten.
"""
import os, sqlite3, sys, time, unicodedata

BASE = "/mnt/caglar/Media"
DB = os.path.expanduser("~/media-reorg/tr.db")
MAP = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def conv(name):
    n = unicodedata.normalize("NFC", name).replace("i̇", "i")
    return n.translate(MAP)


def db():
    c = sqlite3.connect(DB, isolation_level=None)
    c.execute("PRAGMA synchronous=FULL")
    c.execute("""CREATE TABLE IF NOT EXISTS ops(id INTEGER PRIMARY KEY, src TEXT UNIQUE, dst TEXT UNIQUE,
                 size INTEGER, flags TEXT, status TEXT, error TEXT, updated_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    return c


def walk_totals():
    cnt = size = 0
    for root, _, fs in os.walk(BASE):
        for f in fs:
            cnt += 1
            size += os.lstat(os.path.join(root, f)).st_size
    return cnt, size


def cmd_dryrun():
    c = db()
    if c.execute("SELECT count(*) FROM ops").fetchone()[0]:
        sys.exit("plan already exists in tr.db - not overwriting")
    plan, tr_dirs = [], []
    for root, ds, fs in os.walk(BASE):
        for d in ds:
            if conv(d) != d:
                tr_dirs.append(os.path.join(root, d))
        existing = set(fs)
        taken = set(fs)
        for f in sorted(fs):
            new = conv(f)
            if new == f:
                continue
            flags = ""
            if new in taken:
                stem, ext = os.path.splitext(new)
                k = 1
                while f"{stem}-{k}{ext}" in taken:
                    k += 1
                new = f"{stem}-{k}{ext}"
                flags = "suffix"
            taken.add(new)
            src = os.path.join(root, f)
            plan.append((src, os.path.join(root, new), os.lstat(src).st_size, flags))
    cnt, size = walk_totals()
    c.execute("BEGIN")
    for s, d, sz, fl in plan:
        c.execute("INSERT INTO ops(src,dst,size,flags,status,updated_at) VALUES(?,?,?,?, 'PLANNED', datetime('now'))",
                  (s, d, sz, fl))
    c.execute("INSERT OR REPLACE INTO meta VALUES('files',?)", (str(cnt),))
    c.execute("INSERT OR REPLACE INTO meta VALUES('bytes',?)", (str(size),))
    c.execute("COMMIT")
    rep = os.path.expanduser("~/media-reorg/tr-dryrun.tsv")
    with open(rep, "w", encoding="utf-8", errors="surrogateescape") as o:
        o.write("old\tnew\tflags\n")
        for s, d, _, fl in plan:
            o.write(f"{s[len(BASE)+1:]}\t{d[len(BASE)+1:]}\t{fl}\n")
    log(f"planned {len(plan)} renames ({sum(1 for p in plan if p[3])} with suffix); totals {cnt} files {size} bytes")
    log(f"dirs with Turkish letters (NOT renamed): {len(tr_dirs)}")
    for d in tr_dirs:
        print("  DIR", d[len(BASE)+1:])
    log(f"plan file: {rep}")


def cmd_run():
    c = db()
    for id_, src, dst, size, st in c.execute(
            "SELECT id,src,dst,size,status FROM ops WHERE status NOT IN ('DONE','VERIFIED') ORDER BY id").fetchall():
        try:
            if st in ("PLANNED", "FAILED", "LINKING"):
                c.execute("UPDATE ops SET status='LINKING',updated_at=datetime('now') WHERE id=?", (id_,))
                if not (st == "LINKING" and os.path.exists(dst)):
                    os.link(src, dst)  # FileExistsError instead of overwrite
                a, b = os.lstat(src), os.lstat(dst)
                if (a.st_ino, a.st_dev) != (b.st_ino, b.st_dev) or b.st_size != size:
                    raise RuntimeError("link verify failed (nothing removed)")
                c.execute("UPDATE ops SET status='LINKED',updated_at=datetime('now') WHERE id=?", (id_,))
                st = "LINKED"
            if st == "LINKED":
                if os.path.exists(src):
                    a, b = os.lstat(src), os.lstat(dst)
                    if (a.st_ino, a.st_dev) != (b.st_ino, b.st_dev):
                        raise RuntimeError("src and dst are different files - refusing unlink")
                    os.unlink(src)
                c.execute("UPDATE ops SET status='DONE',error=NULL,updated_at=datetime('now') WHERE id=?", (id_,))
        except Exception as e:
            c.execute("UPDATE ops SET status='FAILED',error=?,updated_at=datetime('now') WHERE id=?", (str(e), id_))
            sys.exit(f"FAILED op {id_}: {src} -> {dst}: {e}")
    log("run finished")


def cmd_verify():
    c = db()
    bad = 0
    for id_, src, dst, size in c.execute("SELECT id,src,dst,size FROM ops").fetchall():
        if os.path.lexists(src) or not os.path.exists(dst) or os.lstat(dst).st_size != size:
            bad += 1
            log(f"BAD {id_}: {src} -> {dst}")
    cnt, size = walk_totals()
    ecnt, esize = (int(c.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()[0]) for k in ("files", "bytes"))
    log(f"global: files {cnt} (expected {ecnt}), bytes {size} (expected {esize}); bad rows {bad}")
    if bad or cnt != ecnt or size != esize:
        sys.exit("NOT verified")
    c.execute("UPDATE ops SET status='VERIFIED' WHERE status='DONE'")
    log("VERIFIED")


DIRS = [("Archive/Pictures/DÜZENLENEN", "Archive/Pictures/Duzenlenen"),
        ("Archive/Pictures/karışık", "Archive/Pictures/Karisik")]


def cmd_dirs():
    c = db()
    c.execute("CREATE TABLE IF NOT EXISTS dirops(src TEXT PRIMARY KEY, dst TEXT, status TEXT, updated_at TEXT)")
    if c.execute("SELECT count(*) FROM ops WHERE status!='VERIFIED'").fetchone()[0]:
        sys.exit("file renames not verified yet - refusing")
    for s, d in DIRS:
        c.execute("INSERT OR IGNORE INTO dirops VALUES(?,?,'PLANNED',datetime('now'))", (s, d))
    for s, d, st in c.execute("SELECT src,dst,status FROM dirops").fetchall():
        S, D = f"{BASE}/{s}", f"{BASE}/{d}"
        if st == "DONE":
            continue
        if os.path.lexists(D):
            if not os.path.lexists(S):
                c.execute("UPDATE dirops SET status='DONE' WHERE src=?", (s,))
                continue
            sys.exit(f"target exists, refusing: {D}")
        os.rename(S, D)
        c.execute("UPDATE dirops SET status='DONE',updated_at=datetime('now') WHERE src=?", (s,))
        log(f"dir renamed: {s} -> {d}")
    cnt, size = walk_totals()
    ecnt, esize = (int(c.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()[0]) for k in ("files", "bytes"))
    log(f"global: files {cnt} (expected {ecnt}), bytes {size} (expected {esize})")
    if cnt != ecnt or size != esize:
        sys.exit("NOT verified")
    log("dirs VERIFIED")


def cmd_status():
    for r in db().execute("SELECT status,count(*) FROM ops GROUP BY status"):
        print(*r)


if __name__ == "__main__":
    {"dryrun": cmd_dryrun, "run": cmd_run, "verify": cmd_verify, "status": cmd_status, "dirs": cmd_dirs}[sys.argv[1]]()
