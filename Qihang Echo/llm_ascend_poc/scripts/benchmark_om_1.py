import time
import acl
import sys
import os

# 错误码检查
def check_ret(ret, message):
    if ret != 0:
        print(f"Error: {message} failed ret={ret}")
        sys.exit(1)

class AscendBenchmark:
    def __init__(self, device_id=0):
        self.device_id = device_id
        self.context = None
        self.stream = None
        self.model_id = None
        self.model_desc = None
        self.input_dataset = None
        self.output_dataset = None
        self.input_buffers = []
        self.output_buffers = []

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

    def load_model(self, model_path):
        self.model_id, ret = acl.mdl.load_from_file(model_path)
        check_ret(ret, f"acl.mdl.load_from_file {model_path}")
        self.model_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self.model_desc, self.model_id)
        check_ret(ret, "acl.mdl.get_desc")
        print(f"[Load] Model {model_path} loaded successfully.")

    def _allocate_dataset(self, is_input):
        dataset = acl.mdl.create_dataset()
        num = acl.mdl.get_num_inputs(self.model_desc) if is_input else acl.mdl.get_num_outputs(self.model_desc)
        buffers = []
        
        for i in range(num):
            if is_input:
                size = acl.mdl.get_input_size_by_index(self.model_desc, i)
            else:
                size = acl.mdl.get_output_size_by_index(self.model_desc, i)
            
            dev_ptr, ret = acl.rt.malloc(size, 2) # 2: ACL_MEM_MALLOC_HUGE_FIRST
            check_ret(ret, f"acl.rt.malloc index {i}")
            
            data_buffer = acl.create_data_buffer(dev_ptr, size)
            acl.mdl.add_dataset_buffer(dataset, data_buffer)
            buffers.append(dev_ptr)
            
        return dataset, buffers

    def prepare_dummy_data(self):
        # 自动根据模型描述分配输入输出内存
        self.input_dataset, self.input_buffers = self._allocate_dataset(is_input=True)
        self.output_dataset, self.output_buffers = self._allocate_dataset(is_input=False)
        print("[Data] Dummy input/output buffers allocated.")

    def run_benchmark(self, loops=100):
        print(f"[Bench] Running warm-up...")
        for _ in range(5):
            ret = acl.mdl.execute(self.model_id, self.input_dataset, self.output_dataset)
            check_ret(ret, "acl.mdl.execute warm-up")

        print(f"[Bench] Running {loops} loops inference...")
        start_time = time.time()
        for i in range(loops):
            ret = acl.mdl.execute(self.model_id, self.input_dataset, self.output_dataset)
            if ret != 0:
                print(f"Inference failed at loop {i}")
                break
        end_time = time.time()
        
        total_time = end_time - start_time
        avg_time = total_time / loops
        tps = 1 / avg_time
        
        print(f"\n{'='*40}")
        print(f"Total Time: {total_time:.4f} s")
        print(f"Avg Latency: {avg_time*1000:.2f} ms")
        print(f"Throughput:  {tps:.2f} tokens/s")
        print(f"{'='*40}\n")

    def release_resource(self):
        # 简化释放流程，实际工程需逐个释放 buffer 和 dataset
        if self.model_id:
            acl.mdl.unload(self.model_id)
        if self.stream:
            acl.rt.destroy_stream(self.stream)
        if self.context:
            acl.rt.destroy_context(self.context)
        acl.rt.reset_device(self.device_id)
        acl.finalize()
        print("[Exit] Resources released.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 benchmark_om.py <om_model_path> [loops]")
        sys.exit(1)
        
    model_path = sys.argv[1]
    loops = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    
    if not os.path.exists(model_path):
        print(f"File not found: {model_path}")
        sys.exit(1)

    bench = AscendBenchmark()
    try:
        bench.init_resource()
        bench.load_model(model_path)
        bench.prepare_dummy_data()
        bench.run_benchmark(loops)
    finally:
        bench.release_resource()
