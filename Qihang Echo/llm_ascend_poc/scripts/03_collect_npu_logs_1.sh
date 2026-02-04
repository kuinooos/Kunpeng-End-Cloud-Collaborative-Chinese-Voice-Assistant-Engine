#!/usr/bin/env bash
set -euo pipefail

# Collect Ascend/NPU diagnostics into a timestamped folder.
# Usage:
#   sudo bash scripts/03_collect_npu_logs.sh

TS="$(date +%Y%m%d_%H%M%S 2>/dev/null || echo unknown_time)"
OUT_DIR="/tmp/ascend_diag_${TS}"
mkdir -p "$OUT_DIR"

log() { echo "[COLLECT] $*"; }
run() {
  local name="$1"; shift
  log "$name"
  {
    echo "# CMD: $*"
    "$@"
  } >"$OUT_DIR/${name}.txt" 2>&1 || true
}

# Basic versions
run "npu_smi_info" npu-smi info
run "npu_smi_health" npu-smi info -i 0 -c 0 -t health
run "npu_smi_product" npu-smi info -i 0 -c 0 -t product
run "npu_smi_work_mode" npu-smi info -i 0 -c 0 -t work-mode
run "npu_smi_pcie_err" npu-smi info -i 0 -c 0 -t pcie-err
run "npu_smi_help" npu-smi --help
run "npu_smi_set_help" npu-smi set -h
run "npu_smi_clear_help" npu-smi clear -h

# Version files
run "driver_version" bash -c 'echo "## /var/davinci/driver/version.info"; cat /var/davinci/driver/version.info 2>/dev/null || true; echo; echo "## /usr/local/Ascend/ascend-toolkit/latest/runtime/version.info"; cat /usr/local/Ascend/ascend-toolkit/latest/runtime/version.info 2>/dev/null || true'

# Device nodes & permissions
run "dev_nodes" bash -c 'ls -l /dev/davinci* /dev/ascend_manager /dev/hisi_bbox* 2>/dev/null || true; echo; stat /dev/davinci0 2>/dev/null || true'

# Kernel modules
run "lsmod_ascend" bash -c 'lsmod | egrep -i "ascend|npu|davinci|drv_davinci" || true'

# Services (best-effort)
run "systemctl_grep" bash -c 'systemctl list-units --type=service --no-pager | egrep -i "ascend|davinci|npu|dcmi|mind|msgproc|ts_agent" || true'
run "ps_grep" bash -c 'ps -ef | egrep -i "ascend|davinci|dcmi|mind|msgproc|ts_agent|dvpp" || true'

# Logs
run "dmesg_tail" bash -c 'dmesg | tail -n 300'
run "dmesg_grep_ascend" bash -c 'dmesg | egrep -i "ascend|bbox|davinci|icm|mailbox|lpm" | tail -n 400'

# Ascend logs on common paths
run "var_davinci_log_list" bash -c 'ls -lah /var/davinci 2>/dev/null || true; echo; find /var/davinci -maxdepth 3 -type f -name "*.log" -o -name "message*" -o -name "*.txt" 2>/dev/null | head -n 200 || true'
run "usr_local_ascend_list" bash -c 'ls -lah /usr/local/Ascend 2>/dev/null || true; echo; find /usr/local/Ascend -maxdepth 4 -type f -name "*.log" -o -name "*.txt" -o -name "*.info" 2>/dev/null | head -n 200 || true'

# Pack
TAR_PATH="/tmp/ascend_diag_${TS}.tar.gz"
log "pack -> $TAR_PATH"
tar -czf "$TAR_PATH" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")" >/dev/null 2>&1 || true

echo "[OK] collected to: $OUT_DIR"
echo "[OK] packed to:    $TAR_PATH"
