# Ascend 310 NPU 跑 LLM（CANN/ACL）PoC

目标：在不改动现有 `Server/` 的前提下，把 **LLM 推理**单独验证跑通：

- 环境：Orange Pi Kunpeng Pro（4核 ARM + 16GB + Ascend 310 NPU）
- 方式：**CANN/ACL + 模型转换 + LLM 推理框架/服务**
- 不使用：GGUF / llama.cpp

> 说明：Ascend 上跑 LLM 通常不是“把 HF 权重直接丢给 ACL”这么简单。
> 正确做法是：选择一个 Ascend 侧的 LLM 推理框架（通常自带模型转换工具），将模型转换成该框架可跑的格式，然后启动服务/推理。

---

## 0. 你需要准备的三样东西

1) **CANN 工具链与驱动**（板子侧已安装/可安装）
2) **Python ACL 能用**（`import acl` 能成功）
3) **一个“Ascend LLM 推理框架/服务”**（例如官方/生态提供的 LLM Serving）

这一套 PoC 文件夹先把 1/2 做成可执行的自检与冒烟测试；第 3 步我会按你板子上能用的框架再补齐“模型转换 + 启动服务 + 压测”。

---

## 1) 环境自检（板子上跑）

进入该目录后按顺序执行：

```bash
cd /path/to/AIChat_demo/llm_ascend_poc
bash scripts/00_collect_sysinfo.sh
python3 scripts/01_acl_smoke_test.py
```

如果出现：`acl.init()==0` 但 `get_device_count ret!=0` / `set_device` 卡住

```bash
cd /path/to/AIChat_demo/llm_ascend_poc
sudo bash scripts/03_collect_npu_logs.sh
```

脚本会在 `/tmp` 下生成一个目录和一个 `tar.gz` 诊断包，并在终端打印路径。

预期：
- `npu-smi info` 能看到 310 设备
- `atc --version` / `ascend-toolkit` 相关命令存在（有则更好）
- `python3 scripts/01_acl_smoke_test.py` 输出 `[OK]` 并正常 init/finalize

---

## 2) 模型转换与服务部署（你确认框架后我补“可直接跑”的命令）

LLM 上 NPU 的关键是：**选定推理框架/服务 → 用它的 converter 把模型转成可跑格式 → 启动服务**。

你需要告诉我你准备使用哪一种（或板子上已经装了哪一种）：
- 选项A：你已经有 Ascend 的 LLM Serving/推理框架（提供模型转换工具）
- 选项B：你只有 CANN/ACL（那就先确认是否有官方示例/工具链，通常仍建议用“框架”而不是手撸算子）

请回复两条信息（我就能把 `notes/02_model_convert_and_serve.md` 补成可执行版）：
1) 你的 CANN 版本（`npu-smi info` / 工具链版本）
2) 你想跑的模型来源：HF 的 Qwen2.5-3B-Instruct（fp16/bf16）？还是已有的某个 checkpoint？

---

## 3) 最终对接方式（建议）

即使你最终把 LLM 上 NPU，我建议依旧把它作为**独立服务**对外提供接口（HTTP/gRPC，最好 OpenAI 兼容）。
这样现有 `Server/` 只需要“换一个 URL”，业务逻辑不用重写。

这个目录里后面会放一个 `scripts/10_openai_compat_client.py` 用来验证服务是否满足 `/v1/chat/completions`（含 stream）。
