#!/usr/bin/env bash
set -euo pipefail
source ${REMOTE_ENVIRONMENT_SCRIPT}
TASK_ROOT="${VENTUS_FLOW_ROOT:-${REMOTE_FLOW_ROOT}}"
export LD_LIBRARY_PATH="$TASK_ROOT/deps/install/lib:$TASK_ROOT/deps/install/systemc/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
CASE_DIR="${VENTUS_CYCLESIM_CASE_DIR:-$TASK_ROOT/evidence/cyclesim-vecadd}"
mkdir "$CASE_DIR"
cp "$TASK_ROOT/evidence/rtl-vecadd/vecadd.metadata" "$CASE_DIR/vecadd.metadata"
cp "$TASK_ROOT/evidence/rtl-vecadd/vecadd.data" "$CASE_DIR/vecadd.data"
cd "$CASE_DIR"
VENTUS_VERIFY_VECADD=1 /usr/bin/time -f '%e' -o wall_seconds.txt timeout 180 \
  "$TASK_ROOT/cyclesim-build/main" \
  --kernel name=vecadd,metafile=vecadd.metadata,datafile=vecadd.data \
  --sim-time-max 2000000 > stdout.log 2> stderr.log
grep 'VERIFIED_VECADD_WORDS=1024' stdout.log
tail -3 stdout.log
