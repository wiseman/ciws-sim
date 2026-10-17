#!/bin/bash
# Before/after soaks: alternate the saved pre-dive build and the current one, 120 s each, at waves
# 3 and 10, three pairs each. Writes soak-ab.log here.
cd "$(dirname "$0")/../.."
for wave in 3 10; do
  for i in 1 2 3; do
    for page in docs/dronedive/index-before.html index.html; do
      uv run tools/soak.py 120 $wave --page $page 2>&1 | grep -E "SUMMARY|ERROR|average"
    done
  done
done | tee docs/dronedive/soak-ab.log
