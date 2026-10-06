#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="${VENTUS_FLOW_ROOT:-${REMOTE_FLOW_ROOT}}"
# A fresh root is required; existing evidence is never replaced.
mkdir "$TASK_ROOT"
mkdir "$TASK_ROOT/evidence" "$TASK_ROOT/deps" "$TASK_ROOT/src"
git clone https://github.com/THU-DSP-LAB/ventus-gpgpu-cpp-simulator.git "$TASK_ROOT/src/cyclesim"
git -C "$TASK_ROOT/src/cyclesim" checkout 335ba24d2c7763c87e8c9bfe889c9074763a32f7
git -C "$TASK_ROOT/src/cyclesim" submodule update --init --recursive
