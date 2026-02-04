#!/usr/bin/env python3
"""Qwen2.5-0.5B Chat 推理程序 - CANN 8.0"""

import sys
import time
import numpy as np
import acl
from transformers import AutoTokenizer

def check_ret(ret, message):
    if ret != 0:
        print(f"Error: {message} failed ret={ret}")
        sys.exit(1)

class QwenChat:
    def __init__(self, model_path, tokenizer_path, device_id=0):
        self.device_id = device_id
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.max_seq_len = 1024
        
        # ACL 资源
        self.context = None
        self.model_id = None
        self.model_desc = None
        
        # KV Cache - Device 侧 buffer（常驻显存）
        self.kv_cache_dev_ptr = None  # Device 侧 KV cache
        self.kv_cache_size = 1 * 1024 * 96 * 64 * 2  # [1, 1024, 96, 64] fp16 = 2 bytes
        self.current_pos = 0

    def init_acl(self):
        ret = acl.init()
        check_ret(ret, "acl.init")
        ret = acl.rt.set_device(self.device_id)
        check_ret(ret, "acl.rt.set_device")
        self.context, ret = acl.rt.create_context(self.device_id)
        check_ret(ret, "acl.rt.create_context")
        print("✅ ACL initialized")

    def load_model(self):
        self.model_id, ret = acl.mdl.load_from_file(self.model_path)
        check_ret(ret, f"load model")
        self.model_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self.model_desc, self.model_id)
        check_ret(ret, "get model desc")
        
        # 分配 Device 侧 KV cache buffer
        self.kv_cache_dev_ptr, ret = acl.rt.malloc(self.kv_cache_size, 2)  # ACL_MEM_MALLOC_HUGE_FIRST
        check_ret(ret, "malloc kv cache")
        
        # 初始化为 0
        ret = acl.rt.memset(self.kv_cache_dev_ptr, self.kv_cache_size, 0, self.kv_cache_size)
        check_ret(ret, "memset kv cache")
        
        print("✅ Model loaded with Device-side KV cache")

    def load_tokenizer(self):
        self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_path, trust_remote_code=True)
        print("✅ Tokenizer loaded")

    def _create_input_dataset(self, input_id, attention_mask, position_id):
        """创建输入数据集"""
        dataset = acl.mdl.create_dataset()
        keep_alive = []  # 用于防止 bytes 对象被垃圾回收
        
        # Input 0: input_ids [1, 1] int64
        input_id_arr = np.array([[input_id]], dtype=np.int64)
        input_bytes = input_id_arr.tobytes()  # 1. 先赋值给变量
        keep_alive.append(input_bytes)        # 2. 加入保活列表
        ptr = acl.util.bytes_to_ptr(input_bytes) # 3. 获取指针
        buf = acl.create_data_buffer(ptr, input_id_arr.nbytes)
        acl.mdl.add_dataset_buffer(dataset, buf)
        
        # Input 1: attention_mask [1, 1025] int64
        mask_arr = attention_mask.astype(np.int64)
        if not mask_arr.flags['C_CONTIGUOUS']:
            mask_arr = np.ascontiguousarray(mask_arr)
        mask_bytes = mask_arr.tobytes()
        keep_alive.append(mask_bytes)
        ptr = acl.util.bytes_to_ptr(mask_bytes)
        buf = acl.create_data_buffer(ptr, mask_arr.nbytes)
        acl.mdl.add_dataset_buffer(dataset, buf)
        
        # Input 2: position_ids [1, 1] int64
        pos_arr = np.array([[position_id]], dtype=np.int64)
        pos_bytes = pos_arr.tobytes()
        keep_alive.append(pos_bytes)
        ptr = acl.util.bytes_to_ptr(pos_bytes)
        buf = acl.create_data_buffer(ptr, pos_arr.nbytes)
        acl.mdl.add_dataset_buffer(dataset, buf)
        
        # Input 3: kv_cache [1, 1024, 96, 64] fp16 - 使用 Device 侧 buffer
        # kv_cache 是 device 指针，不需要 python bytes 保活
        buf = acl.create_data_buffer(self.kv_cache_dev_ptr, self.kv_cache_size)
        acl.mdl.add_dataset_buffer(dataset, buf)
        
        return dataset, keep_alive  # 返回 dataset 和保活列表
    
    def _create_output_dataset(self):
        """创建输出数据集"""
        dataset = acl.mdl.create_dataset()
        output_ptrs = []
        
        for i in range(2):  # 2个输出
            size = acl.mdl.get_output_size_by_index(self.model_desc, i)
            ptr, ret = acl.rt.malloc(size, 2)
            check_ret(ret, f"malloc output {i}")
            buf = acl.create_data_buffer(ptr, size)
            acl.mdl.add_dataset_buffer(dataset, buf)
            output_ptrs.append(ptr)
        
        return dataset, output_ptrs

    def _dev_to_host(self, dev_ptr, shape, dtype):
        """Device 内存复制到 Host"""
        size = int(np.prod(shape) * np.dtype(dtype).itemsize)
        host_ptr, ret = acl.rt.malloc_host(size)
        check_ret(ret, "malloc host")
        ret = acl.rt.memcpy(host_ptr, size, dev_ptr, size, 2)
        check_ret(ret, "memcpy")
        data_bytes = acl.util.ptr_to_bytes(host_ptr, size)
        data_np = np.frombuffer(data_bytes, dtype=dtype).reshape(shape).copy()
        acl.rt.free_host(host_ptr)
        return data_np

    def forward(self, token_id):
        """单步推理"""
        # 准备 attention_mask [1, 1025]
        # 注意：这里保留之前的掩码逻辑修复
        attention_mask = np.ones((1, self.max_seq_len + 1), dtype=np.int64)
        
        # 【逻辑修复】: 确保当前位置 current_pos 是 1，只 Mask 掉未来的
        if self.current_pos + 1 < self.max_seq_len:
            attention_mask[0, self.current_pos + 1 : self.max_seq_len] = 0
            
        # 准备输入
        # 【内存修复】: 接收 keep_alive 列表
        input_dataset, keep_alive = self._create_input_dataset(
            token_id, 
            attention_mask, 
            self.current_pos
        )
        
        # 准备输出
        output_dataset, output_ptrs = self._create_output_dataset()
        
        # 执行
        ret = acl.mdl.execute(self.model_id, input_dataset, output_dataset)
        check_ret(ret, "execute")
        
        # 读取 logits
        logits = self._dev_to_host(output_ptrs[0], (1, 1, 151936), np.float32)
        
        # 更新 Device 侧 KV cache
        offset = self.current_pos * 96 * 64 * 2
        new_kv_size = 1 * 1 * 96 * 64 * 2
        
        if self.current_pos < self.max_seq_len:
            ret = acl.rt.memcpy(
                self.kv_cache_dev_ptr + offset,
                new_kv_size,
                output_ptrs[1],
                new_kv_size,
                4 
            )
            check_ret(ret, "update kv cache")
        
        # 递增位置
        self.current_pos += 1
        
        # 清理资源
        for ptr in output_ptrs:
            acl.rt.free(ptr)
        acl.mdl.destroy_dataset(output_dataset)
        acl.mdl.destroy_dataset(input_dataset) # 销毁 dataset
        
        # keep_alive 列表在这里随着函数结束而被销毁，
        # 但此时 execute 已经执行完毕，内存已经使用完了，所以是安全的。
        del keep_alive 
        
        return logits  # 【修复】forward 函数需要返回 logits

    def generate(self, prompt, max_new_tokens=256):  # 【修复】补全函数定义
        """生成回复"""
        # 重置 Device 侧 KV cache  # 【修复】添加 # 号
        ret = acl.rt.memset(self.kv_cache_dev_ptr, self.kv_cache_size, 0, self.kv_cache_size)
        check_ret(ret, "reset kv cache")
        # 构造消息
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        # Tokenize
        input_ids = self.tokenizer.encode(text)
        
        # 初始化 KV cache
        self.kv_cache = np.zeros((1, self.max_seq_len, 96, 64), dtype=np.float16)
        self.current_pos = 0
        
        print(f"\n{'='*60}")
        print(f"User: {prompt}")
        print(f"Assistant: ", end="", flush=True)
        
        # Prefill 阶段（逐个处理输入tokens）
        prefill_start = time.time()
        for token_id in input_ids:
            if self.current_pos >= self.max_seq_len:
                print("\n[Warning] Reached max sequence length during prefill")
                break
            logits = self.forward(token_id)
        
        prefill_time = time.time() - prefill_start
        
        # Decode 阶段（生成新tokens）
        generated_tokens = []
        decode_start = time.time()
        
        next_token = np.argmax(logits)
        
        # 调试：显示第一个生成的 token
        if next_token == self.tokenizer.eos_token_id:
            print(f"\n[Debug] First token is EOS (id={next_token})")
        
        for step in range(max_new_tokens):
            if next_token == self.tokenizer.eos_token_id:
                break
            
            if self.current_pos >= self.max_seq_len:
                print("\n[Warning] Reached max sequence length")
                break
            
            # 输出token
            token_str = self.tokenizer.decode([next_token])
            print(token_str, end="", flush=True)
            generated_tokens.append(next_token)
            
            # Debug: 每10步显示一次状态
            if step > 0 and step % 10 == 0:
                print(f"\n[Debug] Step {step}: pos={self.current_pos}, token_id={next_token}")
            
            # 生成下一个token
            logits = self.forward(next_token)
            
            # Debug: 检查 logits 是否合理
            if step == 0:
                print(f"\n[Debug] Logits stats: min={logits.min():.2f}, max={logits.max():.2f}, mean={logits.mean():.2f}")
            
            next_token = np.argmax(logits)
            
            # Debug: 检测重复
            if len(generated_tokens) >= 3 and generated_tokens[-1] == generated_tokens[-2] == generated_tokens[-3]:
                print(f"\n[Warning] Detected repetition! Token {next_token} repeated.")
                break
        
        decode_time = time.time() - decode_start
        
        # 统计信息
        total_time = prefill_time + decode_time
        print(f"\n{'='*60}")
        print(f"📊 Statistics:")
        print(f"  Prefill tokens: {len(input_ids)}, time: {prefill_time:.2f}s ({len(input_ids)/prefill_time:.1f} tok/s)")
        print(f"  Decode tokens:  {len(generated_tokens)}, time: {decode_time:.2f}s ({len(generated_tokens)/decode_time:.1f} tok/s)")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  First token latency: {prefill_time:.2f}s")
        
        return self.tokenizer.decode(generated_tokens)

    def release(self):
        """释放资源"""
        if self.kv_cache_dev_ptr:
            acl.rt.free(self.kv_cache_dev_ptr)
            print("✅ KV cache freed")
        if self.model_id:
            acl.mdl.unload(self.model_id)
            print("✅ Model unloaded")
        if self.context:
            acl.rt.destroy_context(self.context)
            print("✅ Context destroyed")
        acl.rt.reset_device(self.device_id)
        acl.finalize()
        print("✅ ACL finalized")

def main():
    try:
        if len(sys.argv) < 2:
            print("Usage: python3 chat_qwen.py <model.om> [tokenizer_path]")
            sys.exit(1)

        model_path = sys.argv[1]
        tokenizer_path = sys.argv[2] if len(sys.argv) > 2 else "./qwen_tokenizer"

        print("🚀 Qwen2.5-0.5B Chat on Ascend NPU")
        print("="*60)
        print(f"Model: {model_path}")
        print(f"Tokenizer: {tokenizer_path}")
        print()
        
        chat = QwenChat(model_path, tokenizer_path)
        print("Initializing ACL...")
        chat.init_acl()
        print("Loading model...")
        chat.load_model()
        print("Loading tokenizer...")
        chat.load_tokenizer()
        
        print("\n💬 Chat started. Type 'exit' to quit.\n")
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    while True:
        try:
            user_input = input("\n👤 You: ")
            if user_input.strip().lower() == 'exit':
                break
            
            if not user_input.strip():
                continue
            
            chat.generate(user_input, max_new_tokens=256)
            
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    chat.release()
    print("\n👋 Goodbye!")

if __name__ == "__main__":
    main()
