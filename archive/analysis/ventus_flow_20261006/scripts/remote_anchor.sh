#!/usr/bin/env bash
set -euo pipefail
source ${REMOTE_ENVIRONMENT_SCRIPT}
TASK_ROOT="${VENTUS_FLOW_ROOT:-${REMOTE_FLOW_ROOT}}"
UPSTREAM=${REMOTE_PROJECT_ROOT}
CASE_DIR="$TASK_ROOT/evidence/rtl-vecadd"
mkdir "$CASE_DIR"
cp "$UPSTREAM/sim-verilator/testcase/vecadd/vecadd_32b8w8t.metadata" "$CASE_DIR/vecadd.metadata"
cp "$UPSTREAM/sim-verilator/testcase/vecadd/vecadd_32b8w8t.data" "$CASE_DIR/vecadd.data"
cd "$CASE_DIR"
/usr/bin/time -f '%e' -o wall_seconds.txt timeout 600 \
  "$UPSTREAM/sim-verilator/build/driver_example/debug/sim-VentusRTL" \
  --kernel name=vecadd,metafile=vecadd.metadata,datafile=vecadd.data \
  --sim-time-max 2000000 --snapshot 20000000 --dump-mem 0x90002000,0x90002FFC \
  > stdout.log 2> stderr.log
python3 "$TASK_ROOT/inspect_anchor.py" "$CASE_DIR" "$UPSTREAM"
