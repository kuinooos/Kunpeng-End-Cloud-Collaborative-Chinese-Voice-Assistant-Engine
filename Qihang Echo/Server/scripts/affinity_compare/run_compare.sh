#!/usr/bin/env bash
# Run baseline vs affinity-pinned benchmark and generate figures.
# Designed for Linux/openEuler (Kunpeng/NUMA).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Some deployments use <root>/Server, others use the server dir as root.
if [[ -d "$ROOT_DIR/Server/tools" ]]; then
  SERVER_DIR="$ROOT_DIR/Server"
  TOOLS_DIR="$ROOT_DIR/Server/tools"
else
  SERVER_DIR="$ROOT_DIR"
  TOOLS_DIR="$ROOT_DIR/tools"
fi
OUT_DIR_DEFAULT="$ROOT_DIR/reports/affinity_compare/$(date +%Y%m%d_%H%M%S)"

ENGINE="onnx"
LOOPS="30"
WARMUP="2"
AUDIO_SECONDS="5"
SAMPLER_INTERVAL="0.2"

ONNX_PATH=""
VOCAB_PATH=""

# Affinity settings
PIN_CPUSET=""
PIN_NODE=""

# Noise settings (optional)
NOISE_CPUSET=""
NOISE_NODE=""
NOISE_CPU_WORKERS="0"
NOISE_MEM_MB="0"
NOISE_TOUCH="0"

usage() {
  cat <<EOF
Usage: $0 [options]

Benchmark:
  --engine onnx|torch           (default: onnx)
  --loops N                     (default: 30)
  --warmup N                    (default: 2)
  --audio-seconds S             (default: 5)
  --sampler-interval S          (default: 0.2)
  --out-dir PATH                (default: $OUT_DIR_DEFAULT)
  --onnx-path PATH              Override ASR ONNX model path
  --vocab-path PATH             Override tokens.json path

Affinity pinned run:
  --pin-cpuset "0-31"            CPU set for affinity run
  --pin-node N                  NUMA node id (optional, used for numactl membind/cpunodebind)

Noise (to demonstrate isolation & memory defense):
  --noise-cpuset "32-63"         CPU set for noise process (recommended different from pin-cpuset)
  --noise-node N                NUMA node id for noise (optional)
  --noise-cpu-workers N          Spawn N CPU spinning workers (default: 0)
  --noise-mem-mb N               Allocate N MB in noise process (default: 0)
  --noise-touch                 Continuously touch pages (default: off)

Notes:
- baseline run is executed without taskset/numactl.
- affinity run is executed with taskset (cpuset) and optional numactl (node bind).
EOF
}

OUT_DIR="$OUT_DIR_DEFAULT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --engine) ENGINE="$2"; shift 2;;
    --loops) LOOPS="$2"; shift 2;;
    --warmup) WARMUP="$2"; shift 2;;
    --audio-seconds) AUDIO_SECONDS="$2"; shift 2;;
    --sampler-interval) SAMPLER_INTERVAL="$2"; shift 2;;
    --out-dir) OUT_DIR="$2"; shift 2;;

    --onnx-path) ONNX_PATH="$2"; shift 2;;
    --vocab-path) VOCAB_PATH="$2"; shift 2;;

    --pin-cpuset) PIN_CPUSET="$2"; shift 2;;
    --pin-node) PIN_NODE="$2"; shift 2;;

    --noise-cpuset) NOISE_CPUSET="$2"; shift 2;;
    --noise-node) NOISE_NODE="$2"; shift 2;;
    --noise-cpu-workers) NOISE_CPU_WORKERS="$2"; shift 2;;
    --noise-mem-mb) NOISE_MEM_MB="$2"; shift 2;;
    --noise-touch) NOISE_TOUCH="1"; shift 1;;

    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

mkdir -p "$OUT_DIR"

BASE_JSON="$OUT_DIR/baseline.json"
AFF_JSON="$OUT_DIR/affinity.json"

# Optional noise
NOISE_PID=""
if [[ "$NOISE_CPU_WORKERS" != "0" || "$NOISE_MEM_MB" != "0" ]]; then
  echo "[1/5] starting noise worker..."
  NOISE_ARGS=("$TOOLS_DIR/noise_worker.py" --duration 999999 --cpu-workers "$NOISE_CPU_WORKERS" --mem-mb "$NOISE_MEM_MB")
  if [[ "$NOISE_TOUCH" == "1" ]]; then
    NOISE_ARGS+=(--touch)
  fi

  if command -v numactl >/dev/null 2>&1 && [[ -n "$NOISE_NODE" || -n "$NOISE_CPUSET" ]]; then
    if [[ -n "$NOISE_NODE" && -n "$NOISE_CPUSET" ]]; then
      numactl --cpunodebind="$NOISE_NODE" --membind="$NOISE_NODE" --physcpubind="$NOISE_CPUSET" python3 "${NOISE_ARGS[@]}" &
    elif [[ -n "$NOISE_CPUSET" ]]; then
      numactl --physcpubind="$NOISE_CPUSET" python3 "${NOISE_ARGS[@]}" &
    else
      numactl --cpunodebind="$NOISE_NODE" --membind="$NOISE_NODE" python3 "${NOISE_ARGS[@]}" &
    fi
  elif command -v taskset >/dev/null 2>&1 && [[ -n "$NOISE_CPUSET" ]]; then
    taskset -c "$NOISE_CPUSET" python3 "${NOISE_ARGS[@]}" &
  else
    python3 "${NOISE_ARGS[@]}" &
  fi
  NOISE_PID=$!
fi

cleanup() {
  if [[ -n "${NOISE_PID}" ]]; then
    kill "${NOISE_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[2/5] running baseline benchmark -> $BASE_JSON"
python3 "$TOOLS_DIR/affinity_benchmark.py" \
  --mode baseline \
  --engine "$ENGINE" \
  ${ONNX_PATH:+--onnx-path "$ONNX_PATH"} \
  ${VOCAB_PATH:+--vocab-path "$VOCAB_PATH"} \
  --loops "$LOOPS" \
  --warmup "$WARMUP" \
  --audio-seconds "$AUDIO_SECONDS" \
  --sampler-interval "$SAMPLER_INTERVAL" \
  --out "$BASE_JSON"

echo "[3/5] running affinity benchmark -> $AFF_JSON"

BENCH_CMD=(python3 "$TOOLS_DIR/affinity_benchmark.py" \
  --mode affinity --engine "$ENGINE" \
  ${ONNX_PATH:+--onnx-path "$ONNX_PATH"} \
  ${VOCAB_PATH:+--vocab-path "$VOCAB_PATH"} \
  --loops "$LOOPS" --warmup "$WARMUP" \
  --audio-seconds "$AUDIO_SECONDS" --sampler-interval "$SAMPLER_INTERVAL" \
  --out "$AFF_JSON")

if command -v taskset >/dev/null 2>&1 && [[ -n "$PIN_CPUSET" ]]; then
  if command -v numactl >/dev/null 2>&1 && [[ -n "$PIN_NODE" ]]; then
    # On some embedded boards numactl --physcpubind is unsupported; use taskset for CPU, numactl only for node binding.
    numactl --cpunodebind="$PIN_NODE" --membind="$PIN_NODE" taskset -c "$PIN_CPUSET" "${BENCH_CMD[@]}"
  else
    taskset -c "$PIN_CPUSET" "${BENCH_CMD[@]}"
  fi
elif command -v numactl >/dev/null 2>&1 && [[ -n "$PIN_NODE" ]]; then
  numactl --cpunodebind="$PIN_NODE" --membind="$PIN_NODE" "${BENCH_CMD[@]}"
else
  echo "[WARN] pin-cpuset/pin-node not provided; running without pin (will be less persuasive)." >&2
  "${BENCH_CMD[@]}"
fi

echo "[4/5] generating figures"
python3 "$TOOLS_DIR/affinity_plot.py" --baseline "$BASE_JSON" --affinity "$AFF_JSON" --out-dir "$OUT_DIR"

echo "[5/5] done: $OUT_DIR"
ls -lh "$OUT_DIR" | sed -n '1,200p'

