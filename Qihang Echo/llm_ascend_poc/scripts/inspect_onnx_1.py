import onnx

def inspect_onnx(model_path):
    print(f"Inspecting {model_path}...")
    try:
        model = onnx.load(model_path, load_external_data=False)
        print("Inputs:")
        for input in model.graph.input:
            shape = []
            for d in input.type.tensor_type.shape.dim:
                if d.dim_value:
                    shape.append(d.dim_value)
                elif d.dim_param:
                    shape.append(d.dim_param)
                else:
                    shape.append("?")
            print(f"  {input.name}: {shape}")
    except Exception as e:
        print(f"Error loading {model_path}: {e}")

inspect_onnx("d:/01_all_series_quickstart/Demo4Echo/AIChat_demo/llm_ascend_poc/Qwen2.5-onnx/qwen25_first.onnx")
inspect_onnx("d:/01_all_series_quickstart/Demo4Echo/AIChat_demo/llm_ascend_poc/Qwen2.5-onnx/qwen25_next.onnx")
