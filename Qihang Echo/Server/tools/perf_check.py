import os
import subprocess

def run(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
        return out.strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()

def blas_info():
    try:
        import numpy as np
        print("[NumPy] config:")
        np.__config__.show()
    except Exception as e:
        print(f"[NumPy] not available: {e}")

def torch_info():
    try:
        import torch
        print("[Torch] version:", torch.__version__)
        print("[Torch] threads:", torch.get_num_threads(), torch.get_num_interop_threads())
        print("[Torch] has_mps:", hasattr(torch, 'has_mps') and torch.has_mps)
        print("[Torch] cuda available:", torch.cuda.is_available())
    except Exception as e:
        print(f"[Torch] not available: {e}")

def opus_neon_info():
    path = run("python -c \"import ctypes,ctypes.util; print(ctypes.util.find_library('opus'))\"")
    print("[Opus] lib path:", path)
    if path:
        print(run(f"readelf -A `ldconfig -p | grep libopus | awk '{{print $4}}' | head -n1` | grep -i neon || true"))

def affinity_info():
    print("[Affinity] taskset:", run("taskset -p $$"))
    print("[NUMA] numactl --hardware:\n", run("numactl --hardware"))

if __name__ == '__main__':
    print("== Environment ==")
    for k in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS","MKL_NUM_THREADS"]:
        print(f"{k}=", os.environ.get(k))
    print("== BLAS/Torch ==")
    blas_info()
    torch_info()
    print("== Opus/NEON ==")
    opus_neon_info()
    print("== Affinity/NUMA ==")
    affinity_info()
