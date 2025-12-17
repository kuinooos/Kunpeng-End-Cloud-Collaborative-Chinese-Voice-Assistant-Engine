import time
import numpy as np
import os
import sys
import torch
import torchaudio  # 用于加载和处理音频文件
import json
from datetime import datetime
import argparse

# 运行示例：python ./test/benchmark_asr_cpu.py --onnx-model-path ./sensevoice_onnx_quant/model_quant.onnx --loops 20

# 添加当前目录到 sys.path 以便导入模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import global_settings
from models.asr_model import ASRModel
from models.asr_model_npu import ASRModelNPU


def run_benchmark():
    # ================= 加载真实 WAV 文件 =================
    default_wav = "/home/openEuler/KunpengChat/Server/test/echo.wav"  # <--- 修改为你的实际路径

    # CLI 参数：允许替换 WAV 路径、ONNX 模型以及循环次数
    parser = argparse.ArgumentParser(description='ASR CPU speed benchmark (PyTorch vs ONNX)')
    parser.add_argument('--onnx-model-path', dest='onnx_model_path', type=str, default=global_settings.ASR_ONNX_MODEL_PATH,
                        help='Path to ONNX model to test (default from config)')
    parser.add_argument('--loops', type=int, default=10, help='Number of inference loops per backend')
    parser.add_argument('--wav', type=str, default=default_wav, help='WAV file path to use')
    args = parser.parse_args()

    wav_path = args.wav

    if not os.path.exists(wav_path):
        print(f"[ERROR] WAV file not found: {wav_path}")
        print("请确认文件存在，并正确修改代码中的 wav_path 变量。")
        return

    try:
        print(f"Loading WAV file: {wav_path}")
        waveform, sample_rate = torchaudio.load(wav_path)

        if sample_rate != 16000:
            print(f"Resampling from {sample_rate}Hz to 16000Hz...")
            resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
            waveform = resampler(waveform)

        if waveform.shape[0] > 1:
            print(f"Converting {waveform.shape[0]}-channel to mono...")
            waveform = waveform.mean(dim=0, keepdim=True)

        audio_data = waveform.squeeze(0).numpy()

        max_abs = np.max(np.abs(audio_data))
        if max_abs > 0:
            audio_data = audio_data / max_abs * 0.95

        duration = len(audio_data) / 16000
        print(f"Successfully loaded audio:")
        print(f"   Path: {wav_path}")
        print(f"   Duration: {duration:.2f} seconds ({len(audio_data)} samples)")
        print(f"   Sample rate: 16000 Hz, mono, float32")
        print(f"   Amplitude range: [{audio_data.min():.4f}, {audio_data.max():.4f}]")

    except Exception as e:
        print(f"[ERROR] Failed to load or process WAV file: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"System Info: CPU Cores: {os.cpu_count()}")

    # 用于保存详细时间的字典
    benchmark_results = {
        "metadata": {
            "date": datetime.now().isoformat(),
            "wav_file": wav_path,
            "duration_seconds": round(duration, 2),
            "loops": args.loops,
            "onnx_model_path": args.onnx_model_path
        },
        "results": {
            "cpu-torch": {"times": []},
            "cpu-onnx": {"times": []}
        }
    }

    # ================= PyTorch Benchmark =================
    print("\n" + "="*50)
    print("--- Benchmarking PyTorch (CPU) ---")
    print("="*50)
    try:
        torch_model = ASRModel(device="cpu")
        if torch_model.model is None:
            print("Failed to load PyTorch model. Skipping.")
        else:
            # Warmup
            print("Warming up PyTorch model...")
            result = torch_model.ASR_generate_text(audio_data)
            print(f"Warmup output: {result}")

            # Run benchmark with per-iteration timing
            loops = args.loops
            print(f"Running {loops} inference loops...")
            torch_times = []
            start_total = time.time()
            for i in range(loops):
                start_iter = time.time()
                torch_model.ASR_generate_text(audio_data)
                end_iter = time.time()
                iter_time = end_iter - start_iter
                torch_times.append(iter_time)
                print(f"  Iteration {i+1:2d}: {iter_time*1000:.2f} ms")

            total_time = time.time() - start_total
            avg_time = total_time / loops
            print(f"PyTorch Total Time: {total_time:.4f} s")
            print(f"PyTorch Average Inference Time: {avg_time*1000:.2f} ms")

            # 保存到结果字典
            benchmark_results["results"]["cpu-torch"]["times"] = torch_times

            # 清理
            del torch_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            import gc
            gc.collect()

    except Exception as e:
        print(f"PyTorch Benchmark Failed: {e}")
        import traceback
        traceback.print_exc()

    # ================= ONNX Benchmark =================
    print("\n" + "="*50)
    print("--- Benchmarking ONNX Runtime (CPU) ---")
    print("="*50)
    try:
        onnx_path = args.onnx_model_path
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
                result = onnx_model.ASR_generate_text(audio_data)
                print(f"Warmup output: {result}")

                # Run benchmark with per-iteration timing
                loops = args.loops
                print(f"Running {loops} inference loops...")
                onnx_times = []
                start_total = time.time()
                for i in range(loops):
                    start_iter = time.time()
                    onnx_model.ASR_generate_text(audio_data)
                    end_iter = time.time()
                    iter_time = end_iter - start_iter
                    onnx_times.append(iter_time)
                    print(f"  Iteration {i+1:2d}: {iter_time*1000:.2f} ms")

                total_time = time.time() - start_total
                avg_time = total_time / loops
                print(f"ONNX Total Time: {total_time:.4f} s")
                print(f"ONNX Average Inference Time: {avg_time*1000:.2f} ms")

                # 保存到结果字典
                benchmark_results["results"]["cpu-onnx"]["times"] = onnx_times

                del onnx_model

    except Exception as e:
        print(f"ONNX Benchmark Failed: {e}")
        import traceback
        traceback.print_exc()

    # ================= 保存 JSON 结果 =================
    output_path = "benchmark_results.json"
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(benchmark_results, f, indent=2, ensure_ascii=False)
        print("\n" + "="*50)
        print(f"Benchmark results saved to: {os.path.abspath(output_path)}")
        print("You can now generate plots with:")
        print("    python test/plot_benchmark.py benchmark_results.json")
        print("="*50)
    except Exception as e:
        print(f"Failed to save JSON: {e}")


if __name__ == "__main__":
    run_benchmark()