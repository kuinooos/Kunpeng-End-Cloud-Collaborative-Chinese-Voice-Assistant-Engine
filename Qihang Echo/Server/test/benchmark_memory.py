"""
内存开销基准测试脚本：对比 PyTorch (CPU) 与 ONNX Runtime (CPU) 的内存占用。
使用多进程隔离测试，确保结果互不干扰。

用法：
    python test/benchmark_memory.py

示例：
    # 使用默认配置中的 ONNX 模型
    python test/benchmark_memory.py

    # 指定要测试的 ONNX 模型文件（比如量化模型），并进行多次推理以记录每次时间
    python test/benchmark_memory.py --onnx-model Server/sensevoice_onnx_quant/model_quant.onnx --loops 5
"""
import os
import time
import sys
import multiprocessing
import numpy as np
from config.settings import global_settings

def get_process_memory_mb():
    """获取当前进程的物理内存占用 (RSS) 单位: MB"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        # Linux fallback
        try:
            with open(f'/proc/{os.getpid()}/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        # VmRSS:    1234 kB
                        parts = line.split()
                        if len(parts) >= 2:
                            return float(parts[1]) / 1024
        except Exception:
            pass
    return 0.0

def make_test_audio(duration_s=1.0, sr=16000):
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    data = 0.1 * np.sin(2 * np.pi * 1000 * t)
    return data.astype(np.float32)

def run_torch_test(queue, loops=1):
    """在独立进程中测试 PyTorch 内存并记录每次推理时间"""
    try:
        # 1. 初始基准
        import gc
        gc.collect()
        base_mem = get_process_memory_mb()
        
        # 2. 加载库
        import torch
        from models.asr_model import ASRModel
        
        # 3. 加载模型
        print("[PyTorch] Loading model...")
        start_load_mem = get_process_memory_mb()
        model = ASRModel(device='cpu-torch')
        loaded_mem = get_process_memory_mb()
        
        # 4. 推理多次并记录每次耗时与内存采样
        print(f"[PyTorch] Running inference for {loops} loops...")
        audio = make_test_audio()
        times = []
        mem_samples = []
        for i in range(loops):
            t0 = time.time()
            model.ASR_generate_text(audio)
            t1 = time.time()
            times.append((t1 - t0) * 1000.0)  # ms
            mem_samples.append(get_process_memory_mb())
            print(f"  Iter {i+1}: {times[-1]:.2f} ms, mem={mem_samples[-1]:.1f} MB")

        peak_mem = max(mem_samples) if mem_samples else get_process_memory_mb()
        
        result = {
            'name': 'cpu-torch',
            'base_mb': base_mem,
            'loaded_mb': loaded_mem,
            'peak_mb': peak_mem,
            'increment_mb': peak_mem - base_mem,
            'times_ms': times,
            'mem_after_iters_mb': mem_samples
        }
        queue.put(result)
    except Exception as e:
        queue.put({'name': 'cpu-torch', 'error': str(e)})

def run_onnx_test(queue, model_path, loops=1):
    """在独立进程中测试 ONNX 内存并记录每次推理时间"""
    try:
        # 1. 初始基准
        import gc
        gc.collect()
        base_mem = get_process_memory_mb()
        
        # 2. 加载库
        import onnxruntime
        from models.asr_model_npu import create_asr_model
        
        # 3. 加载模型
        print(f"[ONNX] Loading model: {model_path} ...")
        start_load_mem = get_process_memory_mb()
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX model not found: {model_path}")
        model = create_asr_model(
            device='cpu-onnx',
            model_path=model_path,
            vocab_path=global_settings.ASR_VOCAB_PATH
        )
        loaded_mem = get_process_memory_mb()
        
        # 4. 推理多次并记录每次耗时与内存采样
        print(f"[ONNX] Running inference for {loops} loops...")
        audio = make_test_audio()
        times = []
        mem_samples = []
        for i in range(loops):
            t0 = time.time()
            model.ASR_generate_text(audio)
            t1 = time.time()
            times.append((t1 - t0) * 1000.0)  # ms
            mem_samples.append(get_process_memory_mb())
            print(f"  Iter {i+1}: {times[-1]:.2f} ms, mem={mem_samples[-1]:.1f} MB")

        peak_mem = max(mem_samples) if mem_samples else get_process_memory_mb()
        
        result = {
            'name': 'cpu-onnx',
            'base_mb': base_mem,
            'loaded_mb': loaded_mem,
            'peak_mb': peak_mem,
            'increment_mb': peak_mem - base_mem,
            'times_ms': times,
            'mem_after_iters_mb': mem_samples
        }
        queue.put(result)
    except Exception as e:
        queue.put({'name': 'cpu-onnx', 'error': str(e)})

def print_bar(val, max_val, width=20):
    if max_val == 0: return ""
    n = int((val / max_val) * width)
    return "█" * n + "░" * (width - n)

def main():
    print("Starting Memory Benchmark (using multiprocessing isolation)...")
    print("-" * 60)
    parser = __import__('argparse').ArgumentParser(description='Memory benchmark for ASR backends')
    parser.add_argument('--onnx-model', type=str, default=global_settings.ASR_NPU_MODEL_PATH,
                        help='Path to ONNX model to test (default from config)')
    parser.add_argument('--loops', type=int, default=1, help='Number of inference loops to run and record')
    args = parser.parse_args()

    q = multiprocessing.Queue()

    # Run PyTorch (pass loops)
    p1 = multiprocessing.Process(target=run_torch_test, args=(q, args.loops))
    p1.start()
    p1.join()
    res_torch = q.get()

    # Run ONNX (use provided model path and loops)
    p2 = multiprocessing.Process(target=run_onnx_test, args=(q, args.onnx_model, args.loops))
    p2.start()
    p2.join()
    res_onnx = q.get()
    
    print("-" * 60)
    print(f"{'Backend':<12} | {'Base (MB)':<10} | {'Peak (MB)':<10} | {'Increment (MB)':<15}")
    print("-" * 60)
    
    results = [res_torch, res_onnx]
    max_inc = max((r.get('increment_mb', 0) for r in results if 'error' not in r), default=1)
    
    for r in results:
        if 'error' in r:
            print(f"{r['name']:<12} | ERROR: {r['error']}")
        else:
            print(f"{r['name']:<12} | {r['base_mb']:<10.1f} | {r['peak_mb']:<10.1f} | {r['increment_mb']:<10.1f} {print_bar(r['increment_mb'], max_inc)}")
            # If per-iteration times are available, print a concise summary
            if r.get('times_ms'):
                times = r['times_ms']
                avg = sum(times) / len(times)
                print(f"{'':<12}   Avg time: {avg:.2f} ms over {len(times)} runs; times (ms): {', '.join(f'{t:.1f}' for t in times)}")
            if r.get('mem_after_iters_mb'):
                mems = r['mem_after_iters_mb']
                print(f"{'':<12}   Mem samples (MB): {', '.join(f'{m:.1f}' for m in mems)}")
            
    print("-" * 60)
    
    # Analysis
    if 'error' not in res_torch and 'error' not in res_onnx:
        diff = res_torch['increment_mb'] - res_onnx['increment_mb']
        ratio = res_torch['increment_mb'] / res_onnx['increment_mb'] if res_onnx['increment_mb'] > 0 else 0
        print(f"\nSummary:")
        print(f"ONNX Runtime saves approximately {diff:.1f} MB RAM compared to PyTorch.")
        print(f"Memory usage ratio (PyTorch / ONNX): {ratio:.2f}x")
        print("\n[Note] 'Increment' represents the memory added by loading the model and running inference,")
        print("       excluding the base overhead of the Python interpreter.")

if __name__ == '__main__':
    main()

