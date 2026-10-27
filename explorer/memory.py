from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryProfile:
    name: str
    total: int
    available: int
    worker_mb: int = 256
    parser_workers: int = 1
    context_tokens: int = 2048
    background_ai: bool = False
    embeddings: bool = False


def profile() -> MemoryProfile:
    total, available = 4 * 1024**3, 1024**3
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ('total', 'available', 'page_total', 'page_available', 'virtual_total',
                 'virtual_available', 'extended')]
        status = Status()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total, available = status.total, status.available
    else:
        try:
            total = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
            available = os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
            # A cgroup limit is more relevant than host RAM in constrained CI.
            for filename in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
                try:
                    with open(filename) as stream:
                        limit = int(stream.read().strip())
                    total = min(total, limit)
                except (OSError, ValueError):
                    pass
        except (ValueError, OSError, AttributeError):
            pass
    gb = total / 1024**3
    name = 'ULTRA LOW' if gb <= 4.05 else 'LOW' if gb <= 8.05 else 'NORMAL' if gb <= 16.05 else 'HIGH'
    return MemoryProfile(name, total, available, 128 if available < 512 * 1024**2 else 256)


_job = None


def process_usage(pid):
    if os.name != 'nt':
        try:
            values = {}
            with open('/proc/%d/status' % pid) as stream:
                for line in stream:
                    if line.startswith(('VmRSS:', 'VmHWM:')):
                        key, value, _ = line.split()
                        values[key[:-1]] = int(value) / 1024
            return dict(rss_mb=values.get('VmRSS', 0), peak_rss_mb=values.get('VmHWM', 0))
        except OSError:
            return {}
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'rss', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    kernel = ctypes.WinDLL('kernel32')
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return {}
    try:
        info = Memory()
        info.size = ctypes.sizeof(info)
        psapi = ctypes.WinDLL('psapi')
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.size):
            return dict(rss_mb=info.rss / 1024**2, peak_rss_mb=info.peak / 1024**2)
        return {}
    finally:
        kernel.CloseHandle(handle)


def constrain_process(megabytes: int) -> bool:
    """Apply an OS-enforced ceiling, including child processes on Windows."""
    global _job
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (megabytes * 1024**2,) * 2)
        return True
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t),
                    ('max_ws', ctypes.c_size_t), ('active', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                    ('scheduling', wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(key, ctypes.c_ulonglong) for key in
                    ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_limit', ctypes.c_size_t),
                    ('job_limit', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                    ('peak_job', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x200 | 0x2000  # JOB_MEMORY + KILL_ON_JOB_CLOSE
    info.job_limit = megabytes * 1024**2
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return False
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        return False
    _job = handle  # Keep alive for the lifetime of this process.
    return True
