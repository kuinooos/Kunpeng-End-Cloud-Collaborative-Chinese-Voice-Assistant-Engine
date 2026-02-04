#!/usr/bin/env bash
set -euo pipefail

echo "==[1/8] basic system=="
uname -a || true
cat /etc/os-release 2>/dev/null || true

echo "\n==[2/8] cpu/mem=="
lscpu 2>/dev/null | sed -n '1,40p' || true
free -h || true

echo "\n==[3/8] ascend runtime / drivers=="
if command -v npu-smi >/dev/null 2>&1; then
	if npu-smi info; then
		echo "[OK] npu-smi info succeeded"
	else
		echo "[WARN] npu-smi exists but failed (driver/runtime not ready?)"
	fi
else
	echo "[WARN] npu-smi not found"
fi

echo "\n==[4/8] toolkit commands=="
if command -v atc >/dev/null 2>&1; then
	# 有些版本不支持 --version，用 --help 取代
	if atc --version 2>/dev/null; then
		true
	else
		echo "[INFO] atc --version not supported; showing first lines of --help"
		atc --help 2>/dev/null | sed -n '1,20p' || true
	fi
	echo "[OK] atc found: $(command -v atc)"
else
	echo "[WARN] atc not found"
fi
command -v msnpureport >/dev/null 2>&1 && msnpureport --version || true

echo "\n==[5/8] environment hints=="
echo "ASCEND_HOME_PATH=${ASCEND_HOME_PATH:-}"
echo "ASCEND_TOOLKIT_HOME=${ASCEND_TOOLKIT_HOME:-}"
echo "LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}" | cut -c1-200; echo

echo "\n==[6/8] python=="
python3 -V || true
python3 -c "import sys; print('exe:', sys.executable)" || true

echo "\n==[7/8] python packages (short)=="
python3 -c "import pkgutil; print('acl in pkgutil:', any(m.name=='acl' for m in pkgutil.iter_modules()))" || true

echo "\n==[8/8] done=="
echo "[OK] sysinfo collected"
