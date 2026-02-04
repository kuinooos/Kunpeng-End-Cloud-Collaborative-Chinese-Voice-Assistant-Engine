#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Noise generator for affinity/isolation demonstrations.

Goal:
- Create controlled CPU contention and optional memory pressure.
- Intended to be pinned to a specific CPU set/NUMA node by external tools
  (taskset/numactl) so we can demonstrate "算力隔离" and "内存防御".

This tool is deliberately simple and dependency-free.
"""

from __future__ import annotations

import argparse
import os
import time
from multiprocessing import Event, Process


def _cpu_spin(stop: Event) -> None:
    x = 0
    while not stop.is_set():
        x = (x * 1664525 + 1013904223) & 0xFFFFFFFF


def _mem_pressure(stop: Event, mem_mb: int, touch: bool) -> None:
    # Allocate and (optionally) touch memory pages to force real RSS.
    size = int(mem_mb) * 1024 * 1024
    if size <= 0:
        while not stop.is_set():
            time.sleep(0.2)
        return

    buf = bytearray(size)
    if touch:
        step = 4096
        i = 0
        while not stop.is_set():
            buf[i] = (buf[i] + 1) & 0xFF
            i = (i + step) % len(buf)
    else:
        while not stop.is_set():
            time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description="CPU/memory noise generator")
    parser.add_argument("--cpu-workers", type=int, default=max(1, (os.cpu_count() or 1) // 2))
    parser.add_argument("--mem-mb", type=int, default=0, help="Total memory (MB) to allocate in a single process")
    parser.add_argument("--touch", action="store_true", help="Continuously touch allocated pages")
    parser.add_argument("--duration", type=float, default=30.0, help="Seconds to run")
    args = parser.parse_args()

    stop = Event()
    procs: list[Process] = []

    for _ in range(max(0, int(args.cpu_workers))):
        p = Process(target=_cpu_spin, args=(stop,), daemon=True)
        p.start()
        procs.append(p)

    if args.mem_mb > 0:
        p = Process(target=_mem_pressure, args=(stop, int(args.mem_mb), bool(args.touch)), daemon=True)
        p.start()
        procs.append(p)

    try:
        time.sleep(max(0.0, float(args.duration)))
    finally:
        stop.set()
        for p in procs:
            p.join(timeout=1.0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

