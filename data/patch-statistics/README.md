# Commands to regenerate numbers

# 1) Files-changed statistics + plot
./venv/bin/python statistics.py patch_diffs --pattern '*.diff' --save statistics_plot.png

# 2) Print sanitizer crash_output for one diff (asan/msan/tsan/ubsan by default)
./venv/bin/python asan_stat.py patch_diffs/42486246_7f027e158b.diff

# 2b) ASAN-only
./venv/bin/python asan_stat.py patch_diffs/42486246_7f027e158b.diff --sanitizers asan

# 3) Filename + function + stack-index statistics over all diffs
./venv/bin/python asan_filename_stats.py \
  --diff-dir patch_diffs \
  --pattern '*.diff' \
  --show-examples 10 \
  --max-stack-index-report 10

# 3b) Include parse-failure reasons and missing-report list
./venv/bin/python asan_filename_stats.py \
  --diff-dir patch_diffs \
  --pattern '*.diff' \
  --show-examples 0 \
  --print-parse-failures \
  --print-missing-sanitizer > sanitizer_stats_full.txt

# Help for each script
./venv/bin/python statistics.py -h
./venv/bin/python asan_stat.py -h
./venv/bin/python asan_filename_stats.py -h
