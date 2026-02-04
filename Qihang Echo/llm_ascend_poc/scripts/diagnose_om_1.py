#!/usr/bin/env python3
"""诊断 OM 模型加载问题"""

import os
import sys
import acl

def check_ret(ret, message):
    if ret != 0:
        print(f"❌ Error: {message} failed, ret={ret}")
        return False
    print(f"✅ {message} success")
    return True

def diagnose():
    model_path = sys.argv[1] if len(sys.argv) > 1 else "./qwen2.5_0.5b_chat.om"
    
    print("="*50)
    print("OM Model Diagnostic Tool")
    print("="*50)
    
    # 1. 检查文件
    print(f"\n[1] Checking file: {model_path}")
    if not os.path.exists(model_path):
        print(f"❌ File not found: {model_path}")
        return
    
    file_size = os.path.getsize(model_path)
    print(f"✅ File exists, size: {file_size / 1024 / 1024:.2f} MB")
    
    # 2. 初始化 ACL
    print(f"\n[2] Initializing ACL...")
    ret = acl.init()
    if not check_ret(ret, "acl.init"):
        return
    
    ret = acl.rt.set_device(0)
    if not check_ret(ret, "acl.rt.set_device"):
        acl.finalize()
        return
    
    context, ret = acl.rt.create_context(0)
    if not check_ret(ret, "acl.rt.create_context"):
        acl.finalize()
        return
    
    # 3. 尝试加载模型
    print(f"\n[3] Loading model...")
    print(f"    Model path: {os.path.abspath(model_path)}")
    
    model_id, ret = acl.mdl.load_from_file(model_path)
    if ret != 0:
        print(f"❌ Failed to load model, ret={ret}")
        print(f"\nPossible causes:")
        print(f"  1. Model format mismatch (check ATC version)")
        print(f"  2. Model corrupted during transfer")
        print(f"  3. Incompatible SOC version")
        print(f"  4. Insufficient memory")
        
        # 尝试获取更多信息
        print(f"\n[Debug] ACL Runtime Info:")
        try:
            version = acl.get_version()
            print(f"  ACL Version: {version}")
        except:
            print(f"  Cannot get ACL version")
        
        acl.rt.destroy_context(context)
        acl.finalize()
        return
    
    print(f"✅ Model loaded, ID={model_id}")
    
    # 4. 获取模型描述
    print(f"\n[4] Getting model description...")
    model_desc = acl.mdl.create_desc()
    ret = acl.mdl.get_desc(model_desc, model_id)
    if not check_ret(ret, "acl.mdl.get_desc"):
        acl.mdl.unload(model_id)
        acl.rt.destroy_context(context)
        acl.finalize()
        return
    
    # 5. 显示模型信息
    print(f"\n[5] Model Information:")
    num_inputs = acl.mdl.get_num_inputs(model_desc)
    num_outputs = acl.mdl.get_num_outputs(model_desc)
    
    print(f"  Number of inputs: {num_inputs}")
    for i in range(num_inputs):
        dtype = acl.mdl.get_input_data_type(model_desc, i)
        size = acl.mdl.get_input_size_by_index(model_desc, i)
        dims, _ = acl.mdl.get_input_dims(model_desc, i)
        print(f"    Input[{i}]: dtype={dtype}, size={size}, shape={dims['dims']}")
    
    print(f"  Number of outputs: {num_outputs}")
    for i in range(min(3, num_outputs)):
        dtype = acl.mdl.get_output_data_type(model_desc, i)
        size = acl.mdl.get_output_size_by_index(model_desc, i)
        dims, _ = acl.mdl.get_output_dims(model_desc, i)
        print(f"    Output[{i}]: dtype={dtype}, size={size}, shape={dims['dims']}")
    if num_outputs > 3:
        print(f"    ... and {num_outputs - 3} more outputs")
    
    print(f"\n✅ All checks passed! Model is valid.")
    
    # 清理
    acl.mdl.unload(model_id)
    acl.rt.destroy_context(context)
    acl.finalize()

if __name__ == "__main__":
    diagnose()
