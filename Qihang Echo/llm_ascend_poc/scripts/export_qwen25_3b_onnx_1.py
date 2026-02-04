#!/usr/bin/env python3
"""Export Qwen2.5 to ONNX for Ascend 310B4"""

import argparse
import os
from typing import List, Tuple

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoConfig
from transformers.cache_utils import DynamicCache


class FirstWrapper(torch.nn.Module):
    def __init__(self, model: torch.nn.Module, num_layers: int):
        super().__init__()
        self.model = model
        self.num_layers = num_layers

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor, position_ids: torch.Tensor):
        outputs = self.model(input_ids=input_ids, attention_mask=attention_mask, position_ids=position_ids, use_cache=True)
        flat_present = []
        for i in range(self.num_layers):
            k, v = outputs.past_key_values[i]
            flat_present.extend([k, v])
        return (outputs.logits, *flat_present)


class NextWrapper(torch.nn.Module):
    def __init__(self, model: torch.nn.Module, num_layers: int):
        super().__init__()
        self.model = model
        self.num_layers = num_layers

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor, position_ids: torch.Tensor, *past_key_values):
        cache = DynamicCache()
        for i in range(self.num_layers):
            k = past_key_values[2 * i]
            v = past_key_values[2 * i + 1]
            cache.update(k, v, layer_idx=i)
        outputs = self.model(input_ids=input_ids, attention_mask=attention_mask, position_ids=position_ids, past_key_values=cache, use_cache=True)
        flat_present = []
        for i in range(self.num_layers):
            k, v = outputs.past_key_values[i]
            flat_present.extend([k, v])
        return (outputs.logits, *flat_present)


def load_model(model_path: str, dtype: torch.dtype) -> Tuple[torch.nn.Module, AutoTokenizer]:
    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
    if hasattr(config, 'quantization_config'):
        delattr(config, 'quantization_config')
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and dtype == torch.float16:
        print("Warning: FP16 on CPU is unstable. Consider using --dtype float32")
    print(f"Loading model on {device} with dtype={dtype}")
    model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True, dtype=dtype, device_map=device, config=config)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    return model, tokenizer


def export_first(model: torch.nn.Module, seq_len: int, output_path: str, num_layers: int) -> None:
    device = next(model.parameters()).device
    dummy_input_ids = torch.zeros((1, seq_len), dtype=torch.long, device=device)
    dummy_attention = torch.ones((1, seq_len), dtype=torch.long, device=device)
    dummy_position_ids = torch.arange(seq_len, dtype=torch.long, device=device).unsqueeze(0)
    wrapper = FirstWrapper(model, num_layers)
    
    output_names = ["logits"]
    for i in range(num_layers):
        output_names.extend([f"present_key_values.{i}.key", f"present_key_values.{i}.value"])

    torch.onnx.export(wrapper, (dummy_input_ids, dummy_attention, dummy_position_ids), output_path, export_params=True, opset_version=18,
                      do_constant_folding=True, input_names=["input_ids", "attention_mask", "position_ids"], output_names=output_names, dynamic_axes=None)


def export_next(model: torch.nn.Module, past_len: int, output_path: str, num_layers: int, num_heads: int, head_dim: int) -> None:
    device = next(model.parameters()).device
    model_dtype = next(model.parameters()).dtype
    dummy_input_ids = torch.zeros((1, 1), dtype=torch.long, device=device)
    dummy_attention = torch.ones((1, past_len + 1), dtype=torch.long, device=device)
    dummy_position_ids = torch.tensor([[past_len]], dtype=torch.long, device=device)
    past_list: List[torch.Tensor] = []
    for _ in range(num_layers):
        k = torch.zeros((1, num_heads, past_len, head_dim), dtype=model_dtype, device=device)
        v = torch.zeros((1, num_heads, past_len, head_dim), dtype=model_dtype, device=device)
        past_list.extend([k, v])
    input_names = ["input_ids", "attention_mask", "position_ids"]
    for i in range(num_layers):
        input_names.extend([f"past_key_values.{i}.key", f"past_key_values.{i}.value"])
    output_names = ["logits"]
    for i in range(num_layers):
        output_names.extend([f"present_key_values.{i}.key", f"present_key_values.{i}.value"])
    wrapper = NextWrapper(model, num_layers)
    torch.onnx.export(wrapper, (dummy_input_ids, dummy_attention, dummy_position_ids, *past_list), output_path, export_params=True, opset_version=18,
                      do_constant_folding=True, input_names=input_names, output_names=output_names, dynamic_axes=None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Qwen ONNX for Ascend 310B4")
    parser.add_argument("--model-path", required=True, help="Path to HF model")
    parser.add_argument("--out-dir", default="./onnx_out", help="Output directory")
    parser.add_argument("--seq-len", type=int, default=128, help="Sequence length")
    parser.add_argument("--past-len", type=int, default=128, help="Past KV length")
    parser.add_argument("--dtype", default="float32", choices=["float16", "bfloat16", "float32"], help="Model dtype (use float32 for CPU, float16 for GPU)")
    parser.add_argument("--skip-first", action="store_true", help="Skip export of first token model")
    parser.add_argument("--only-first", action="store_true", help="Only export first token model")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.dtype == "float16":
        dtype = torch.float16
    elif args.dtype == "bfloat16":
        dtype = torch.bfloat16
    else:
        dtype = torch.float32
    os.makedirs(args.out_dir, exist_ok=True)
    config = AutoConfig.from_pretrained(args.model_path, trust_remote_code=True)
    if hasattr(config, 'quantization_config'):
        delattr(config, 'quantization_config')
    num_layers = config.num_hidden_layers
    num_heads = config.num_attention_heads
    num_kv_heads = getattr(config, 'num_key_value_heads', num_heads)
    head_dim = config.hidden_size // config.num_attention_heads
    print(f"Model config: layers={num_layers}, q_heads={num_heads}, kv_heads={num_kv_heads}, head_dim={head_dim}")
    model, _ = load_model(args.model_path, dtype=dtype)
    first_path = os.path.join(args.out_dir, "qwen25_0.5b_first.onnx")
    next_path = os.path.join(args.out_dir, "qwen25_0.5b_next.onnx")

    if not args.skip_first:
        export_first(model, seq_len=args.seq_len, output_path=first_path, num_layers=num_layers)
        print("Saved:", first_path)

    if not args.only_first:
        export_next(model, past_len=args.past_len, output_path=next_path, num_layers=num_layers, num_heads=num_kv_heads, head_dim=head_dim)
        print("Saved:", next_path)


if __name__ == "__main__":
    main()