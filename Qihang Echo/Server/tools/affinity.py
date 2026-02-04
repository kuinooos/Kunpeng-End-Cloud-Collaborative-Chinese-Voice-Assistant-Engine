import os
import platform
import threading
from typing import Iterable, Optional, Union

from config.settings import global_settings
from tools.logger import logger


def _parse_cpu_set(cpu_set: Optional[Union[str, Iterable[int]]]) -> Optional[set[int]]:
    if cpu_set is None:
        return None
    if isinstance(cpu_set, str):
        cpus: set[int] = set()
        for part in cpu_set.split(','):
            part = part.strip()
            if '-' in part:
                a, b = part.split('-')
                cpus.update(range(int(a), int(b) + 1))
            elif part:
                cpus.add(int(part))
        return cpus if cpus else None
    try:
        return set(int(x) for x in cpu_set)
    except Exception:
        return None


def set_process_affinity(cpu_set: Optional[Union[str, Iterable[int]]]) -> None:
    cpus = _parse_cpu_set(cpu_set)
    if not cpus:
        return
    try:
        os.sched_setaffinity(0, cpus)
        logger.info(f"Process CPU affinity set to: {sorted(cpus)}")
    except Exception as e:
        logger.warning(f"Failed to set process affinity: {e}")


def set_thread_affinity(cpu_set: Optional[Union[str, Iterable[int]]]) -> None:
    cpus = _parse_cpu_set(cpu_set)
    if not cpus:
        return
    try:
        # pthread self via sched_setaffinity through tid
        try:
            # Python 3.8+ on Linux exposes thread native id
            tid = threading.get_native_id()
        except AttributeError:
            # Fallback to gettid syscall via os
            tid = 0
        if tid:
            os.sched_setaffinity(tid, cpus)
        else:
            os.sched_setaffinity(0, cpus)
        logger.info(f"Thread CPU affinity set to: {sorted(cpus)}")
    except Exception as e:
        logger.warning(f"Failed to set thread affinity: {e}")


def configure_runtime_threads():
    """
    Configure BLAS/OMP/Torch threading env for ARM/openEuler.
    """
    n = int(global_settings.THREADS_LINEAR_ALG)
    env_updates = {
        "OMP_NUM_THREADS": str(n),
        "OPENBLAS_NUM_THREADS": str(n),
        "NUMEXPR_NUM_THREADS": str(n),
        # Avoid MKL oversub on ARM; present but harmless if MKL not used
        "MKL_NUM_THREADS": "1",
    }
    os.environ.update(env_updates)
    try:
        import torch
        torch.set_num_threads(int(global_settings.TORCH_NUM_THREADS))
        torch.set_num_interop_threads(int(global_settings.TORCH_NUM_INTEROP_THREADS))
        logger.info(
            f"Torch threads set: compute={global_settings.TORCH_NUM_THREADS}, interop={global_settings.TORCH_NUM_INTEROP_THREADS}"
        )
    except Exception as e:
        logger.warning(f"Torch threading config skipped: {e}")
