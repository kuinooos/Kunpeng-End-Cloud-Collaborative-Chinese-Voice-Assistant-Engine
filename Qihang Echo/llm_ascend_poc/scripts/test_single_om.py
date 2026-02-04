#!/usr/bin/env python3
"""使用单个 OM 模型进行推理测试"""

import os
import sys
import time
import numpy as np
import acl
from transformers import AutoTokenizer

def check_ret(ret, message):
    if ret != 0:
        print(f"Error: {message} failed ret={ret}")
        sys.exit(1)

class AscendLLMSingle:
    def __init__(self, model_path, device_id=0):
        self.device_id = device_id
        self.context = None
        self.stream = None
        self.model_id = None
        self.model_desc = None
        self.model_path = model_path

    def init_resource(self):
        ret = acl.init()
        check_ret(ret, "acl.init")
        ret = acl.rt.set_device(self.device_id)
        check_ret(ret, "acl.rt.set_device")
        self.context, ret = acl.rt.create_context(self.device_id)
        check_ret(ret, "acl.rt.create_context")
        self.stream, ret = acl.rt.create_stream()
        check_ret(ret, "acl.rt.create_stream")
        print("[Init] Ascend resources initialized.")

    def load_model(self):
        self.model_id, ret = acl.mdl.load_from_file(self.model_path)
        check_ret(ret, f"load model {self.model_path}")
        self.model_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self.model_desc, self.model_id)
        check_ret(ret, "get model desc")
        print("[Load] Model loaded successfully.")
        self._print_model_info()

    def _print_model_info(self):
        num_inputs = acl.mdl.get_num_inputs(self.model_desc)
        num_outputs = acl.mdl.get_num_outputs(self.model_desc)
        print(f"\nModel Info:")
        print(f"  Inputs: {num_inputs}")
        for i in range(num_inputs):
            dtype = acl.mdl.get_input_data_type(self.model_desc, i)
            dims, _ = acl.mdl.get_input_dims(self.model_desc, i)
            print(f"    [{i}] dtype={dtype}, shape={dims['dims']}")
        print(f"  Outputs: {num_outputs}")
        for i in range(min(3, num_outputs)):  # 只显示前3个输出
            dtype = acl.mdl.get_output_data_type(self.model_desc, i)
            dims, _ = acl.mdl.get_output_dims(self.model_desc, i)
            print(f"    [{i}] dtype={dtype}, shape={dims['dims']}")
        if num_outputs > 3:
            print(f"    ... and {num_outputs - 3} more outputs")

    def _get_numpy_dtype(self, acl_dtype):
        if acl_dtype == 0: return np.float32
        if acl_dtype == 1: return np.float16
        if acl_dtype == 3: return np.int32
        if acl_dtype == 9: return np.int64
        return np.float32

    def _create_dataset(self, inputs):
        dataset = acl.mdl.create_dataset()
        buffers = []
        for i, data in enumerate(inputs):
            # 类型转换
            expected_dtype_acl = acl.mdl.get_input_data_type(self.model_desc, i)
            expected_dtype = self._get_numpy_dtype(expected_dtype_acl)
            if data.dtype != expected_dtype:
                data = data.astype(expected_dtype)
            
            if not data.flags['C_CONTIGUOUS']:
                data = np.ascontiguousarray(data)
            
            ptr = acl.util.numpy_to_ptr(data)
            size = data.nbytes
            data_buffer = acl.create_data_buffer(ptr, size)
            acl.mdl.add_dataset_buffer(dataset, data_buffer)
            buffers.append(data_buffer)
        return dataset, buffers

    def _create_output_dataset(self):
        dataset = acl.mdl.create_dataset()
        num = acl.mdl.get_num_outputs(self.model_desc)
        buffers = []
        dev_ptrs = []
        
        for i in range(num):
            size = acl.mdl.get_output_size_by_index(self.model_desc, i)
            dev_ptr, ret = acl.rt.malloc(size, 2)
            check_ret(ret, f"malloc output {i}")
            
            data_buffer = acl.create_data_buffer(dev_ptr, size)
            acl.mdl.add_dataset_buffer(dataset, data_buffer)
            buffers.append(data_buffer)
            dev_ptrs.append(dev_ptr)
            
        return dataset, buffers, dev_ptrs

    def _dev_to_host(self, dev_ptr, shape, dtype=np.float16):
        size = int(np.prod(shape) * np.dtype(dtype).itemsize)
        host_ptr, ret = acl.rt.malloc_host(size)
        check_ret(ret, "malloc host")
        
        ret = acl.rt.memcpy(host_ptr, size, dev_ptr, size, 2)
        check_ret(ret, "memcpy device to host")
        
        data_bytes = acl.util.ptr_to_bytes(host_ptr, size)
        data_np = np.frombuffer(data_bytes, dtype=dtype).reshape(shape).copy()
        
        acl.rt.free_host(host_ptr)
        return data_np

    def forward(self, input_ids, attention_mask, past_key_values=None):
        """统一的推理接口"""
        # 准备输入
        inputs = [input_ids, attention_mask]
        
        # 检查是否需要 position_ids
        num_inputs = acl.mdl.get_num_inputs(self.model_desc)
        
        # 如果有 past_key_values，添加到输入
        if past_key_values is not None:
            for k, v in past_key_values:
                inputs.extend([k, v])
        
        # 如果还缺输入，可能需要 position_ids
        if len(inputs) < num_inputs and past_key_values is None:
            # 生成 position_ids
            position_ids = np.zeros_like(attention_mask, dtype=np.int64)
            valid_len = np.sum(attention_mask[0])
            position_ids[0, :valid_len] = np.arange(valid_len, dtype=np.int64)
            inputs.insert(2, position_ids)
        
        input_dataset, input_buffers = self._create_dataset(inputs)
        output_dataset, output_buffers, output_ptrs = self._create_output_dataset()
        
        # 执行
        ret = acl.mdl.execute(self.model_id, input_dataset, output_dataset)
        check_ret(ret, "execute model")
        
        # 获取 logits (第一个输出)
        logits_ptr = output_ptrs[0]
        logits_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.model_desc, 0))
        dims, _ = acl.mdl.get_output_dims(self.model_desc, 0)
        logits_shape = tuple(dims['dims'])
        logits = self._dev_to_host(logits_ptr, logits_shape, logits_dtype)
        
        # 获取 KV Cache (如果有)
        present_key_values = []
        num_outputs = len(output_ptrs)
        if num_outputs > 1:
            num_layers = (num_outputs - 1) // 2
            for i in range(num_layers):
                k_ptr = output_ptrs[1 + 2*i]
                v_ptr = output_ptrs[1 + 2*i + 1]
                
                k_dims, _ = acl.mdl.get_output_dims(self.model_desc, 1 + 2*i)
                k_shape = tuple(k_dims['dims'])
                k_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.model_desc, 1 + 2*i))
                v_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.model_desc, 1 + 2*i + 1))
                
                k = self._dev_to_host(k_ptr, k_shape, k_dtype)
                v = self._dev_to_host(v_ptr, k_shape, v_dtype)
                present_key_values.append((k, v))
        
        return logits, present_key_values

    def release(self):
        acl.finalize()

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_single_om.py <model.om> [tokenizer_path]")
        sys.exit(1)

    model_path = sys.argv[1]
    tokenizer_path = sys.argv[2] if len(sys.argv) > 2 else "./qwen_tokenizer"

    print("Loading Tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

    llm = AscendLLMSingle(model_path)
    llm.init_resource()
    llm.load_model()

    print("\n" + "="*20 + " Chat Test " + "="*20)
    
    # 测试对话
    query = input("User: ")
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": query}
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text], return_tensors="np")
    
    input_ids = model_inputs.input_ids.astype(np.int64)
    attention_mask = model_inputs.attention_mask.astype(np.int64)
    
    seq_len = input_ids.shape[1]
    print(f"\nInput length: {seq_len}")
    print(f"Assistant: ", end="", flush=True)
    
    start_time = time.time()
    
    # 推理
    logits, past_key_values = llm.forward(input_ids, attention_mask)
    
    # 获取下一个 token
    next_token_id = np.argmax(logits[0, -1, :])
    token_str = tokenizer.decode([next_token_id])
    print(token_str, end="", flush=True)
    
    # 生成更多 tokens
    max_new_tokens = 50
    generated = [next_token_id]
    
    for _ in range(max_new_tokens - 1):
        if next_token_id == tokenizer.eos_token_id:
            break
        
        # 下一轮推理（这里简化处理，实际可能需要调整）
        next_input_ids = np.array([[next_token_id]], dtype=np.int64)
        next_attention_mask = np.ones((1, seq_len + len(generated)), dtype=np.int64)
        
        # 如果模型支持 KV cache，传入 past_key_values
        logits, past_key_values = llm.forward(next_input_ids, next_attention_mask, past_key_values if past_key_values else None)
        
        next_token_id = np.argmax(logits[0, -1, :])
        generated.append(next_token_id)
        token_str = tokenizer.decode([next_token_id])
        print(token_str, end="", flush=True)
    
    print(f"\n\nGeneration time: {time.time() - start_time:.2f}s")
    print(f"Tokens generated: {len(generated)}")
    
    llm.release()

if __name__ == "__main__":
    main()
