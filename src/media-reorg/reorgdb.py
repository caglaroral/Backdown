#!/usr/bin/env python3
"""Database-driven, batched, resumable media reorganization for /mnt/caglar/Media.

The SQLite database (~/media-reorg/reorg.db, on local disk) IS the dry-run file and the
progress record. Every operation is a row; every step is committed before the next one.

Operation status flow:
    PLANNED    created from the frozen plan (init)
    VALIDATED  dry run confirmed: source exists with expected size, target free  (INVALID otherwise)
    LINKING    run: about to create the new name (hard link)
    LINKED     new name exists and is verified to be the same file (same inode + size)
    DONE       old name removed; file lives only at the new name
    VERIFIED   batch check confirmed the file at its new name
    FAILED     stopped with an error (see ops.error); nothing is removed in that case

A move never copies or deletes data and never overwrites: os.link() refuses an existing target,
os.unlink() only removes the old name after the new name is verified.

Resume: `run` continues from the database, starting at the first operation of the batch that is
not DONE/VERIFIED. An operation recorded as LINKING or LINKED (interrupted mid-step) is completed
according to its recorded step.

Commands:
    init               create database from ~/media-reorg/dryrun4-plan.tsv (once)
    dryrun             validate every PLANNED/INVALID op, record result per row, write report
    run    --batch N   execute batch N (previous batch must be VERIFIED)
    verify --batch N   verify batch N + global file count/size; mark ops VERIFIED
    status             per-batch summary from the database
    report             write the markdown report from the database
"""
import argparse, os, sqlite3, sys, time

BASE = "/mnt/caglar/Media"
HOME = os.path.expanduser("~/media-reorg")
DB = f"{HOME}/reorg.db"
PLAN = f"{HOME}/dryrun4-plan.tsv"
INVENTORY = f"{HOME}/inventory-before.txt"
REPORT = f"{HOME}/reorg-report.md"
ORDER = {"Documents": 0, "Audios": 1, "Videos": 2, "Pictures": 3, "Archive": 4}
PILOT, CHUNK = 100, 2000
FS = dict(encoding="utf-8", errors="surrogateescape")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def connect():
    db = sqlite3.connect(DB, isolation_level=None)  # autocommit; explicit BEGIN where needed
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    return db


def event(db, cmd, batch, msg):
    db.execute("INSERT INTO events(ts, cmd, batch, msg) VALUES (?,?,?,?)", (now(), cmd, batch, msg))


def set_op(db, op_id, status, error=None):
    db.execute("UPDATE ops SET status=?, updated_at=?, error=? WHERE id=?", (status, now(), error, op_id))


def cmd_init(_):
    if os.path.exists(DB):
        sys.exit(f"{DB} already exists - not overwriting")
    inv = {}
    with open(INVENTORY, **FS) as f:
        for line in f:
            p, size, mtime = line.rstrip("\n").split("\t")
            inv[p] = int(size)
    rows = []
    with open(PLAN, **FS) as f:
        next(f)
        for line in f:
            cat, src, dst, ds, flags = line.rstrip("\n").split("\t")
            rows.append((cat, src, dst, ds, flags))
    rows.sort(key=lambda r: (ORDER[r[0]], r[1]))
    if len(rows) != len(inv) or set(r[1] for r in rows) != set(inv):
        sys.exit("plan does not match inventory")
    db = connect()
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE batches(n INTEGER PRIMARY KEY, first_id INTEGER, last_id INTEGER, files INTEGER,
                             status TEXT, last_done_id INTEGER, started_at TEXT, finished_at TEXT,
                             verified_at TEXT);
        CREATE TABLE ops(id INTEGER PRIMARY KEY, batch INTEGER, category TEXT, src TEXT UNIQUE,
                         dst TEXT UNIQUE, size INTEGER, date_source TEXT, flags TEXT,
                         status TEXT, error TEXT, updated_at TEXT);
        CREATE INDEX ops_batch_status ON ops(batch, status);
        CREATE TABLE events(id INTEGER PRIMARY KEY, ts TEXT, cmd TEXT, batch INTEGER, msg TEXT);
    """)
    db.execute("BEGIN")
    n, bounds, i = len(rows), [], 0
    bounds.append((1, 1, min(PILOT, n)))
    i = min(PILOT, n)
    while i < n:
        bounds.append((len(bounds) + 1, i + 1, min(i + CHUNK, n)))
        i += CHUNK
    batch_of = {}
    for b, first, last in bounds:
        for k in range(first, last + 1):
            batch_of[k] = b
        db.execute("INSERT INTO batches(n, first_id, last_id, files, status) VALUES (?,?,?,?,?)",
                   (b, first, last, last - first + 1, "PLANNED"))
    for k, (cat, src, dst, ds, flags) in enumerate(rows, 1):
        db.execute("INSERT INTO ops(id, batch, category, src, dst, size, date_source, flags, status, updated_at)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (k, batch_of[k], cat, src, dst, inv[src], ds, flags, "PLANNED", now()))
    db.execute("INSERT INTO meta VALUES ('base', ?), ('created_at', ?), ('inventory_files', ?), ('inventory_bytes', ?)",
               (BASE, now(), str(len(inv)), str(sum(inv.values()))))
    event(db, "init", None, f"{n} ops, {len(bounds)} batches")
    db.execute("COMMIT")
    log(f"database created: {DB} ({n} ops, {len(bounds)} batches)")


def cmd_dryrun(_):
    db = connect()
    ops = db.execute("SELECT id, src, dst, size FROM ops WHERE status IN ('PLANNED','INVALID') ORDER BY id").fetchall()
    srcs = set(f"{BASE}/{r[0]}" for r in db.execute("SELECT src FROM ops"))
    good = bad = 0
    db.execute("BEGIN")
    for op_id, src, dst, size in ops:
        sabs, err = f"{BASE}/{src}", None
        try:
            st = os.lstat(sabs)
            if st.st_size != size:
                err = f"source size {st.st_size} != expected {size}"
        except FileNotFoundError:
            err = "source missing"
        if not err and os.path.lexists(dst):
            err = "target already exists"
        if not err and dst in srcs:
            err = "target equals another source path"
        if not err and not dst.startswith(BASE + "/"):
            err = "target outside base"
        set_op(db, op_id, "INVALID" if err else "VALIDATED", err)
        good, bad = good + (not err), bad + bool(err)
    db.execute("UPDATE batches SET status='VALIDATED' WHERE status='PLANNED' AND n NOT IN "
               "(SELECT DISTINCT batch FROM ops WHERE status='INVALID')")
    event(db, "dryrun", None, f"validated {good}, invalid {bad}")
    db.execute("COMMIT")
    log(f"dry run: validated {good}, invalid {bad}")
    cmd_report(None)
    sys.exit(1 if bad else 0)


def cmd_run(a):
    db = connect()
    n = a.batch
    b = db.execute("SELECT status FROM batches WHERE n=?", (n,)).fetchone()
    if not b:
        sys.exit("no such batch")
    if n > 1:
        prev = db.execute("SELECT status FROM batches WHERE n=?", (n - 1,)).fetchone()[0]
        if prev != "VERIFIED":
            sys.exit(f"batch {n - 1} is {prev}, not VERIFIED - refusing to start batch {n}")
    bad = db.execute("SELECT COUNT(*) FROM ops WHERE batch=? AND status IN ('PLANNED','INVALID','FAILED')", (n,)).fetchone()[0]
    if bad:
        sys.exit(f"batch {n} has {bad} ops not VALIDATED (or FAILED) - run dryrun / inspect first")
    db.execute("UPDATE batches SET status='RUNNING', started_at=COALESCE(started_at, ?) WHERE n=?", (now(), n))
    event(db, "run", n, "start")
    todo = db.execute("SELECT id, src, dst, size, status FROM ops WHERE batch=? AND status NOT IN ('DONE','VERIFIED') "
                      "ORDER BY id", (n,)).fetchall()
    log(f"batch {n}: {len(todo)} ops to process (resuming from database)")
    moved = 0
    for op_id, src, dst, size, status in todo:
        sabs = f"{BASE}/{src}"
        try:
            if status == "VALIDATED":
                set_op(db, op_id, "LINKING")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.link(sabs, dst)  # never overwrites: raises FileExistsError
                status = "LINKING"
            if status == "LINKING":
                # recorded step: link was being created. Confirm it now exists and is the same file.
                if not os.path.lexists(dst):
                    os.link(sabs, dst)
                s1, s2 = os.lstat(sabs), os.lstat(dst)
                if (s1.st_ino, s1.st_dev) != (s2.st_ino, s2.st_dev) or s2.st_size != size:
                    raise RuntimeError("target exists but is not the same file / wrong size")
                set_op(db, op_id, "LINKED")
                status = "LINKED"
            if status == "LINKED":
                if os.path.lexists(sabs):
                    s1, s2 = os.lstat(sabs), os.lstat(dst)
                    if (s1.st_ino, s1.st_dev) != (s2.st_ino, s2.st_dev):
                        raise RuntimeError("old and new name are not the same file - not removing")
                    os.unlink(sabs)  # removes only the old name
                elif os.lstat(dst).st_size != size:
                    raise RuntimeError("new name has wrong size")
                set_op(db, op_id, "DONE")
                db.execute("UPDATE batches SET last_done_id=? WHERE n=?", (op_id, n))
                moved += 1
        except Exception as e:
            set_op(db, op_id, "FAILED", f"{type(e).__name__}: {e}")
            db.execute("UPDATE batches SET status='FAILED' WHERE n=?", (n,))
            event(db, "run", n, f"FAILED at op {op_id}: {e}")
            sys.exit(f"STOPPED at op {op_id} ({src}): {e}  - nothing removed for this op")
        if moved % 250 == 0 and moved:
            log(f"batch {n}: {moved} moved")
    left = db.execute("SELECT COUNT(*) FROM ops WHERE batch=? AND status NOT IN ('DONE','VERIFIED')", (n,)).fetchone()[0]
    db.execute("UPDATE batches SET status=?, finished_at=? WHERE n=?", ("DONE" if left == 0 else "RUNNING", now(), n))
    event(db, "run", n, f"finished: moved {moved}, remaining {left}")
    log(f"batch {n} finished: moved {moved}, remaining {left}")


def cmd_verify(a):
    db = connect()
    n = a.batch
    st = db.execute("SELECT status FROM batches WHERE n=?", (n,)).fetchone()[0]
    if st not in ("DONE", "VERIFIED"):
        sys.exit(f"batch {n} is {st}, run it first")
    problems = []
    for op_id, src, dst, size in db.execute("SELECT id, src, dst, size FROM ops WHERE batch=? ORDER BY id", (n,)).fetchall():
        if os.path.lexists(f"{BASE}/{src}"):
            problems.append(f"op {op_id}: old name still exists")
        try:
            if os.lstat(dst).st_size != size:
                problems.append(f"op {op_id}: size mismatch at new name")
        except FileNotFoundError:
            problems.append(f"op {op_id}: new name missing")
    cnt = size_sum = 0
    for root, dirs, files in os.walk(BASE):
        for fn in files:
            cnt += 1
            size_sum += os.lstat(os.path.join(root, fn)).st_size
    exp_cnt = int(db.execute("SELECT value FROM meta WHERE key='inventory_files'").fetchone()[0])
    exp_size = int(db.execute("SELECT value FROM meta WHERE key='inventory_bytes'").fetchone()[0])
    log(f"global: files {cnt} (expected {exp_cnt}), bytes {size_sum} (expected {exp_size})")
    if (cnt, size_sum) != (exp_cnt, exp_size):
        problems.append(f"global count/size mismatch: {cnt}/{size_sum} vs {exp_cnt}/{exp_size}")
    if problems:
        event(db, "verify", n, f"FAILED: {len(problems)} problems")
        for p in problems[:30]:
            log(p)
        sys.exit(f"batch {n} NOT verified")
    db.execute("BEGIN")
    db.execute("UPDATE ops SET status='VERIFIED', updated_at=? WHERE batch=? AND status='DONE'", (now(), n))
    db.execute("UPDATE batches SET status='VERIFIED', verified_at=? WHERE n=?", (now(), n))
    event(db, "verify", n, f"verified; global files {cnt}, bytes {size_sum}")
    db.execute("COMMIT")
    log(f"batch {n} VERIFIED")
    cmd_report(None)


def cmd_status(_):
    db = connect()
    for n, files, status, last in db.execute("SELECT n, files, status, last_done_id FROM batches ORDER BY n"):
        c = dict(db.execute("SELECT status, COUNT(*) FROM ops WHERE batch=? GROUP BY status", (n,)).fetchall())
        print(f"batch {n:02d}  files {files:5d}  {status:9s}  last_done_id={last}  ops={c}")


def cmd_report(_):
    db = connect()
    meta = dict(db.execute("SELECT key, value FROM meta"))
    tot = dict(db.execute("SELECT status, COUNT(*) FROM ops GROUP BY status").fetchall())
    L = ["# Media reorganization - report (from database)",
         f"Generated: {now()}  |  database: {DB}",
         f"Base: {meta['base']}  |  inventory: {meta['inventory_files']} files, {meta['inventory_bytes']} bytes",
         "",
         "Operation status: PLANNED -> VALIDATED (dry run) -> LINKING -> LINKED -> DONE -> VERIFIED  (INVALID/FAILED = stop)",
         "Move = hard link to new name, verify same file + size, remove old name. Nothing copied, deleted or overwritten.",
         "",
         f"## Totals: {tot}",
         "",
         "## Batches",
         "| # | ops id range | files | categories | batch status | op states | last done id | verified at |",
         "|---|---|---|---|---|---|---|---|"]
    for n, first, last, files, status, ld, va in db.execute(
            "SELECT n, first_id, last_id, files, status, last_done_id, verified_at FROM batches ORDER BY n").fetchall():
        cats = dict(db.execute("SELECT category, COUNT(*) FROM ops WHERE batch=? GROUP BY category", (n,)).fetchall())
        sts = dict(db.execute("SELECT status, COUNT(*) FROM ops WHERE batch=? GROUP BY status", (n,)).fetchall())
        L.append(f"| {n:02d} | {first}-{last} | {files} | {cats} | {status} | {sts} | {ld or '-'} | {va or '-'} |")
    errs = db.execute("SELECT id, status, src, error FROM ops WHERE status IN ('INVALID','FAILED') ORDER BY id LIMIT 100").fetchall()
    L += ["", "## Problems"] + (["- none"] if not errs else [f"- op {i} {s}: {src} - {e}" for i, s, src, e in errs])
    L += ["", "## Events"] + [f"- {ts} {c} batch={b}: {m}" for ts, c, b, m in
                              db.execute("SELECT ts, cmd, batch, msg FROM events ORDER BY id").fetchall()]
    with open(REPORT, "w", **FS) as f:
        f.write("\n".join(L) + "\n")
    log(f"report written: {REPORT}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["init", "dryrun", "run", "verify", "status", "report"])
    p.add_argument("--batch", type=int)
    a = p.parse_args()
    {"init": cmd_init, "dryrun": cmd_dryrun, "run": cmd_run, "verify": cmd_verify,
     "status": cmd_status, "report": cmd_report}[a.cmd](a)
