# media-reorg

Scripts that reorganized `/mnt/caglar/Media` on the NAS (mounted on 1.190 over NFS) into
`{Pictures,Videos,Audios,Documents}/YYYY/YYYY-MM/YYYYMMDD_HHMMSS_<name>[-N].<ext>`, with leftovers in `Archive/<original path>`.

Safety model everywhere: nothing is deleted or overwritten. A move is `os.link` to the new name
(which fails if the target exists), then a check that both names point to the same file with the
right size, then `unlink` of the old name. Name collisions get a `-N` suffix.

Date priority: DateTimeOriginal → CreateDate (+66 years if before 1970, a phone epoch bug) → a date in the file name → FileModifyDate.

| Step | Script | What it does |
|---|---|---|
| 1 | `dryrun.sh` | Inventory snapshot plus exiftool `-testname` dry run and `dates.csv` (date tags per file). Nothing is moved. |
| 2 | `plan_step1.py` … `plan_step4.py` | Build `dryrun4-plan.tsv` (category, source, target, date source, flags) from the exiftool output. Step 4 adds Documents and needs `dates-docs.csv`, the same exiftool `-csv` export for document extensions. |
| 3 | `reorgdb.py` | SQLite-driven runner: `init`, `dryrun`, `run --batch N`, `verify --batch N`, `status`, `report`. Resumable; records each move's state in `reorg.db`. |
| 4 | `run-all.sh` | Runs batches 2–13 in order (run, then verify) and stops on the first failure. |
| 5 | `trdb.py` | Turkish letters in file names → ASCII (`ç→c`, `ğ→g`, `ı→i`, …): `dryrun`, `run`, `verify`, `dirs`, `status`. |
| 6 | `casefix.py` | Folders longer than 5 chars → first letter upper, rest lower (skips `DCIM*` and dot folders). Dry run by default; `--apply` renames. |

Data files (inventory, plans, databases) are not in the repo: they list private file names.
