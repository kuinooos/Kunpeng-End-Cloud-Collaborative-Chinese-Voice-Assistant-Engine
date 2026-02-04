# 02. 模型转换 + 启动 LLM 服务（待你确认框架后补全）

你已经明确：不走 GGUF/llama.cpp，要走 **CANN/ACL + 模型转换 + Ascend LLM 推理框架/服务**。

这一页我先把“正确的流程框架”写清楚，等你把板子上的可用组件确认后，我再把每一步补成可直接复制执行的命令。

---

## 目标

- 输入：Qwen2.5-3B-Instruct（HF 权重，例如 fp16/bf16/safetensors）
- 输出：Ascend 310 上能跑的推理格式（取决于框架，可能是 OM/分片/专用格式）
- 最终：启动一个 LLM 推理服务（建议 OpenAI 兼容 `/v1/chat/completions`），便于后续对接现有对话系统

---

## Step A：确认环境与版本矩阵

先运行：

```bash
bash scripts/00_collect_sysinfo.sh
python3 scripts/01_acl_smoke_test.py
```

你把输出里这几行贴给我：
- `npu-smi info` 关键段（设备型号/驱动）
- `atc --version`（若有）
- Python 版本
- `import acl` 是否成功

---

## Step B：选择 LLM 推理框架/服务（关键决策）

原因：LLM 不建议“手写 ACL 调算子”——工作量巨大、很难稳定。
正确做法是用一个现成的 Ascend LLM 推理框架，它一般会提供：
- 权重转换/编译工具（把 HF checkpoint 转成可跑格式）
- KV Cache/并行策略/算子融合等优化
- Serving（HTTP/gRPC）

你告诉我你能用哪一个（或你希望用哪一个），我就按它写后续步骤：
- 方案1：你已有的 Ascend LLM Serving（官方/厂商/课程提供）
- 方案2：你只有 CANN（那就先装对应的 LLM 框架，再走转换与 serving）

---

## Step C：模型下载（通用）

建议在 PC 侧下载 HF 权重再拷贝到板子（避免板子下载慢/断）。
模型目录建议结构：

```
/opt/models/qwen2.5-3b-instruct/
  config.json
  tokenizer.json
  tokenizer.model (如果有)
  *.safetensors
```

---

## Step D：模型转换/编译（由框架决定）

不同框架的转换命令差异很大，这一步需要你先确认“框架名字/版本”。
我会把：
- converter 命令
- 输入输出目录
- 常见坑（tokenizer、rope、dtype、max_seq_len、batch、kv cache）
都写成一键脚本。

---

## Step E：启动服务 & 验证

最终验证目标：
- `curl http://127.0.0.1:PORT/v1/chat/completions ...` 能出结果
- 支持 `stream=true`（对话体验更好）
- 输出 tok/s / 首 token 延迟

