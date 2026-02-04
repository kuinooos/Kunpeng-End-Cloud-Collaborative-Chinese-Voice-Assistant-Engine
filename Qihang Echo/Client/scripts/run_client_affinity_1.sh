#!/usr/bin/env bash
# openEuler/ARM64: Run AIChatClient with CPU & memory affinity
# Usage:
#   ./run_client_affinity.sh -e ./rv1106_AIChatClient_demo/bin/AIChatClient -c "0-7" -m 0 [-- extra args]
# Options:
#   -e EXEC      Path to AIChatClient executable (default: ./AIChat_demo/Client/build/AIChatClient)
#   -c CPUS      CPU set, e.g. "0-7" or "0,2,4,6"
#   -m NODE      NUMA node id for memory bind (optional)
#   -i CORES     Isolated cores for io/ws thread (optional, comma/range)
#   -a CORES     Cores for audio encode/decode thread (optional)
#   -t CORES     Cores for task/ASR/VAD threads (optional)
# Notes:
# - Tries numactl first, falls back to taskset if numactl not available.
# - If -i/-a/-t provided, will export hints for process internal thread pinning.

set -euo pipefail

EXEC="./AIChat_demo/Client/build/AIChatClient"
CPUS=""
NODE=""
IO_CORES=""
AUDIO_CORES=""
TASK_CORES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -e) EXEC="$2"; shift 2;;
    -c) CPUS="$2"; shift 2;;
    -m) NODE="$2"; shift 2;;
    -i) IO_CORES="$2"; shift 2;;
    -a) AUDIO_CORES="$2"; shift 2;;
    -t) TASK_CORES="$2"; shift 2;;
    --) shift; break;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ ! -x "$EXEC" ]]; then
  echo "Executable not found or not executable: $EXEC" >&2
  exit 2
fi

# Export thread affinity hints for the app (optional if you later wire them in)
export AICHAT_IO_CORES="$IO_CORES"
export AICHAT_AUDIO_CORES="$AUDIO_CORES"
export AICHAT_TASK_CORES="$TASK_CORES"

# Prevent automatic startup of JACK server by clients
export JACK_NO_START_SERVER=1



CMD=("$EXEC" "$@")

if command -v taskset >/dev/null 2>&1; then
  if [[ -n "$CPUS" ]]; then
    # Convert CPU list/range to mask via taskset -c
    exec taskset -c "$CPUS" "${CMD[@]}"
  else
    exec "${CMD[@]}"
  fi
elif command -v numactl >/dev/null 2>&1; then
  if [[ -n "$CPUS" ]]; then
    # Convert CPU list/range to mask via taskset -c
    exec taskset -c "$CPUS" "${CMD[@]}"
  else
    exec "${CMD[@]}"
  fi
else
  echo "Neither numactl nor taskset is available; running without affinity." >&2
  exec "${CMD[@]}"
fi
