"""Best-effort Windows hardware inventory. Unknown values stay unknown."""
from __future__ import annotations
import ctypes
import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

@dataclass
class GPUInfo:
    id: str
    name: str
    vendor: str = "Unknown"
    memory_total_mb: int | None = None
    memory_free_mb: int | None = None
    utilization_percent: int | None = None
    backend_hint: str = "unknown"

@dataclass
class HardwareInfo:
    platform: str
    cpu_name: str
    cpu_logical_threads: int
    ram_total_mb: int | None
    ram_available_mb: int | None
    gpus: list[GPUInfo]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _windows_memory() -> tuple[int | None, int | None]:
    if os.name != "nt":
        try:
            page = os.sysconf("SC_PAGE_SIZE")
            total = os.sysconf("SC_PHYS_PAGES") * page // (1024 * 1024)
            available = os.sysconf("SC_AVPHYS_PAGES") * page // (1024 * 1024)
            return total, available
        except (AttributeError, ValueError, OSError):
            return None, None
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None
        return status.ullTotalPhys // (1024 * 1024), status.ullAvailPhys // (1024 * 1024)
    except (AttributeError, OSError):
        return None, None

def _run(command: list[str], timeout: int = 8) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return completed.stdout.strip() if completed.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""

def _detect_gpus() -> list[GPUInfo]:
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        output = _run([nvidia, "--query-gpu=index,name,memory.total,memory.free,utilization.gpu",
                       "--format=csv,noheader,nounits"])
        result: list[GPUInfo] = []
        for line in output.splitlines():
            parts = [x.strip() for x in line.split(",", 4)]
            if len(parts) != 5:
                continue
            try:
                result.append(GPUInfo(id=f"cuda:{parts[0]}", name=parts[1], vendor="NVIDIA",
                    memory_total_mb=int(parts[2]), memory_free_mb=int(parts[3]),
                    utilization_percent=int(parts[4]), backend_hint="CUDA/Vulkan (driver-dependent)"))
            except ValueError:
                continue
        if result:
            return result
    if os.name == "nt":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            script = "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"
            raw = _run([ps, "-NoProfile", "-NonInteractive", "-Command", script])
            try:
                payload = json.loads(raw) if raw else []
                if isinstance(payload, dict):
                    payload = [payload]
                result = []
                for index, gpu in enumerate(payload):
                    name = str(gpu.get("Name") or "Video adapter")
                    lower = name.lower()
                    vendor = "NVIDIA" if "nvidia" in lower else "AMD" if any(x in lower for x in ("amd", "radeon")) else "Intel" if "intel" in lower else "Unknown"
                    try:
                        ram_mb = int(gpu.get("AdapterRAM")) // (1024 * 1024)
                    except (TypeError, ValueError):
                        ram_mb = None
                    if ram_mb is not None and ram_mb >= 4095:
                        ram_mb = None
                    result.append(GPUInfo(id=f"adapter:{index}", name=name, vendor=vendor,
                                          memory_total_mb=ram_mb, backend_hint="driver/backend not verified"))
                return result
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
    return []

def detect_hardware() -> HardwareInfo:
    total, available = _windows_memory()
    cpu = platform.processor() or platform.machine() or "Unknown CPU"
    notes = ["GPU execution is available only when the selected llama.cpp build includes a compatible backend."]
    gpus = _detect_gpus()
    if not gpus:
        notes.append("No GPU inventory was returned by the installed drivers; CPU inference remains available.")
    elif any(g.memory_total_mb is None for g in gpus):
        notes.append("Some adapter VRAM values are unavailable or unreliable; no memory has been assumed.")
    return HardwareInfo(platform=f"{platform.system()} {platform.release()} {platform.machine()}",
        cpu_name=cpu, cpu_logical_threads=os.cpu_count() or 1, ram_total_mb=total,
        ram_available_mb=available, gpus=gpus, notes=notes)
