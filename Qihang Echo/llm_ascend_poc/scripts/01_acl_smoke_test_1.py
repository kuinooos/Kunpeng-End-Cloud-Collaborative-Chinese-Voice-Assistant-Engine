#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ACL Python 冒烟测试：验证 CANN/ACL Python 绑定是否可用。

运行：
  python3 scripts/01_acl_smoke_test.py

成功标准：
- 能 import acl
- 能 acl.init / acl.finalize

注意：不同版本 ACL 的 API/返回值可能略有差异；脚本尽量宽容。
"""

from __future__ import annotations

import os
import sys
import faulthandler
import subprocess

try:
    import signal
except Exception:  # pragma: no cover
    signal = None
import traceback


def main() -> int:
    # 可选：当你怀疑 Python 侧死锁/卡死时再开启。
    # 用法：ACL_SMOKE_FAULTHANDLER=1 python3 scripts/01_acl_smoke_test.py
    if os.getenv("ACL_SMOKE_FAULTHANDLER") == "1":
        try:
            faulthandler.enable(all_threads=True)
            faulthandler.dump_traceback_later(30, repeat=True)
        except Exception:
            pass

    def _run_deep_probe_subprocess(timeout_s: int = 10) -> int:
        """在子进程里跑 set_device/create_context，主进程用超时保护。

        说明：ACL 的部分调用可能在底层驱动/固件异常时卡住且不响应信号，
        这时在同一进程里用 SIGALRM 也无法可靠中断；子进程超时可强制结束。
        """

        code = r"""
import os
import sys

import acl  # type: ignore

def p(*a):
    print(*a, flush=True)

p('[CHILD] Python:', sys.version)
p('[CHILD] ASCEND_HOME_PATH=', os.getenv('ASCEND_HOME_PATH'))
p('[CHILD] ASCEND_TOOLKIT_HOME=', os.getenv('ASCEND_TOOLKIT_HOME'))

ret = acl.init()
p('[CHILD] acl.init() ->', ret)

if hasattr(acl, 'rt') and hasattr(acl.rt, 'set_device'):
    try:
        r = acl.rt.set_device(0)
        p('[CHILD] acl.rt.set_device(0) ->', r)
    except Exception as e:
        p('[CHILD][EXC] set_device:', repr(e))

if hasattr(acl, 'rt') and hasattr(acl.rt, 'create_context'):
    try:
        ctx = acl.rt.create_context(0)
        p('[CHILD] acl.rt.create_context(0) ->', ctx)
        if hasattr(acl.rt, 'destroy_context'):
            try:
                dr = acl.rt.destroy_context(ctx if not isinstance(ctx, tuple) else ctx[1])
                p('[CHILD] acl.rt.destroy_context(ctx) ->', dr)
            except Exception as e:
                p('[CHILD][EXC] destroy_context:', repr(e))
    except Exception as e:
        p('[CHILD][EXC] create_context:', repr(e))

try:
    r2 = acl.finalize()
    p('[CHILD] acl.finalize() ->', r2)
except Exception as e:
    p('[CHILD][EXC] finalize:', repr(e))
"""

        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            print(f"[FAIL] deep probe subprocess timed out after {timeout_s}s (driver/runtime likely stuck)")
            return 11

        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print("[CHILD][STDERR]" + "\n" + proc.stderr.rstrip())

        return proc.returncode

    print("[INFO] Python:", sys.version)
    print("[INFO] ASCEND_HOME_PATH=", os.getenv("ASCEND_HOME_PATH"))
    print("[INFO] ASCEND_TOOLKIT_HOME=", os.getenv("ASCEND_TOOLKIT_HOME"))

    try:
        import acl  # type: ignore
    except Exception as e:
        print("[FAIL] import acl failed:", repr(e))
        traceback.print_exc()
        print("\n[INFO] sys.path (top 20):")
        for i, p in enumerate(sys.path[:20]):
            print(f"  [{i:02d}] {p}")
        print("\n可能原因：")
        print("- 未安装 CANN/ACL Python 包")
        print("- LD_LIBRARY_PATH 未包含 Ascend runtime 库路径")
        print("- Python 版本与 CANN 组件不匹配")
        print("\n建议你在板子上执行以下命令定位 acl 模块实际位置：")
        print("  sudo find /usr/local/Ascend -type d -name acl -path '*site-packages*' 2>/dev/null | head")
        print("  sudo find /usr/local/Ascend -type d -path '*site-packages*' 2>/dev/null | head")
        print("\n如果能找到类似 .../site-packages 目录，可临时这样跑：")
        print("  export PYTHONPATH=/path/to/site-packages:$PYTHONPATH")
        print("  python3 scripts/01_acl_smoke_test.py")
        return 2

    print("[OK] import acl succeeded")

    # init
    try:
        ret = acl.init()
        print("[INFO] acl.init() ->", ret)
    except TypeError:
        # 有些版本需要传 config 路径
        try:
            ret = acl.init("")
            print("[INFO] acl.init('') ->", ret)
        except Exception as e:
            print("[FAIL] acl.init failed:", repr(e))
            traceback.print_exc()
            return 3
    except Exception as e:
        print("[FAIL] acl.init failed:", repr(e))
        traceback.print_exc()
        return 3

    # acl.init 返回 0 才是成功（非 0 往往意味着运行时/驱动未就绪）
    if isinstance(ret, int) and ret != 0:
        print("[FAIL] acl.init returned non-zero, runtime likely not ready. ret=", ret)
        # 仍尝试 finalize，避免资源泄漏
        try:
            acl.finalize()
        except Exception:
            pass
        return 4

    # 尝试读取设备数量（不同版本返回值形式可能不同）
    device_count = None
    dc_ret = None
    try:
        if hasattr(acl, "rt") and hasattr(acl.rt, "get_device_count"):
            dc = acl.rt.get_device_count()
            # 可能是 (ret, count) 或直接 count
            if isinstance(dc, tuple) and len(dc) >= 2:
                dc_ret = int(dc[0])
                device_count = int(dc[1])
                print("[INFO] acl.rt.get_device_count() ->", dc)
            else:
                device_count = int(dc)
                print("[INFO] acl.rt.get_device_count() ->", device_count)
    except Exception as e:
        print("[WARN] get_device_count failed:", repr(e))

    if dc_ret is not None and dc_ret != 0:
        print(f"[FAIL] get_device_count returned ret={dc_ret} (runtime can init but cannot enumerate devices)")
    if device_count is not None and device_count <= 0:
        print("[WARN] device_count=0 (no NPU device visible yet)")

    # 深度探测（set_device/create_context）在驱动/固件异常时可能触发内核卡死/软锁。
    # 默认关闭；只有你明确需要更深错误形态时再开启：ACL_SMOKE_DEEP_PROBE=1
    if os.getenv("ACL_SMOKE_DEEP_PROBE") == "1":
        probe_rc = _run_deep_probe_subprocess(timeout_s=10)
        if probe_rc != 0:
            print(f"[WARN] deep probe returncode={probe_rc}")
    else:
        print("[INFO] deep probe skipped (set ACL_SMOKE_DEEP_PROBE=1 to enable)")

    # 如果枚举失败或数量为0，认为未就绪
    if (dc_ret is not None and dc_ret != 0) or (device_count is not None and device_count <= 0):
        try:
            acl.finalize()
        except Exception:
            pass
        return 5

    # finalize
    try:
        ret2 = acl.finalize()
        print("[INFO] acl.finalize() ->", ret2)
    except Exception as e:
        print("[WARN] acl.finalize failed:", repr(e))
        traceback.print_exc()

    print("[OK] ACL smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
