import os
import shutil
from funasr import AutoModel

def main():
    # 1. 指定您刚刚找到的本地模型绝对路径
    model_dir = "/home/book/.cache/modelscope/hub/models/iic/SenseVoiceSmall"
    
    # 2. 指定导出结果存放的目录 (建议放在您的项目目录下)
    output_dir = "./sensevoice_onnx_output"
    
    print(f"正在从本地路径加载模型: {model_dir}")

    try:
        # 加载模型
        # disable_update=True: 禁止它去联网检查更新，防止卡住
        model = AutoModel(
            model=model_dir,
            trust_remote_code=True,
            device="cpu", 
            disable_update=True
        )
        
        print("模型加载成功，准备导出 ONNX...")

        # 3. 使用 FunASR 官方的 export 方法
        # 这会自动处理 forward 函数参数不匹配的问题
        model.export(
            output_dir=output_dir,
            quantize=False,    # 昇腾NPU不需要在这里量化，保持精度
            opset_version=14,  # 推荐版本
            type="onnx"        # 明确指定导出类型
        )
        
        print("\n" + "="*30)
        print("✅ 导出成功！")
        print(f"导出文件位置: {os.path.abspath(output_dir)}")
        print("="*30)
        
        # 检查生成的文件
        if os.path.exists(output_dir):
            print("生成的关键文件列表:")
            for f in os.listdir(output_dir):
                print(f" - {f}")
                
    except Exception as e:
        print(f"\n❌ 导出失败: {e}")
        print("\n如果报错提示 'AutoModel object has no attribute export'，请尝试更新 funasr:")
        print("pip install --upgrade funasr")

if __name__ == "__main__":
    main()