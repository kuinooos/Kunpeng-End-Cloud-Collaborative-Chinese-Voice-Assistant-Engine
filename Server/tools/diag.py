def print_runtime_diagnostics():
    try:
        import platform, os
        print("== Platform ==")
        print(platform.platform())
        print(platform.machine())
        print("OMP_NUM_THREADS=", os.environ.get("OMP_NUM_THREADS"))
        print("OPENBLAS_NUM_THREADS=", os.environ.get("OPENBLAS_NUM_THREADS"))
    except Exception:
        pass

    try:
        import numpy as np
        print("== NumPy ==", np.__version__)
        try:
            np.__config__.show()
        except Exception:
            pass
    except Exception as e:
        print("NumPy not available:", e)

    try:
        import torch
        print("== Torch ==", torch.__version__)
        try:
            print("xnnpack:", getattr(torch.backends, "xnnpack", None) and torch.backends.xnnpack.enabled)
        except Exception:
            pass
        try:
            print("threads:", torch.get_num_threads(), torch.get_num_interop_threads())
        except Exception:
            pass
        try:
            torch.__config__.show()
        except Exception:
            pass
    except Exception as e:
        print("Torch not available:", e)

    try:
        import onnxruntime as ort
        print("== ONNX Runtime ==", ort.__version__)
        try:
            providers = ort.get_available_providers()
            print("providers:", providers)
        except Exception:
            print("onnxruntime: failed to get providers")
        try:
            # 附加信息：CANN/Ascend 在 providers 中通常以 CANNExecutionProvider 出现
            if 'CANNExecutionProvider' in providers:
                print('CANNExecutionProvider available')
            if any('CPU' in p for p in providers):
                print('CPUExecutionProvider available')
        except Exception:
            pass
    except Exception:
        pass

    # CPU flags (Linux): 检查 NEON/ASIMD 等指令集支持
    try:
        import os
        if os.path.exists('/proc/cpuinfo'):
            with open('/proc/cpuinfo', 'r', encoding='utf-8', errors='ignore') as f:
                cpuinfo = f.read()
            has_neon = 'neon' in cpuinfo.lower() or 'asimd' in cpuinfo.lower()
            print('CPU NEON/ASIMD support:', has_neon)
    except Exception:
        pass

    # Ascend ACL 可用性检测
    try:
        import acl
        print('ACL available')
    except Exception:
        pass
