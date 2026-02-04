#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Benchmark to demonstrate benefits of CPU/NUMA affinity.

Produces a JSON file containing:
- inference latency distribution (p50/p95/p99)
- CPU core migration (cpu_num samples)
- process CPU%, RSS, context switches, page faults (Linux)

This script is intentionally self-contained and can be used in two modes:
- baseline: no affinity pinning
- affinity: run under taskset/numactl or use settings-based set_process_affinity

Recommended usage (Linux/openEuler):
  python3 AIChat_demo/Server/tools/affinity_benchmark.py --engine onnx --loops 50 --out out.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Event, Thread
from typing import Any, Optional

import numpy as np


def _read_proc_self_stat_faults() -> Optional[dict[str, int]]:
    """Return minflt/majflt from /proc/self/stat if available."""
    try:
        with open("/proc/self/stat", "r", encoding="utf-8") as f:
            data = f.read().strip().split()
        # man proc: fields
        # 10 minflt, 12 majflt (1-indexed: 10th and 12th)
        # In zero-based list: 9 and 11
        return {
            "minflt": int(data[9]),
            "majflt": int(data[11]),
        }
    except Exception:
        return None


def _safe_import_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


@dataclass
class Sample:
    t: float
    cpu_num: Optional[int]
    cpu_percent: Optional[float]
    rss_mb: Optional[float]
    vms_mb: Optional[float]
    vol_ctx: Optional[int]
    invol_ctx: Optional[int]
    minflt: Optional[int]
    majflt: Optional[int]


class Sampler:
    def __init__(self, interval_s: float = 0.2):
        self.interval_s = interval_s
        self.stop = Event()
        self.samples: list[Sample] = []

        self._psutil = _safe_import_psutil()
        self._proc = self._psutil.Process(os.getpid()) if self._psutil else None

    def start(self) -> None:
        if self._proc:
            try:
                # Prime cpu_percent
                self._proc.cpu_percent(interval=None)
            except Exception:
                pass
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def finish(self) -> None:
        self.stop.set()
        if hasattr(self, "_thread"):
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self.stop.is_set():
            t = time.time()

            cpu_num = None
            cpu_percent = None
            rss_mb = None
            vms_mb = None
            vol_ctx = None
            invol_ctx = None

            if self._proc:
                try:
                    cpu_num = int(self._proc.cpu_num())
                except Exception:
                    cpu_num = None
                try:
                    cpu_percent = float(self._proc.cpu_percent(interval=None))
                except Exception:
                    cpu_percent = None
                try:
                    mi = self._proc.memory_info()
                    rss_mb = float(mi.rss) / (1024 * 1024)
                    vms_mb = float(mi.vms) / (1024 * 1024)
                except Exception:
                    rss_mb = None
                    vms_mb = None
                try:
                    cs = self._proc.num_ctx_switches()
                    vol_ctx = int(cs.voluntary)
                    invol_ctx = int(cs.involuntary)
                except Exception:
                    vol_ctx = None
                    invol_ctx = None

            faults = _read_proc_self_stat_faults()
            self.samples.append(
                Sample(
                    t=t,
                    cpu_num=cpu_num,
                    cpu_percent=cpu_percent,
                    rss_mb=rss_mb,
                    vms_mb=vms_mb,
                    vol_ctx=vol_ctx,
                    invol_ctx=invol_ctx,
                    minflt=faults["minflt"] if faults else None,
                    majflt=faults["majflt"] if faults else None,
                )
            )

            time.sleep(self.interval_s)


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return d0 + d1


def _compute_summary(lat_ms: list[float], samples: list[Sample]) -> dict[str, Any]:
    lat_sorted = sorted(lat_ms)
    summary: dict[str, Any] = {
        "count": len(lat_ms),
        "mean_ms": statistics.fmean(lat_ms) if lat_ms else None,
        "std_ms": statistics.pstdev(lat_ms) if len(lat_ms) > 1 else None,
        "p50_ms": _percentile(lat_sorted, 50),
        "p95_ms": _percentile(lat_sorted, 95),
        "p99_ms": _percentile(lat_sorted, 99),
        "min_ms": min(lat_ms) if lat_ms else None,
        "max_ms": max(lat_ms) if lat_ms else None,
    }

    # sampler-derived deltas
    if samples:
        rss = [s.rss_mb for s in samples if s.rss_mb is not None]
        summary["rss_peak_mb"] = max(rss) if rss else None
        summary["rss_mean_mb"] = statistics.fmean(rss) if rss else None

        cpu_nums = [s.cpu_num for s in samples if s.cpu_num is not None]
        summary["cpu_unique_cores"] = len(set(cpu_nums)) if cpu_nums else None

        # context switches & faults deltas (end - start)
        def _delta(field: str) -> Optional[int]:
            vals = [getattr(s, field) for s in samples if getattr(s, field) is not None]
            if len(vals) < 2:
                return None
            return int(vals[-1] - vals[0])

        summary["vol_ctx_delta"] = _delta("vol_ctx")
        summary["invol_ctx_delta"] = _delta("invol_ctx")
        summary["minflt_delta"] = _delta("minflt")
        summary["majflt_delta"] = _delta("majflt")

        cpu_p = [s.cpu_percent for s in samples if s.cpu_percent is not None]
        summary["cpu_percent_mean"] = statistics.fmean(cpu_p) if cpu_p else None

    return summary


def _load_engine(engine: str, onnx_path: Optional[str], vocab_path: Optional[str]) -> Any:
    # Lazy imports to keep the script usable even if some deps are missing.
    import sys

    here = Path(__file__).resolve()
    server_dir = here.parents[1]
    sys.path.append(str(server_dir))

    if engine == "torch":
        from models.asr_model import ASRModel  # type: ignore

        model = ASRModel(device="cpu")
        if getattr(model, "model", None) is None:
            raise RuntimeError("Torch ASR model load failed (model is None)")
        return model

    if engine == "onnx":
        from config.settings import global_settings  # type: ignore
        from models.asr_model_npu import ASRModelNPU  # type: ignore

        path = onnx_path or getattr(global_settings, "ASR_ONNX_MODEL_PATH", None)
        if not path or not os.path.exists(path):
            raise RuntimeError(f"ONNX model not found: {path}")

        vp = vocab_path or getattr(global_settings, "ASR_VOCAB_PATH", "")
        if vp and (not os.path.exists(vp)):
            # Keep running (ASRModelNPU will return raw IDs), but be explicit.
            print(f"[WARN] vocab/tokens file not found: {vp}")

        model = ASRModelNPU(
            model_path=path,
            vocab_path=vp,
            device="cpu-onnx",
        )
        if getattr(model, "session", None) is None:
            raise RuntimeError("ONNX session create failed (session is None)")
        return model

    raise ValueError(f"Unknown engine: {engine}")


def _infer(engine: str, model: Any, audio: np.ndarray) -> Any:
    if engine == "torch":
        return model.ASR_generate_text(audio)
    if engine == "onnx":
        return model.ASR_generate_text(audio)
    raise ValueError(engine)


def main() -> int:
    parser = argparse.ArgumentParser(description="Affinity benchmark runner (outputs JSON)")
    parser.add_argument("--mode", choices=["baseline", "affinity"], default="baseline")
    parser.add_argument("--engine", choices=["onnx", "torch"], default="onnx")
    parser.add_argument("--onnx-path", default=None, help="Override ASR ONNX path")
    parser.add_argument(
        "--vocab-path",
        default=None,
        help="Override SenseVoice vocab/tokens path (tokens.json). If omitted, uses config.settings global_settings.ASR_VOCAB_PATH.",
    )
    parser.add_argument("--loops", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--audio-seconds", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sampler-interval", type=float, default=0.2)
    parser.add_argument(
        "--ort-intra-threads",
        type=int,
        default=None,
        help="ONNX Runtime intra-op threads (sets ORT_INTRA_OP_NUM_THREADS). Highly recommended when taskset pins to 1-2 cores.",
    )
    parser.add_argument(
        "--ort-inter-threads",
        type=int,
        default=None,
        help="ONNX Runtime inter-op threads (sets ORT_INTER_OP_NUM_THREADS).",
    )
    parser.add_argument(
        "--ort-exec-mode",
        choices=["sequential", "parallel"],
        default=None,
        help="ONNX Runtime execution mode (sets ORT_EXECUTION_MODE).",
    )
    args = parser.parse_args()

    # Configure ORT threading deterministically (read by ASRModelNPU).
    if args.engine == "onnx":
        if args.ort_intra_threads is not None:
            os.environ["ORT_INTRA_OP_NUM_THREADS"] = str(int(args.ort_intra_threads))
        if args.ort_inter_threads is not None:
            os.environ["ORT_INTER_OP_NUM_THREADS"] = str(int(args.ort_inter_threads))
        if args.ort_exec_mode is not None:
            os.environ["ORT_EXECUTION_MODE"] = str(args.ort_exec_mode).upper()

    sr = int(args.sample_rate)
    audio_len = int(sr * float(args.audio_seconds))
    # Random audio in [-0.1,0.1] float32, consistent with existing benchmark_asr.py
    rng = np.random.default_rng(42)
    audio = rng.uniform(-0.1, 0.1, audio_len).astype(np.float32)

    model = _load_engine(args.engine, args.onnx_path, args.vocab_path)

    # Warmup
    for _ in range(max(0, int(args.warmup))):
        _infer(args.engine, model, audio)

    sampler = Sampler(interval_s=float(args.sampler_interval))
    sampler.start()

    lat_ms: list[float] = []
    t0 = time.perf_counter()
    for _ in range(max(1, int(args.loops))):
        s = time.perf_counter()
        _infer(args.engine, model, audio)
        e = time.perf_counter()
        lat_ms.append((e - s) * 1000.0)
    t1 = time.perf_counter()

    sampler.finish()

    report: dict[str, Any] = {
        "meta": {
            "mode": args.mode,
            "engine": args.engine,
            "onnx_path": args.onnx_path,
            "vocab_path": args.vocab_path,
            "audio_seconds": float(args.audio_seconds),
            "sample_rate": sr,
            "loops": int(args.loops),
            "warmup": int(args.warmup),
            "sampler_interval": float(args.sampler_interval),
            "ort_intra_threads": args.ort_intra_threads,
            "ort_inter_threads": args.ort_inter_threads,
            "ort_exec_mode": (str(args.ort_exec_mode).upper() if args.ort_exec_mode else None),
            "elapsed_s": float(t1 - t0),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "host": platform.node(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "pid": os.getpid(),
            "env": {
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
                "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
                "ORT_INTRA_OP_NUM_THREADS": os.environ.get("ORT_INTRA_OP_NUM_THREADS"),
                "ORT_INTER_OP_NUM_THREADS": os.environ.get("ORT_INTER_OP_NUM_THREADS"),
                "ORT_EXECUTION_MODE": os.environ.get("ORT_EXECUTION_MODE"),
                "NUMEXPR_NUM_THREADS": os.environ.get("NUMEXPR_NUM_THREADS"),
                "MKL_NUM_THREADS": os.environ.get("MKL_NUM_THREADS"),
            },
        },
        "latency_ms": lat_ms,
        "samples": [asdict(s) for s in sampler.samples],
        "summary": _compute_summary(lat_ms, sampler.samples),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] wrote: {out_path}")
    print("[Summary]", report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

