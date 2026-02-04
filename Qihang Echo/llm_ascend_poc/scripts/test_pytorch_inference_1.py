#!/usr/bin/env python3
"""验证 PyTorch 模型本身是否工作正常"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# 加载模型
model_path = "/root/autodl-tmp/Qwen2.5-0.5B-Instruct"
print("Loading model...")
model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True, torch_dtype=torch.float32, device_map="cpu")
tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
model.eval()

# 构造输入
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "hello"}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
print(f"Input text: {text[:100]}...")

inputs = tokenizer([text], return_tensors="pt")
print(f"Input IDs shape: {inputs.input_ids.shape}")

# 推理
print("Running inference...")
with torch.no_grad():
    outputs = model.generate(
        inputs.input_ids,
        attention_mask=inputs.attention_mask,
        max_new_tokens=20,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id
    )

# 解码
response = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(f"\nModel output:\n{response}")
