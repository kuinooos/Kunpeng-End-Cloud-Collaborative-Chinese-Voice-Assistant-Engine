#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""OpenAI 兼容接口连通性测试（用于验证你的 NPU LLM Serving 是否可对接）。

用法：
  python3 scripts/10_openai_compat_client.py --base-url http://127.0.0.1:8000 --model qwen2.5-3b --stream

说明：
- 该脚本不依赖 requests，使用 urllib，便于在板子上最小环境运行。
- 期望服务支持：POST /v1/chat/completions
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def _post_json(url: str, payload: dict, api_key: str | None, timeout_s: int):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=timeout_s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    url = base + "/v1/chat/completions"

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "你是一个简洁的中文助手。"},
            {"role": "user", "content": "用一句话解释什么是尾延迟（P99）。"},
        ],
        "stream": bool(args.stream),
    }

    print("[INFO] POST", url)
    t0 = time.time()

    if not args.stream:
        with _post_json(url, payload, args.api_key, args.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        dt = time.time() - t0
        print(f"[INFO] latency={dt:.3f}s")
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
            print("[OK] reply:")
            print(text)
            return 0
        except Exception:
            print("[WARN] response is not standard JSON. raw=")
            print(raw)
            return 1

    # stream
    with _post_json(url, payload, args.api_key, args.timeout) as resp:
        first_token_t = None
        total = 0
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:") :].strip()
            if chunk == "[DONE]":
                break
            try:
                data = json.loads(chunk)
            except Exception:
                continue
            delta = data.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content")
            if content:
                if first_token_t is None:
                    first_token_t = time.time()
                    print(f"\n[INFO] first_token_latency={first_token_t - t0:.3f}s")
                sys.stdout.write(content)
                sys.stdout.flush()
                total += len(content)

        print("\n")
        dt = time.time() - t0
        print(f"[INFO] total_chars={total}, wall={dt:.3f}s, approx_chars_per_s={total / max(dt, 1e-6):.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
