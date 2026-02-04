import os
import sys
from http import HTTPStatus

# 尝试导入 settings 中的配置
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.settings import global_settings

try:
    import dashscope  # type: ignore
except Exception:
    dashscope = None

def test_local_llm():
    """测试本地 Ascend LLM 引擎"""
    print("="*50)
    print("本地 LLM 引擎测试")
    print("="*50)
    
    from models.llm_model import LLMModel
    
    print("\n初始化 LLM 引擎（首次会较慢，请耐心等待）...")
    try:
        llm = LLMModel()
        llm.clear_messages()
        
        # 测试问题
        test_queries = [
            "你好，请做个自我介绍",
            "今天天气怎么样",
            "1+1等于几"
        ]
        
        for query in test_queries:
            print(f"\n{'='*50}")
            print(f"问题: {query}")
            print(f"回答: ", end="", flush=True)
            
            # 流式生成
            full_response = ""
            for chunk in llm.get_LLM_response_stream(query):
                print(chunk, end="", flush=True)
                full_response += chunk
            print()  # 换行
            
            if not full_response.strip():
                print("⚠️ 警告：模型返回为空！")
        
        print(f"\n{'='*50}")
        print("✅ 本地 LLM 测试通过！")
        return True
        
    except Exception as e:
        print(f"\n❌ 本地 LLM 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_llm():
    print("="*50)
    print("LLM Debug Tool")
    print("="*50)
    
    engine = getattr(global_settings, "LLM_ENGINE", "").strip().lower()
    
    if engine == "local_ascend_qwen_om":
        print("当前 LLM_ENGINE=local_ascend_qwen_om（本地离线）")
        print("开始测试本地 LLM 引擎...\n")
        return test_local_llm()

    if dashscope is None:
        print("未安装 dashscope。请执行：pip install -r requirements-cloud.txt")
        return

    # 1. Check Key
    api_key = getattr(dashscope, "api_key", None)
    print(f"Current dashscope.api_key: {api_key}")
    
    if not api_key:
        print("Error: API Key is empty or None!")
        return
    
    if api_key.startswith("sk-") and len(api_key) > 10:
        print("Key format looks valid (starts with sk-).")
    else:
        print("Warning: Key format looks suspicious.")

    # 2. Check Environment Variable
    env_key = os.getenv("DASHSCOPE_API_KEY")
    print(f"Environment Variable DASHSCOPE_API_KEY: {env_key}")
    
    # 3. Try a simple call
    print("\nAttempting to call qwen-turbo...")
    try:
        messages = [{'role': 'user', 'content': 'Hello, are you working?'}]
        response = dashscope.Generation.call(
            model='qwen-turbo',
            messages=messages,
            result_format='message',
        )
        
        if response.status_code == HTTPStatus.OK:
            print("SUCCESS! API Key is working.")
            print(f"Response: {response.output.choices[0]['message']['content']}")
        else:
            print(f"FAILED! Status Code: {response.status_code}")
            print(f"Error Code: {response.code}")
            print(f"Error Message: {response.message}")
            
    except Exception as e:
        print(f"Exception occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_llm()

