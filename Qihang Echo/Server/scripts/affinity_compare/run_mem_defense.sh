#!/usr/bin/env bash
# NUMA memory defense demo for your board topology:
# - node0: CPUs 0-3 + 16GB memory
# - node2: 512MB memory, NO CPUs, far distance (100)
#
# This script compares:
#   Remote mem (membind=2) vs Local mem (membind=0)
# while keeping CPU on node0 (0-3).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Some deployments use:
#   <root>/Server/tools
# while your dev-board layout uses:
#   <server_root>/tools
if [[ -d "$ROOT_DIR/tools" ]]; then
  TOOLS_DIR="$ROOT_DIR/tools"
elif [[ -d "$ROOT_DIR/Server/tools" ]]; then
  TOOLS_DIR="$ROOT_DIR/Server/tools"
else
  echo "[ERROR] Cannot find tools directory. Expected '$ROOT_DIR/tools' or '$ROOT_DIR/Server/tools'." >&2
  echo "        ROOT_DIR=$ROOT_DIR" >&2
  exit 2
fi
OUT_DIR_DEFAULT="$ROOT_DIR/reports/affinity_compare/mem_defense_$(date +%Y%m%d_%H%M%S)"

MEM_MB=256
LOOPS=30
WARMUP=2
OUT_DIR="$OUT_DIR_DEFAULT"
CPUSET="0-3"
DTYPE="float64"
PATTERN="scan"
TOUCH_PER_PAGE="16"

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  --mem-mb N        Array size in MB (default: 256; must fit node2 free)
  --dtype TYPE      uint8|uint64|float64 (default: float64)
  --pattern P       scan|random_page (default: scan)
  --touch-per-page N  For pattern=random_page (default: 16)
  --loops N         (default: 30)
  --warmup N        (default: 2)
  --cpuset SPEC     CPU set for the benchmark process (default: 0-3)
  --out-dir PATH    (default: $OUT_DIR_DEFAULT)

It will write:
  remote_node2.json  (CPU=0-3, membind=2)
  local_node0.json   (CPU=0-3, membind=0)
  mem_latency_box.png / mem_throughput.png / summary.md
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mem-mb) MEM_MB="$2"; shift 2;;
    --dtype) DTYPE="$2"; shift 2;;
    --pattern) PATTERN="$2"; shift 2;;
    --touch-per-page) TOUCH_PER_PAGE="$2"; shift 2;;
    --loops) LOOPS="$2"; shift 2;;
    --warmup) WARMUP="$2"; shift 2;;
    --cpuset) CPUSET="$2"; shift 2;;
    --out-dir) OUT_DIR="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

mkdir -p "$OUT_DIR"

REMOTE_JSON="$OUT_DIR/remote_node2.json"
LOCAL_JSON="$OUT_DIR/local_node0.json"

if ! command -v numactl >/dev/null 2>&1; then
  echo "[ERROR] numactl not found. Please install numactl." >&2
  exit 2
fi

TASKSET_PREFIX=()
if command -v taskset >/dev/null 2>&1; then
  TASKSET_PREFIX=(taskset -c "$CPUSET")
else
  echo "[WARN] taskset not found; running without explicit CPU pin." >&2
fi

echo "[1/3] remote memory case: cpu=0-3, membind=2 -> $REMOTE_JSON"
"${TASKSET_PREFIX[@]}" numactl --membind=2 \
  python3 "$TOOLS_DIR/numa_mem_bench.py" --mode baseline --mem-mb "$MEM_MB" --dtype "$DTYPE" --pattern "$PATTERN" --touch-per-page "$TOUCH_PER_PAGE" --loops "$LOOPS" --warmup "$WARMUP" --out "$REMOTE_JSON"

echo "[2/3] local memory case: cpu=0-3, membind=0 -> $LOCAL_JSON"
"${TASKSET_PREFIX[@]}" numactl --membind=0 \
  python3 "$TOOLS_DIR/numa_mem_bench.py" --mode defense --mem-mb "$MEM_MB" --dtype "$DTYPE" --pattern "$PATTERN" --touch-per-page "$TOUCH_PER_PAGE" --loops "$LOOPS" --warmup "$WARMUP" --out "$LOCAL_JSON"

echo "[3/3] generating figures"
python3 "$TOOLS_DIR/numa_mem_plot.py" --remote "$REMOTE_JSON" --local "$LOCAL_JSON" --out-dir "$OUT_DIR"

echo "[DONE] $OUT_DIR"
ls -lh "$OUT_DIR" | sed -n '1,200p'

