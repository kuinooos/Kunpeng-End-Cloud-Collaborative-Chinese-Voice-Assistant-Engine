#!/usr/bin/env bash
set -euo pipefail

# Best-effort runner for ACL smoke test.
# Goal: make "import acl" work without requiring a login shell.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/01_acl_smoke_test.py"

_echo() { echo "[RUN] $*"; }

source_one() {
  local p="$1"
  if [ -f "$p" ]; then
    _echo "source $p"
    # Ascend 的 setenv.bash 有时会直接引用 LD_LIBRARY_PATH 等变量；
    # 如果当前 shell 启用了 nounset(set -u)，且变量未定义，会直接报错。
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH-}"
    export PYTHONPATH="${PYTHONPATH-}"
    export PATH="${PATH-}"
    # shellcheck disable=SC1090
    set +u
    source "$p"
    set -u
    return 0
  fi
  return 1
}

# Prefer explicit toolkit env, then system profile.
# Note: some systems only ship set_env.sh or setenv.bash under different subdirs.
CANDIDATES=(
  "/usr/local/Ascend/ascend-toolkit/latest/set_env.sh"
  "/usr/local/Ascend/ascend-toolkit/latest/setenv.bash"
  "/usr/local/Ascend/ascend-toolkit/latest/bin/setenv.bash"
  "/usr/local/Ascend/ascend-toolkit/latest/runtime/bin/setenv.bash"
  "/usr/local/Ascend/ascend-toolkit/latest/runtime/set_env.sh"
  "/etc/profile.d/ascend.sh"
)

SOURCED=0
for p in "${CANDIDATES[@]}"; do
  if source_one "$p"; then
    SOURCED=1
    break
  fi
done

if [ "$SOURCED" -eq 0 ]; then
  _echo "WARN: no known Ascend env script found. Proceeding without source."
  _echo "You can locate it by running: sudo find /usr/local/Ascend -maxdepth 4 -type f -name 'set_env.sh' -o -name 'setenv.bash'"
else
  # 有些 setenv.bash 不会设置这两个变量，但我们日志/脚本会用到
  if [ -z "${ASCEND_HOME_PATH-}" ] && [ -d "/usr/local/Ascend/ascend-toolkit/latest" ]; then
    export ASCEND_HOME_PATH="/usr/local/Ascend/ascend-toolkit/latest"
  fi
  if [ -z "${ASCEND_TOOLKIT_HOME-}" ] && [ -d "/usr/local/Ascend/ascend-toolkit/latest" ]; then
    export ASCEND_TOOLKIT_HOME="/usr/local/Ascend/ascend-toolkit/latest"
  fi
fi

_echo "python3 $SCRIPT"
python3 "$SCRIPT"
