"""Windows job objects through ctypes: limits on memory and CPU time, how much memory and CPU a program
and everything it started used, and stopping the whole tree at once. (On Linux and macOS the same is
done with resource limits and os.wait4.)"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.CreateJobObjectW.restype = wintypes.HANDLE
_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
_kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_kernel32.SetInformationJobObject.restype = wintypes.BOOL
_kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_kernel32.QueryInformationJobObject.restype = wintypes.BOOL
_kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                ctypes.c_void_p]
_kernel32.TerminateJobObject.restype = wintypes.BOOL
_kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_PROCESS_SET_QUOTA, _PROCESS_TERMINATE = 0x0100, 0x0001
_BASIC_ACCOUNTING, _EXTENDED_LIMITS = 1, 9
_LIMIT_JOB_TIME, _LIMIT_PROCESS_MEMORY, _LIMIT_BREAKAWAY_OK = 0x4, 0x100, 0x800


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


class Job:
    """One job object holding every program of one command."""

    def __init__(self, memory_limit_mb: float | None = None, cpu_limit_seconds: float | None = None):
        self.handle = _kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _ExtendedLimits()
        flags = _LIMIT_BREAKAWAY_OK
        if memory_limit_mb:
            flags |= _LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = int(memory_limit_mb * 1024 * 1024)
        if cpu_limit_seconds:
            flags |= _LIMIT_JOB_TIME
            info.BasicLimitInformation.PerJobUserTimeLimit = int(cpu_limit_seconds * 10_000_000)
        info.BasicLimitInformation.LimitFlags = flags
        if not _kernel32.SetInformationJobObject(self.handle, _EXTENDED_LIMITS, ctypes.byref(info),
                                                 ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def add(self, pid: int) -> bool:
        process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            return False
        try:
            return bool(_kernel32.AssignProcessToJobObject(self.handle, process))
        finally:
            _kernel32.CloseHandle(process)

    def stop_all(self) -> None:
        _kernel32.TerminateJobObject(self.handle, 1)

    def peak_memory_mb(self) -> float | None:
        info = _ExtendedLimits()
        if _kernel32.QueryInformationJobObject(self.handle, _EXTENDED_LIMITS, ctypes.byref(info),
                                               ctypes.sizeof(info), None):
            return info.PeakJobMemoryUsed / (1024 * 1024)
        return None

    def cpu_seconds(self) -> float | None:
        info = _Accounting()
        if _kernel32.QueryInformationJobObject(self.handle, _BASIC_ACCOUNTING, ctypes.byref(info),
                                               ctypes.sizeof(info), None):
            return (info.TotalUserTime + info.TotalKernelTime) / 10_000_000
        return None

    def close(self) -> None:
        if self.handle:
            _kernel32.CloseHandle(self.handle)
            self.handle = None
