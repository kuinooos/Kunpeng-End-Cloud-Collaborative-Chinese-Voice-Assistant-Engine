import time
import os
from http import HTTPStatus
import dashscope

# 请替换为您的真实 API Key，或者设置环境变量 DASHSCOPE_API_KEY
# os.environ["DASHSCOPE_API_KEY"] = "YOUR_API_KEY"

def benchmark_dashscope(model="qwen-turbo", loops=10):
    print(f"Benchmarking DashScope model: {model}")
    print(f"Loops: {loops}")
    
    prompt = "你好，请介绍一下你自己。"
    
    latencies = []
    tokens_generated = []
    
    for i in range(loops):
        start_time = time.time()
        try:
            response = dashscope.Generation.call(
                model=model,
                prompt=prompt,
                result_format='message',  # set the result to be "message" format.
            )
            end_time = time.time()
            
            if response.status_code == HTTPStatus.OK:
                latency = end_time - start_time
                # 估算生成的 token 数 (DashScope 返回 usage)
                usage = response.usage
                output_tokens = usage['output_tokens']
                
                latencies.append(latency)
                tokens_generated.append(output_tokens)
                
                tps = output_tokens / latency
                print(f"Loop {i+1}: {latency:.2f}s, {output_tokens} tokens, TPS: {tps:.2f}")
            else:
                print(f"Request failed: {response.code}, {response.message}")
        except Exception as e:
            print(f"Error: {e}")

    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        total_tokens = sum(tokens_generated)
        total_time = sum(latencies)
        avg_tps = total_tokens / total_time
        
        print(f"\n{'='*40}")
        print(f"Average Request Latency: {avg_latency:.2f} s")
        print(f"Average Generation Speed: {avg_tps:.2f} tokens/s")
        print(f"{'='*40}\n")

if __name__ == "__main__":
    # 确保安装了 dashscope sdk: pip install dashscope
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("Please set DASHSCOPE_API_KEY environment variable.")
    else:
        benchmark_dashscope(model="qwen-plus", loops=5)
