#!/usr/bin/env python3
"""Folder names longer than 5 chars -> first letter upper, rest lower (111APPLE -> 111Apple,
'WhatsApp Voice Notes' -> 'Whatsapp voice notes'). Skips names starting with DCIM and hidden (dot) folders.
Renames are logged to ~/media-reorg/tr.db (table caseops). Refuses if a target already exists.
Checks that the global file count and size are unchanged.
"""
import os, sqlite3, sys

BASE = "/mnt/caglar/Media"
DB = os.path.expanduser("~/media-reorg/tr.db")


def new_name(d):
    i = next((k for k, ch in enumerate(d) if ch.isalpha()), None)
    if i is None:
        return d
    return d[:i] + d[i].upper() + d[i + 1:].lower()


def totals():
    c = s = 0
    for r, _, fs in os.walk(BASE):
        for f in fs:
            c += 1
            s += os.lstat(os.path.join(r, f)).st_size
    return c, s


def main(apply):
    plan = []
    for root, ds, _ in os.walk(BASE):
        for d in ds:
            if len(d) > 5 and not d.startswith(".") and not d.upper().startswith("DCIM"):
                n = new_name(d)
                if n != d:
                    plan.append((os.path.join(root, d), os.path.join(root, n)))
    plan.sort(key=lambda p: -p[0].count("/"))  # deepest first
    for s, d in plan:
        print(s[len(BASE) + 1:], "->", os.path.basename(d))
    if not apply:
        print(f"DRY RUN: {len(plan)} folders (use --apply to rename)")
        return
    c = sqlite3.connect(DB, isolation_level=None)
    c.execute("PRAGMA synchronous=FULL")
    c.execute("CREATE TABLE IF NOT EXISTS caseops(src TEXT PRIMARY KEY, dst TEXT, status TEXT, updated_at TEXT)")
    before = totals()
    for s, d in plan:
        c.execute("INSERT OR IGNORE INTO caseops VALUES(?,?,'PLANNED',datetime('now'))", (s, d))
    for s, d in plan:
        if os.path.lexists(d):
            sys.exit(f"target exists, refusing: {d}")
        os.rename(s, d)
        c.execute("UPDATE caseops SET status='DONE',updated_at=datetime('now') WHERE src=?", (s,))
    after = totals()
    print("renamed", len(plan), "before", before, "after", after, "OK" if before == after else "MISMATCH")
    if before != after:
        sys.exit(1)


if __name__ == "__main__":
    main("--apply" in sys.argv)
