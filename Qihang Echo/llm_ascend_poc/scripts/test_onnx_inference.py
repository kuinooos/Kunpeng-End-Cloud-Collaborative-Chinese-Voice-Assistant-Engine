#!/usr/bin/env python3
"""验证导出的 ONNX 模型是否正确"""

import sys
import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

# 加载 tokenizer
tokenizer_path = sys.argv[1] if len(sys.argv) > 1 else "./qwen_tokenizer"
print(f"Loading tokenizer from {tokenizer_path}...")
tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

# 构造输入
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "hello"}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
print(f"Input text: {text[:100]}...")

inputs = tokenizer([text], return_tensors="np")
input_ids = inputs.input_ids.astype(np.int64)
attention_mask = inputs.attention_mask.astype(np.int64)

print(f"Original input shape: {input_ids.shape}")

# Padding 到 128
seq_len = input_ids.shape[1]
EXPORT_SEQ_LEN = 128
pad_len = EXPORT_SEQ_LEN - seq_len
padded_input_ids = np.pad(input_ids, ((0,0), (0, pad_len)), 'constant')
padded_mask = np.pad(attention_mask, ((0,0), (0, pad_len)), 'constant')

# 生成 position_ids
position_ids = np.zeros_like(padded_mask, dtype=np.int64)
valid_len = np.sum(padded_mask[0])
position_ids[0, :valid_len] = np.arange(valid_len, dtype=np.int64)

print(f"Padded shapes: input_ids={padded_input_ids.shape}, mask={padded_mask.shape}, pos={position_ids.shape}")
print(f"Valid length: {valid_len}")

# 加载 ONNX 模型
print("\nLoading ONNX model...")
sess = ort.InferenceSession("./onnx_out/qwen25_0.5b_first.onnx", providers=['CPUExecutionProvider'])

# 推理
print("Running ONNX inference...")
outputs = sess.run(None, {
    "input_ids": padded_input_ids,
    "attention_mask": padded_mask,
    "position_ids": position_ids
})

logits = outputs[0]
print(f"Logits shape: {logits.shape}, dtype: {logits.dtype}")

# 获取下一个 token
next_token_id = np.argmax(logits[0, seq_len-1, :])
print(f"Next token ID: {next_token_id}")
print(f"Decoded: '{tokenizer.decode([next_token_id])}'")

# 生成几个 token
print("\nGenerating tokens...")
generated = [next_token_id]
for _ in range(10):
    token_str = tokenizer.decode([next_token_id])
    print(token_str, end="", flush=True)
    if next_token_id == tokenizer.eos_token_id:
        break
    # 这里为了简化，只生成第一个 token，完整的需要用 Next 模型
    break

print("\n\nIf you see reasonable text above, ONNX export is correct.")
print("If it's garbage, there's a problem with ONNX export.")
