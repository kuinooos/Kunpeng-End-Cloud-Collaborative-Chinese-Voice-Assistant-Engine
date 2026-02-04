#!/bin/bash
# ============================================================
# 从华为 ModelZoo 下载预转换的 ASR 模型
# 适用于 Orange Pi Kunpeng Pro (Ascend 310B)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL_DIR="$SCRIPT_DIR/../models/onnx"
mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"

echo "=============================================="
echo "华为 ModelZoo ASR 模型下载工具"
echo "=============================================="
echo ""

# ============ 方案 A: WeNet (推荐，官方深度适配) ============
download_wenet() {
    echo "[WeNet] 下载中..."
    
    # WeNet 官方 ONNX 模型 (中文)
    # 来源: https://github.com/wenet-e2e/wenet/releases
    WENET_URL="https://github.com/wenet-e2e/wenet/releases/download/v2.0.1/aishell_u2pp_conformer_exp.tar.gz"
    
    if [ ! -f "wenet_aishell.tar.gz" ]; then
        echo "  从 GitHub 下载 WeNet 模型..."
        wget -q --show-progress -O wenet_aishell.tar.gz "$WENET_URL" || {
            echo "  GitHub 下载失败，尝试镜像..."
            # 备用镜像
            wget -q --show-progress -O wenet_aishell.tar.gz \
                "https://ghproxy.com/$WENET_URL" || {
                echo "  ✗ 下载失败"
                return 1
            }
        }
    fi
    
    echo "  解压模型..."
    tar -xzf wenet_aishell.tar.gz
    
    # 查找 ONNX 文件
    find . -name "*.onnx" -exec echo "  找到: {}" \;
    
    echo "  ✓ WeNet 模型下载完成"
}

# ============ 方案 B: Paraformer (FunASR 系列) ============
download_paraformer() {
    echo "[Paraformer] 从 ModelScope 下载..."
    
    # 使用 Python 下载 (因为 ModelScope 需要认证)
    python3 << 'EOF'
import os
try:
    from modelscope.hub.snapshot_download import snapshot_download
    
    # Paraformer 中文语音识别
    model_dir = snapshot_download(
        'damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        cache_dir='./modelscope_cache'
    )
    print(f"  模型下载到: {model_dir}")
    
    # 检查是否有 ONNX
    import glob
    onnx_files = glob.glob(f"{model_dir}/**/*.onnx", recursive=True)
    if onnx_files:
        print(f"  找到 ONNX: {onnx_files}")
    else:
        print("  未找到 ONNX，需要手动导出")
        
except ImportError:
    print("  需要安装: pip install modelscope")
except Exception as e:
    print(f"  下载失败: {e}")
EOF
}

# ============ 方案 C: SenseVoice (你目前用的) ============
download_sensevoice() {
    echo "[SenseVoice] 导出 ONNX..."
    
    # 调用导出脚本
    python3 "$SCRIPT_DIR/export_sensevoice_onnx.py"
}

# ============ 主菜单 ============
echo "请选择要下载的模型:"
echo "  1) WeNet (推荐，华为官方适配)"
echo "  2) Paraformer (阿里 FunASR)"  
echo "  3) SenseVoice (导出你当前使用的模型)"
echo "  4) 全部下载"
echo ""
read -p "请输入选项 [1-4]: " choice

case $choice in
    1) download_wenet ;;
    2) download_paraformer ;;
    3) download_sensevoice ;;
    4) 
        download_wenet
        download_paraformer
        download_sensevoice
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac

echo ""
echo "=============================================="
echo "下载完成！模型位于: $MODEL_DIR"
echo ""
echo "转换为 NPU 格式 (.om):"
echo "  source /usr/local/Ascend/ascend-toolkit/latest/bin/setenv.bash"
echo "  atc --model=xxx.onnx --framework=5 --output=xxx_npu --soc_version=Ascend310B1"
echo "=============================================="
