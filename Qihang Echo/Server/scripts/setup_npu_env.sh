#!/bin/bash
# ============================================================
# 在 Orange Pi Kunpeng Pro 上准备 NPU 加速环境的脚本
# ============================================================

set -e

echo "=== 检查 NPU 状态 ==="
if command -v npu-smi &> /dev/null; then
    npu-smi info
else
    echo "警告: npu-smi 未找到，请确保 CANN 已正确安装"
fi

echo ""
echo "=== 检查 CANN 环境 ==="
CANN_PATH="/usr/local/Ascend/ascend-toolkit/latest"
if [ -d "$CANN_PATH" ]; then
    echo "找到 CANN Toolkit: $CANN_PATH"
    source $CANN_PATH/bin/setenv.bash
else
    echo "警告: CANN Toolkit 未在默认路径找到"
    echo "请手动设置: source /path/to/ascend-toolkit/set_env.sh"
fi

echo ""
echo "=== 安装 Python 依赖 ==="
# 安装 onnxruntime-ascend (华为提供的 NPU 版本)
# 注意：需要从华为官方 PyPI 源安装
pip install onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple

# 如果有华为官方的 onnxruntime-ascend 包，使用以下命令：
# pip install onnxruntime-ascend -i https://mirrors.huaweicloud.com/repository/pypi/simple

echo ""
echo "=== 验证 ONNX Runtime 可用的 Provider ==="
python3 -c "import onnxruntime as ort; print('Available providers:', ort.get_available_providers())"

echo ""
echo "=== 环境准备完成 ==="
echo ""
echo "下一步操作："
echo "1. 修改 Server/config/settings.py 中的 ASR_DEVICE = 'npu'"
echo "2. 准备 ONNX 格式的 ASR 模型 (如 SenseVoice, WeNet)"
echo "3. (可选) 使用 atc 工具将 ONNX 转换为 .om 获得更好性能"
echo ""
echo "atc 转换命令示例:"
echo "  atc --model=asr_encoder.onnx --framework=5 --output=asr_encoder_npu \\"
echo "      --soc_version=Ascend310B1 --input_format=ND"
