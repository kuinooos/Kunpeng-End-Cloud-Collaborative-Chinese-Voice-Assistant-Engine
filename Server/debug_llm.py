import os
import sys
import dashscope
from http import HTTPStatus

# 尝试导入 settings 中的配置
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.settings import global_settings

def test_llm():
    print("="*50)
    print("LLM API Key Debug Tool")
    print("="*50)
    
    # 1. Check Key
    api_key = dashscope.api_key
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
