#!/usr/bin/env bash
set -euo pipefail

echo "==[1/8] npu-smi=="
if command -v npu-smi >/dev/null 2>&1; then
  npu-smi info || true
  echo "\n-- npu-smi help (first lines) --"
  (npu-smi --help 2>/dev/null | sed -n '1,40p') || true
  echo "\n-- npu-smi extra tables (best-effort) --"
  # 注意：npu-smi 23.x 的 info -t 需要 card id/chip id
  (npu-smi info proc -i 0 2>/dev/null) || true
  (npu-smi info -i 0 -c 0 -t health 2>/dev/null) || true
  (npu-smi info -i 0 -c 0 -t err-count 2>/dev/null) || true
  (npu-smi info -i 0 -c 0 -t pcie-err 2>/dev/null) || true
  (npu-smi info -i 0 -c 0 -t work-mode 2>/dev/null) || true
  (npu-smi info -i 0 -c 0 -t product 2>/dev/null) || true
else
  echo "[WARN] npu-smi not found"
fi

echo "\n==[2/8] device nodes=="
ls -l /dev/davinci* 2>/dev/null || echo "[WARN] /dev/davinci* not found"
ls -l /dev/ascend*  2>/dev/null || echo "[WARN] /dev/ascend* not found"
ls -l /dev/hisi*    2>/dev/null || true

echo "\n==[3/8] kernel modules (grep ascend/npu/davinci)=="
lsmod 2>/dev/null | egrep -i 'ascend|npu|davinci|hisi' || echo "[WARN] no matching modules found"

echo "\n==[4/8] driver/toolkit directories=="
ls -ld /usr/local/Ascend /usr/local/Ascend/driver /usr/local/Ascend/ascend-toolkit 2>/dev/null || true

echo "\n==[5/8] driver version files (best-effort)=="
for p in \
  /usr/local/Ascend/driver/version.info \
  /usr/local/Ascend/driver/driver_version.info \
  /usr/local/Ascend/driver/ascend_driver_version.info \
  /usr/local/Ascend/ascend-toolkit/latest/version.info \
  /usr/local/Ascend/ascend-toolkit/latest/runtime/version.info
do
  if [ -f "$p" ]; then
    echo "-- $p"
    sed -n '1,120p' "$p" || true
  fi
done

echo "\n-- search more version/info under /usr/local/Ascend/driver and /var/davinci/driver --"
find /usr/local/Ascend/driver /var/davinci/driver -maxdepth 3 -type f \( -name '*version*' -o -name '*.info' \) 2>/dev/null | head -n 50 || true

if [ -f /var/davinci/driver/version.info ]; then
  echo "\n-- /var/davinci/driver/version.info --"
  cat /var/davinci/driver/version.info || true
fi

echo "\n==[6.5/8] key processes (best-effort)=="
ps -ef | egrep -i 'ascend|davinci|dcmi|msgproc|ts_agent|npu|dvpp' | head -n 80 || true

echo "\n==[6/8] groups/permissions=="
id || true
if [ -e /dev/davinci0 ]; then
  stat /dev/davinci0 || true
fi

echo "\n==[7/8] dmesg tail (requires permission)=="
(dmesg | tail -n 120) 2>/dev/null || echo "[WARN] dmesg not accessible (try sudo)"

echo "\n==[8/8] done=="
echo "[OK] runtime check finished"
