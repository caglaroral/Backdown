#!/bin/sh
# DRY RUN ONLY: uses -testname (no files are renamed/moved). Outputs go to ~/media-reorg
set -u
M=/mnt/caglar/Media
O=$HOME/media-reorg
cd "$M" || exit 1
date > "$O/started.txt"

# 1) Inventory snapshot: path <TAB> size <TAB> mtime
find . -type f -printf "%P\t%s\t%TY-%Tm-%Td %TH:%TM:%TS\n" | sort > "$O/inventory-before.txt"
{ echo "files: $(wc -l < "$O/inventory-before.txt")"; awk -F"\t" "{s+=\$2} END {printf \"bytes: %d (%.1f GB)\n\", s, s/1e9}" "$O/inventory-before.txt"; } > "$O/inventory-summary.txt"

D="%Y/%Y-%m/%Y%m%d_%H%M%S"
# 2) Pictures
exiftool -r -d "$D" -ext jpg -ext jpeg -ext png -ext webp -ext heic -ext bmp -ext gif \
  "-testname<$M/Pictures/\${FileModifyDate}_%f%-c.%e" \
  "-testname<$M/Pictures/\${CreateDate}_%f%-c.%e" \
  "-testname<$M/Pictures/\${DateTimeOriginal}_%f%-c.%e" . > "$O/dryrun-pictures.log" 2>&1
# 3) Videos (QuickTime dates are UTC -> local time)
exiftool -r -api QuickTimeUTC -d "$D" -ext mov -ext mp4 -ext mpg -ext 3gp -ext ts \
  "-testname<$M/Videos/\${FileModifyDate}_%f%-c.%e" \
  "-testname<$M/Videos/\${CreateDate}_%f%-c.%e" \
  "-testname<$M/Videos/\${DateTimeOriginal}_%f%-c.%e" . > "$O/dryrun-videos.log" 2>&1
# 4) Audios
exiftool -r -api QuickTimeUTC -d "$D" -ext opus -ext mp3 -ext m4a -ext aac \
  "-testname<$M/Audios/\${FileModifyDate}_%f%-c.%e" \
  "-testname<$M/Audios/\${CreateDate}_%f%-c.%e" . > "$O/dryrun-audios.log" 2>&1
# 5) Date sources per file (for the report)
exiftool -r -api QuickTimeUTC -csv -DateTimeOriginal -CreateDate -FileModifyDate \
  -ext jpg -ext jpeg -ext png -ext webp -ext heic -ext bmp -ext gif \
  -ext mov -ext mp4 -ext mpg -ext 3gp -ext ts -ext opus -ext mp3 -ext m4a -ext aac . > "$O/dates.csv" 2> "$O/dates.err"
date > "$O/finished.txt"
echo DRY_DONE
