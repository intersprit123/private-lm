"""Versioned, validated settings shared by PrivateLM cluster nodes."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1
EXECUTION_MODES = {"performance", "performance_group", "extreme_force"}
GPU_POLICIES = {"auto", "cpu", "single", "all_compatible"}
IMAGE_BACKENDS = {"auto", "cpu", "gpu"}
STARTUP_BEHAVIORS = {"remember", "ask"}
TEXT_SCALES = {"small", "medium", "large"}

@dataclass
class ClusterConfig:
    """Only portable settings belong here; never include local paths or secrets."""
    revision: int = 1
    schema_version: int = SCHEMA_VERSION
    execution_mode: str = "performance"
    model_label: str = ""
    context_size: int = 4096
    max_output_tokens: int = 512
    temperature: float = 0.7
    cpu_threads: int = 0
    gpu_policy: str = "auto"
    ram_budget_percent: int = 40
    image_backend: str = "auto"
    startup_behavior: str = "remember"
    text_scale: str = "medium"
    selected_gpu_ids: list[str] = field(default_factory=list)
    available_gpu_devices: list[dict[str, str]] = field(default_factory=list)

    def validate(self) -> "ClusterConfig":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported cluster settings schema: {self.schema_version}")
        if self.revision < 1:
            raise ValueError("Configuration revision must be positive")
        if self.execution_mode not in EXECUTION_MODES:
            raise ValueError("Unknown execution mode")
        if self.gpu_policy not in GPU_POLICIES:
            raise ValueError("Unknown GPU policy")
        if self.image_backend not in IMAGE_BACKENDS:
            raise ValueError("Unknown image-generation backend")
        if self.startup_behavior not in STARTUP_BEHAVIORS:
            raise ValueError("Unknown startup behavior")
        if self.text_scale not in TEXT_SCALES:
            raise ValueError("Text scale must be small, medium or large")
        if not 256 <= self.context_size <= 1_048_576:
            raise ValueError("Context size must be between 256 and 1,048,576 tokens")
        if not 1 <= self.max_output_tokens <= self.context_size:
            raise ValueError("Maximum output tokens must be within the context window")
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0")
        if not 0 <= self.cpu_threads <= 512:
            raise ValueError("CPU threads must be 0 (automatic) or between 1 and 512")
        # Preserve at least 30% memory for Windows, drivers and other applications.
        if not 10 <= self.ram_budget_percent <= 70:
            raise ValueError("RAM budget must be between 10% and 70% to preserve OS headroom")
        if len(self.model_label) > 160:
            raise ValueError("Model label is too long")
        if len(self.selected_gpu_ids) > 64 or any(len(str(x)) > 128 for x in self.selected_gpu_ids):
            raise ValueError("Invalid GPU selection")
        if len(self.available_gpu_devices) > 64 or any(not isinstance(x, dict) or not x.get("id") or len(str(x.get("id"))) > 128 or len(str(x.get("name", ""))) > 200 for x in self.available_gpu_devices):
            raise ValueError("Invalid detected GPU inventory")
        available_ids = {str(x["id"]) for x in self.available_gpu_devices}
        if any(x not in available_ids for x in self.selected_gpu_ids):
            raise ValueError("Selected GPU is not in the detected inventory")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ClusterConfig":
        allowed = set(cls.__dataclass_fields__)
        clean = {k: v for k, v in value.items() if k in allowed}
        if "selected_gpu_ids" in clean and not isinstance(clean["selected_gpu_ids"], list):
            raise ValueError("selected_gpu_ids must be a list")
        return cls(**clean).validate()

    def next_revision(self, **changes: Any) -> "ClusterConfig":
        value = self.to_dict()
        value.update(changes)
        value["revision"] = self.revision + 1
        return ClusterConfig.from_dict(value)
