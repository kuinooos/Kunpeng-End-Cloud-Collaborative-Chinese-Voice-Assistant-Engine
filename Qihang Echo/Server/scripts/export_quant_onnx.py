import os
from funasr import AutoModel

def main():
    model_dir = "/home/openEuler/KunpengChat/Server/models/FunAudioLLM/iic/SenseVoiceSmall"
    # 注意：输出到新的目录，避免覆盖给 NPU 用的 FP32 模型
    output_dir = "../sensevoice_onnx_quant" 
    
    print(f"正在加载模型用于量化导出: {model_dir}")

    model = AutoModel(
        model=model_dir,
        trust_remote_code=True,
        device="cpu", 
        disable_update=True
    )
    
    print("开始导出 Int8 量化模型 (这可能需要几分钟)...")
    
    # 关键修改：quantize=True
    model.export(
        output_dir=output_dir,
        quantize=True,     # <--- 开启量化！
        opset_version=14,
        type="onnx"
    )
    
    print(f"\n✅ 量化模型导出成功: {os.path.abspath(output_dir)}")

if __name__ == "__main__":
    main()
