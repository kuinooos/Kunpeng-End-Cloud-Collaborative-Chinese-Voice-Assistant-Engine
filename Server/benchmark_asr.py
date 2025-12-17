import time
import numpy as np
import os
import sys
import torch

# 添加当前目录到 sys.path 以便导入模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import global_settings
from models.asr_model import ASRModel
from models.asr_model_npu import ASRModelNPU

def run_benchmark():
    # 模拟音频数据 (5秒, 16kHz, float32)
    # SenseVoiceSmall 期望输入是 float32, 归一化到 [-1, 1]
    duration = 5 # 秒
    sample_rate = 16000
    audio_len = sample_rate * duration
    # 生成随机噪声作为音频
    audio_data = np.random.uniform(-0.1, 0.1, audio_len).astype(np.float32)

    print(f"Generating random audio data: {duration} seconds ({audio_len} samples)")
    print(f"System Info: CPU Cores: {os.cpu_count()}")

    # ================= PyTorch Benchmark =================
    print("\n" + "="*40)
    print("--- Benchmarking PyTorch (CPU) ---")
    print("="*40)
    try:
        # 强制使用 CPU
        torch_model = ASRModel(device="cpu")
        if torch_model.model is None:
            print("Failed to load PyTorch model. Skipping.")
        else:
            # Warmup
            print("Warming up PyTorch model...")
            torch_model.ASR_generate_text(audio_data)
            
            # Run
            loops = 10
            print(f"Running {loops} loops...")
            start_time = time.time()
            for i in range(loops):
                torch_model.ASR_generate_text(audio_data)
            end_time = time.time()
            
            avg_time = (end_time - start_time) / loops
            print(f"PyTorch Total Time: {end_time - start_time:.4f} s")
            print(f"PyTorch Average Inference Time: {avg_time*1000:.2f} ms")
            
            # 清理
            del torch_model
            import gc
            gc.collect()
            
    except Exception as e:
        print(f"PyTorch Benchmark Failed: {e}")
        import traceback
        traceback.print_exc()

    # ================= ONNX Benchmark =================
    print("\n" + "="*40)
    print("--- Benchmarking ONNX (CPU) ---")
    print("="*40)
    try:
        # 检查 ONNX 模型是否存在
        onnx_path = global_settings.ASR_ONNX_MODEL_PATH
        if not os.path.exists(onnx_path):
            print(f"ONNX model not found at {onnx_path}.")
            print("Please run 'export_sensevoice_onnx.py' first to generate the ONNX model.")
        else:
            print(f"Loading ONNX model from: {onnx_path}")
            onnx_model = ASRModelNPU(
                model_path=onnx_path,
                vocab_path=global_settings.ASR_VOCAB_PATH,
                device="cpu-onnx"
            )
            
            if onnx_model.session is None:
                print("Failed to create ONNX session. Skipping.")
            else:
                # Warmup
                print("Warming up ONNX model...")
                onnx_model.ASR_generate_text(audio_data)
                
                # Run
                loops = 10
                print(f"Running {loops} loops...")
                start_time = time.time()
                for i in range(loops):
                    onnx_model.ASR_generate_text(audio_data)
                end_time = time.time()
                
                avg_time = (end_time - start_time) / loops
                print(f"ONNX (CPU) Total Time: {end_time - start_time:.4f} s")
                print(f"ONNX (CPU) Average Inference Time: {avg_time*1000:.2f} ms")
                
                del onnx_model
                
    except Exception as e:
        print(f"ONNX Benchmark Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_benchmark()
