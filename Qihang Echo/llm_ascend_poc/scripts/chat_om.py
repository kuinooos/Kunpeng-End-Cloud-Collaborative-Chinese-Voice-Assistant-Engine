import os
import sys
import time
import numpy as np
import acl
from transformers import AutoTokenizer

# 错误码检查
def check_ret(ret, message):
    if ret != 0:
        print(f"Error: {message} failed ret={ret}")
        sys.exit(1)

class AscendLLM:
    def __init__(self, first_model_path, next_model_path, device_id=0):
        self.device_id = device_id
        self.context = None
        self.stream = None
        self.first_model_id = None
        self.next_model_id = None
        self.first_desc = None
        self.next_desc = None
        
        self.first_path = first_model_path
        self.next_path = next_model_path

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

    def load_models(self):
        # Load First Model
        self.first_model_id, ret = acl.mdl.load_from_file(self.first_path)
        check_ret(ret, f"load first model {self.first_path}")
        self.first_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self.first_desc, self.first_model_id)
        check_ret(ret, "get first model desc")
        
        # Load Next Model
        self.next_model_id, ret = acl.mdl.load_from_file(self.next_path)
        check_ret(ret, f"load next model {self.next_path}")
        self.next_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self.next_desc, self.next_model_id)
        check_ret(ret, "get next model desc")
        
        print("[Load] Models loaded successfully.")
        self._print_model_desc(self.first_desc, "First Model")
        self._print_model_desc(self.next_desc, "Next Model")
        
        # 检测模型是否需要 position_ids
        self.first_needs_position_ids = (acl.mdl.get_num_inputs(self.first_desc) == 3)
        self.next_needs_position_ids = (acl.mdl.get_num_inputs(self.next_desc) >= 51)  # 3 + 24*2
        print(f"[Config] First model needs position_ids: {self.first_needs_position_ids}")
        print(f"[Config] Next model needs position_ids: {self.next_needs_position_ids}")

    def _print_model_desc(self, desc, name):
        print(f"Model: {name}")
        num_inputs = acl.mdl.get_num_inputs(desc)
        num_outputs = acl.mdl.get_num_outputs(desc)
        print(f"  Inputs: {num_inputs}")
        for i in range(num_inputs):
            dtype = acl.mdl.get_input_data_type(desc, i)
            dims, _ = acl.mdl.get_input_dims(desc, i)
            print(f"    [{i}] dtype={dtype}, dims={dims['dims']}")
        print(f"  Outputs: {num_outputs}")
        for i in range(num_outputs):
            dtype = acl.mdl.get_output_data_type(desc, i)
            dims, _ = acl.mdl.get_output_dims(desc, i)
            print(f"    [{i}] dtype={dtype}, dims={dims['dims']}")

    def _create_dataset(self, inputs, model_desc):
        dataset = acl.mdl.create_dataset()
        buffers = []
        num_inputs = acl.mdl.get_num_inputs(model_desc)
        if len(inputs) != num_inputs:
             print(f"Warning: Input count mismatch. Model expects {num_inputs}, got {len(inputs)}")

        for i, data in enumerate(inputs):
            # Check and cast data type
            acl_dtype = acl.mdl.get_input_data_type(model_desc, i)
            target_dtype = self._get_numpy_dtype(acl_dtype)
            
            if data.dtype != target_dtype:
                # print(f"Input {i} dtype mismatch: {data.dtype} -> {target_dtype}")
                data = data.astype(target_dtype)

            # 确保数据是连续的且在内存中
            if not data.flags['C_CONTIGUOUS']:
                data = np.ascontiguousarray(data)
            
            ptr = acl.util.numpy_to_ptr(data)
            size = data.nbytes
            data_buffer = acl.create_data_buffer(ptr, size)
            acl.mdl.add_dataset_buffer(dataset, data_buffer)
            buffers.append(data_buffer) # Keep reference
        return dataset, buffers

    def _create_output_dataset(self, model_desc):
        dataset = acl.mdl.create_dataset()
        num = acl.mdl.get_num_outputs(model_desc)
        buffers = []
        dev_ptrs = []
        
        for i in range(num):
            size = acl.mdl.get_output_size_by_index(model_desc, i)
            dev_ptr, ret = acl.rt.malloc(size, 2) # ACL_MEM_MALLOC_HUGE_FIRST
            check_ret(ret, f"malloc output {i}")
            
            data_buffer = acl.create_data_buffer(dev_ptr, size)
            acl.mdl.add_dataset_buffer(dataset, data_buffer)
            buffers.append(data_buffer)
            dev_ptrs.append(dev_ptr)
            
        return dataset, buffers, dev_ptrs

    def _dev_to_host(self, dev_ptr, shape, dtype=np.float16):
        # 计算需要拷贝的字节数
        size = int(np.prod(shape) * np.dtype(dtype).itemsize)
        # 申请 Host 内存
        host_ptr, ret = acl.rt.malloc_host(size)
        check_ret(ret, "malloc host")
        
        # 拷贝 Device -> Host
        ret = acl.rt.memcpy(host_ptr, size, dev_ptr, size, 2) # 2: ACL_MEMCPY_DEVICE_TO_HOST
        check_ret(ret, "memcpy device to host")
        
        # 转为 Numpy
        data_bytes = acl.util.ptr_to_bytes(host_ptr, size)
        data_np = np.frombuffer(data_bytes, dtype=dtype).reshape(shape).copy()
        
        # 释放 Host 内存
        acl.rt.free_host(host_ptr)
        
        return data_np

    def _get_numpy_dtype(self, acl_dtype):
        if acl_dtype == 0: return np.float32
        if acl_dtype == 1: return np.float16
        if acl_dtype == 3: return np.int32
        if acl_dtype == 9: return np.int64
        print(f"Warning: Unknown ACL dtype {acl_dtype}, defaulting to float32")
        return np.float32

    def forward_first(self, input_ids, attention_mask):
        # Prepare inputs
        # input_ids: [1, seq_len], attention_mask: [1, seq_len]
        # position_ids: [1, seq_len] (if needed)
        if self.first_needs_position_ids:
            # 根据 attention_mask 生成正确的 position_ids
            # 只有 mask=1 的位置才有递增的 position，padding 位置保持为 0
            position_ids = np.zeros_like(attention_mask, dtype=np.int64)
            for i in range(attention_mask.shape[0]):
                valid_len = np.sum(attention_mask[i])
                position_ids[i, :valid_len] = np.arange(valid_len, dtype=np.int64)
            inputs = [input_ids, attention_mask, position_ids]
        else:
            inputs = [input_ids, attention_mask]
        
        input_dataset, input_buffers = self._create_dataset(inputs, self.first_desc)
        output_dataset, output_buffers, output_ptrs = self._create_output_dataset(self.first_desc)
        
        # Execute
        ret = acl.mdl.execute(self.first_model_id, input_dataset, output_dataset)
        check_ret(ret, "execute first model")
        
        # Get Logits (Output 0)
        logits_ptr = output_ptrs[0]
        logits_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.first_desc, 0))
        logits = self._dev_to_host(logits_ptr, (1, input_ids.shape[1], 151936), logits_dtype)

        # Get KV Cache (Output 1..N)
        present_key_values = []
        num_layers = (len(output_ptrs) - 1) // 2
        for i in range(num_layers):
            k_ptr = output_ptrs[1 + 2*i]
            v_ptr = output_ptrs[1 + 2*i + 1]
            # Shape: [1, 2, seq_len, 64]
            dims, ret = acl.mdl.get_output_dims(self.first_desc, 1 + 2*i)
            shape = tuple(dims['dims'])
            
            k_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.first_desc, 1 + 2*i))
            v_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.first_desc, 1 + 2*i + 1))
            
            k = self._dev_to_host(k_ptr, shape, k_dtype)
            v = self._dev_to_host(v_ptr, shape, v_dtype)
            present_key_values.append((k, v))

        # Cleanup (简化版，未释放 dataset)
        return logits, present_key_values

    def forward_next(self, input_ids, attention_mask, position_ids, past_key_values):
        # Prepare inputs
        if self.next_needs_position_ids:
            inputs = [input_ids, attention_mask, position_ids]
        else:
            inputs = [input_ids, attention_mask]
        for layer_past in past_key_values:
            inputs.extend(layer_past)
            
        input_dataset, input_buffers = self._create_dataset(inputs, self.next_desc)
        output_dataset, output_buffers, output_ptrs = self._create_output_dataset(self.next_desc)
        
        # Execute
        ret = acl.mdl.execute(self.next_model_id, input_dataset, output_dataset)
        check_ret(ret, "execute next model")
        
        # Get Outputs
        logits_ptr = output_ptrs[0]
        logits_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.next_desc, 0))
        logits = self._dev_to_host(logits_ptr, (1, 1, 151936), logits_dtype)
        
        present_key_values = []
        num_layers = (len(output_ptrs) - 1) // 2
        for i in range(num_layers):
            k_ptr = output_ptrs[1 + 2*i]
            v_ptr = output_ptrs[1 + 2*i + 1]
            dims, ret = acl.mdl.get_output_dims(self.next_desc, 1 + 2*i)
            shape = tuple(dims['dims'])
            
            k_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.next_desc, 1 + 2*i))
            v_dtype = self._get_numpy_dtype(acl.mdl.get_output_data_type(self.next_desc, 1 + 2*i + 1))
            
            k = self._dev_to_host(k_ptr, shape, k_dtype)
            v = self._dev_to_host(v_ptr, shape, v_dtype)
            present_key_values.append((k, v))
            
        return logits, present_key_values

    def release(self):
        acl.finalize()

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 chat_om.py <first_model> <next_model> [tokenizer_path]")
        sys.exit(1)

    first_path = sys.argv[1]
    next_path = sys.argv[2]
    tokenizer_path = sys.argv[3] if len(sys.argv) > 3 else "./Qwen2.5-0.5B-Instruct"

    print("Loading Tokenizer...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
    except Exception as e:
        print(f"Failed to load tokenizer: {e}")
        print("Please ensure 'transformers' is installed and tokenizer path is correct.")
        sys.exit(1)

    llm = AscendLLM(first_path, next_path)
    llm.init_resource()
    llm.load_models()

    history = []
    
    print("\n" + "="*20 + " Chat with Qwen2.5-0.5B (Ascend) " + "="*20)
    print("Type 'exit' to quit.\n")

    while True:
        query = input("User: ")
        if query.strip() == "exit":
            break
            
        # 简单处理：不带 history，单轮对话
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": query}
        ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = tokenizer([text], return_tensors="np")
        
        input_ids = model_inputs.input_ids.astype(np.int64)
        attention_mask = model_inputs.attention_mask.astype(np.int64)
        
        seq_len = input_ids.shape[1]
        print(f"Assistant: ", end="", flush=True)
        
        start_time = time.time()
        
        # First Inference
        # 注意：这里需要 padding 到模型导出的 seq_len (128)
        # 为简化演示，假设输入 < 128，并手动 padding
        EXPORT_SEQ_LEN = 128
        if seq_len > EXPORT_SEQ_LEN:
            print(f"\nError: Input length {seq_len} exceeds exported length {EXPORT_SEQ_LEN}")
            continue
            
        pad_len = EXPORT_SEQ_LEN - seq_len
        padded_input_ids = np.pad(input_ids, ((0,0), (0, pad_len)), 'constant')
        padded_mask = np.pad(attention_mask, ((0,0), (0, pad_len)), 'constant')
        
        logits, past_key_values = llm.forward_first(padded_input_ids, padded_mask)
        
        # Greedy Search for next token
        next_token_id = np.argmax(logits[0, seq_len-1, :])
        generated_ids = [next_token_id]
        print(tokenizer.decode([next_token_id]), end="", flush=True)
        
        # Loop for generation
        current_len = seq_len
        while current_len < EXPORT_SEQ_LEN:
            # Prepare inputs for Next
            next_input_ids = np.array([[next_token_id]], dtype=np.int64)
            
            # Update Attention Mask
            # Next model mask: [1, past_len + 1]
            # Current past_len = current_len
            # Mask should be 1s for [0, current_len]
            next_mask = np.ones((1, current_len + 1), dtype=np.int64)
            # Pad to EXPORT_SEQ_LEN + 1 if needed, but here export uses fixed past_len=128
            # Actually Next model exported with past_len=128, so mask is [1, 129]
            # We need to pad mask to 129
            padded_next_mask = np.pad(next_mask, ((0,0), (0, 129 - (current_len + 1))), 'constant')
            
            # Prepare KV Cache
            # First output KV: [1, 2, 128, 64] (padded)
            # Next input KV: [1, 2, 128, 64]
            # They match!
            
            # Flatten KV for input
            flat_past = []
            for k, v in past_key_values:
                flat_past.extend([k, v])
            
            # Position IDs for Next
            # Current position is current_len
            next_position_ids = np.array([[current_len]], dtype=np.int64)

            logits, present_key_values = llm.forward_next(next_input_ids, padded_next_mask, next_position_ids, flat_past)
            
            next_token_id = np.argmax(logits[0, 0, :])
            generated_ids.append(next_token_id)
            token_str = tokenizer.decode([next_token_id])
            print(token_str, end="", flush=True)
            
            if next_token_id == tokenizer.eos_token_id:
                break
                
            # Update KV Cache and Length
            past_key_values = present_key_values
            current_len += 1
            
        print(f"\nFirst Token Latency: {time.time() - start_time:.4f} s")
        
    llm.release()

if __name__ == "__main__":
    main()
