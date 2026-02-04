import argparse

def get_qwen25_3b_config():
    # Qwen2.5-3B 默认配置
    return {
        "num_layers": 36,
        "num_kv_heads": 2,
        "head_dim": 128
    }

def gen_first_cmd(args):
    # input_ids: [1, seq_len], attention_mask: [1, seq_len]
    shape_str = f"input_ids:1,{args.seq_len};attention_mask:1,{args.seq_len}"
    
    cmd = (
        f"atc --model=./qwen25_first.onnx "
        f"--framework=5 "
        f"--output=./qwen25_first "
        f"--input_format=ND "
        f"--input_shape=\"{shape_str}\" "
        f"--soc_version=Ascend310B4 "
        f"--log=error"
    )
    return cmd

def gen_next_cmd(args):
    config = get_qwen25_3b_config()
    num_layers = config["num_layers"]
    num_kv_heads = config["num_kv_heads"]
    head_dim = config["head_dim"]
    past_len = args.past_len
    
    # 基础输入
    # input_ids: [1, 1]
    # attention_mask: [1, past_len + 1]
    shapes = [
        "input_ids:1,1",
        f"attention_mask:1,{past_len + 1}"
    ]
    
    # KV Cache 输入
    # past_key_values.{i}.key: [1, num_kv_heads, past_len, head_dim]
    for i in range(num_layers):
        kv_shape = f"1,{num_kv_heads},{past_len},{head_dim}"
        shapes.append(f"past_key_values.{i}.key:{kv_shape}")
        shapes.append(f"past_key_values.{i}.value:{kv_shape}")
        
    shape_str = ";".join(shapes)
    
    cmd = (
        f"atc --model=./qwen25_next.onnx "
        f"--framework=5 "
        f"--output=./qwen25_next "
        f"--input_format=ND "
        f"--input_shape=\"{shape_str}\" "
        f"--soc_version=Ascend310B4 "
        f"--log=error"
    )
    return cmd

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seq-len", type=int, default=128, help="Sequence length used in export (default: 128)")
    parser.add_argument("--past-len", type=int, default=128, help="Past length used in export (default: 128)")
    args = parser.parse_args()

    print("=== Command for qwen25_first.onnx ===")
    print(gen_first_cmd(args))
    print("\n=== Command for qwen25_next.onnx ===")
    print(gen_next_cmd(args))
