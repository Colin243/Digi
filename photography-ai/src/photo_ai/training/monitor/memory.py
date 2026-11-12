"""Cheap memory readings for the training monitor (no psutil; macOS via libproc/sysctl).

There are three different things called "memory" on an Apple-silicon Mac, and they overlap:

  mlx_active_gb   bytes held by live MLX arrays (model weights, activations, gradients,
                  optimizer state). These are Metal buffers that live in unified memory.
  mlx_cache_gb    buffers MLX has freed but keeps for reuse (capped by cache_limit_gb).
                  Not used by any array, but still resident and still counted by macOS.
  mlx_peak_gb     the high-water mark of mlx_active since the last reset (start of training).
  proc_footprint_gb  what macOS charges to this process ("Memory" in Activity Monitor):
                  it ALREADY INCLUDES the MLX/Metal buffers above plus the Python heap,
                  tokenizer, images, etc. Never add mlx_active to it.
  swap_used_gb    system-wide swap in use (not per process). Growth during a run means the
                  machine as a whole is over-committed; it is the signal that slowed the
                  uncapped-cache run from ~3 s to 20-60 s per row.
  pressure        macOS memory-pressure level: 1 normal, 2 warning, 4 critical.

Every reader returns None when the value cannot be read; the dashboard shows "unavailable".
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

GB = 1e9

_libc = None


def _lib():
    global _libc
    if _libc is None and sys.platform == "darwin":
        try:
            _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        except OSError:
            _libc = False
    return _libc or None


class _RUsageInfoV2(ctypes.Structure):  # <libproc.h> rusage_info_v2 (prefix we need)
    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16), ("ri_user_time", ctypes.c_uint64),
                ("ri_system_time", ctypes.c_uint64), ("ri_pkg_idle_wkups", ctypes.c_uint64),
                ("ri_interrupt_wkups", ctypes.c_uint64), ("ri_pageins", ctypes.c_uint64),
                ("ri_wired_size", ctypes.c_uint64), ("ri_resident_size", ctypes.c_uint64),
                ("ri_phys_footprint", ctypes.c_uint64), ("ri_proc_start_abstime", ctypes.c_uint64),
                ("ri_proc_exit_abstime", ctypes.c_uint64), ("ri_child_user_time", ctypes.c_uint64),
                ("ri_child_system_time", ctypes.c_uint64), ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
                ("ri_child_interrupt_wkups", ctypes.c_uint64), ("ri_child_pageins", ctypes.c_uint64),
                ("ri_child_elapsed_abstime", ctypes.c_uint64), ("ri_diskio_bytesread", ctypes.c_uint64),
                ("ri_diskio_byteswritten", ctypes.c_uint64)]


class _XswUsage(ctypes.Structure):
    _fields_ = [("xsu_total", ctypes.c_uint64), ("xsu_avail", ctypes.c_uint64),
                ("xsu_used", ctypes.c_uint64), ("xsu_pagesize", ctypes.c_uint32),
                ("xsu_encrypted", ctypes.c_bool)]


def process_memory() -> dict:
    lib = _lib()
    if lib is None:
        return {"proc_footprint_gb": None}
    try:
        info = _RUsageInfoV2()
        if lib.proc_pid_rusage(os.getpid(), 2, ctypes.byref(info)) != 0:
            raise OSError(ctypes.get_errno())
        # ri_resident_size is not reported: on Apple silicon it excludes the Metal buffers and reads
        # far below the footprint, which would invite exactly the double-count confusion we avoid.
        return {"proc_footprint_gb": info.ri_phys_footprint / GB}
    except (OSError, AttributeError):
        return {"proc_footprint_gb": None}


def _sysctl(name: str, ctype):
    lib = _lib()
    if lib is None:
        return None
    try:
        val = ctype()
        size = ctypes.c_size_t(ctypes.sizeof(val))
        if lib.sysctlbyname(name.encode(), ctypes.byref(val), ctypes.byref(size), None, 0) != 0:
            return None
        return val
    except (OSError, AttributeError):
        return None


def system_memory() -> dict:
    sw = _sysctl("vm.swapusage", _XswUsage)
    pr = _sysctl("kern.memorystatus_vm_pressure_level", ctypes.c_int)
    total = _sysctl("hw.memsize", ctypes.c_uint64)
    return {"swap_used_gb": None if sw is None else sw.xsu_used / GB,
            "pressure": None if pr is None else int(pr.value),
            "system_total_gb": None if total is None else total.value / GB}


def mlx_memory() -> dict:
    try:
        import mlx.core as mx

        return {"mlx_active_gb": mx.get_active_memory() / GB, "mlx_cache_gb": mx.get_cache_memory() / GB,
                "mlx_peak_gb": mx.get_peak_memory() / GB}
    except Exception:  # noqa: BLE001 - any failure means "unavailable", never a crash
        return {"mlx_active_gb": None, "mlx_cache_gb": None, "mlx_peak_gb": None}


def snapshot(system: bool = True) -> dict:
    out = {**mlx_memory(), **process_memory()}
    if system:
        out.update(system_memory())
    return out
