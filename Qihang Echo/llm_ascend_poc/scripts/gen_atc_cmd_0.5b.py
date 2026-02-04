import argparse

def get_qwen25_05b_config():
    # Qwen2.5-0.5B 配置
    # Hidden size: 896
    # Heads: 14
    # KV Heads: 2
    # Layers: 24
    return {
        "num_layers": 24,
        "num_kv_heads": 2,
        "head_dim": 64  # 896 / 14 = 64
    }

def gen_first_cmd(args):
    shape_str = f"input_ids:1,{args.seq_len};attention_mask:1,{args.seq_len};position_ids:1,{args.seq_len}"
    
    # 尝试多种 ATC 参数组合
    configs = [
        # 1. 默认配置（已失败）
        "",
        # 2. 强制 FP32 计算
        "--precision_mode=allow_fp32_to_fp16 ",
        # 3. 禁用混合精度
        "--precision_mode=force_fp32 ",
        # 4. 自动混合精度
        "--precision_mode=allow_mix_precision ",
        # 5. 选择高精度算子实现
        "--op_select_implmode=high_precision ",
        # 6. 禁用融合优化
        "--fusion_switch_file=disable_all.cfg ",
    ]
    
    cmds = []
    for i, extra in enumerate(configs):
        output_name = f"./qwen25_0.5b_first_v{i}" if i > 0 else "./qwen25_0.5b_first"
        cmd = (
            f"# 配置 {i}: {extra.strip() or '默认'}\n"
            f"atc --model=./qwen25_0.5b_first.onnx "
            f"--framework=5 "
            f"--output={output_name} "
            f"--input_format=ND "
            f"--input_shape=\"{shape_str}\" "
            f"{extra}"
            f"--soc_version=Ascend310B4"
        )
        cmds.append(cmd)
    
    return "\n\n".join(cmds)

def gen_next_cmd(args):
    config = get_qwen25_05b_config()
    num_layers = config["num_layers"]
    num_kv_heads = config["num_kv_heads"]
    head_dim = config["head_dim"]
    past_len = args.past_len
    
    shapes = [
        "input_ids:1,1",
        f"attention_mask:1,{past_len + 1}",
        "position_ids:1,1"
    ]
    
    for i in range(num_layers):
        kv_shape = f"1,{num_kv_heads},{past_len},{head_dim}"
        shapes.append(f"past_key_values.{i}.key:{kv_shape}")
        shapes.append(f"past_key_values.{i}.value:{kv_shape}")
        
    shape_str = ";".join(shapes)
    
    cmd = (
        f"atc --model=./qwen25_0.5b_next.onnx "
        f"--framework=5 "
        f"--output=./qwen25_0.5b_next "
        f"--input_format=ND "
        f"--input_shape=\"{shape_str}\" "
        f"--soc_version=Ascend310B4"
    )
    return cmd

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seq-len", type=int, default=128, help="Sequence length used in export")
    parser.add_argument("--past-len", type=int, default=128, help="Past length used in export")
    args = parser.parse_args()

    print("=== Command for qwen25_0.5b_first.onnx ===")
    print(gen_first_cmd(args))
    print("\n=== Command for qwen25_0.5b_next.onnx ===")
    print(gen_next_cmd(args))
