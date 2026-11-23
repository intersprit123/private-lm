#!/usr/bin/env python3
"""PrivateLM Windows Host: local inference launcher and secure cluster coordinator."""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import socket
import subprocess
import threading
import tkinter as tk
import qrcode
from PIL import ImageTk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from .cluster_config import ClusterConfig
    from .cluster_protocol import ClusterControlServer, ClusterRegistry, create_tls_identity
    from .hardware import detect_hardware
except ImportError:  # PyInstaller runs this file as the application entry point.
    from cluster_config import ClusterConfig
    from cluster_protocol import ClusterControlServer, ClusterRegistry, create_tls_identity
    from hardware import detect_hardware

APP = "PrivateLM"
BG, PANEL, PANEL2, TEXT, MUTED, BLUE = "#07111f", "#101e31", "#14263d", "#eaf3ff", "#91a7c2", "#278dff"


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PrivateLMWindows"


class HostApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("PrivateLM · Device Cluster")
        root.geometry("1000x850")
        root.minsize(860, 700)
        root.configure(bg=BG)
        self.proc = None
        self.control: ClusterControlServer | None = None
        self.registry = ClusterRegistry(data_dir() / "cluster_state.json")
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_path = data_dir() / "llama-server.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path = data_dir() / "host_settings.json"
        self.saved = self._load_saved()
        self.server = tk.StringVar(value=self.saved.get("server", ""))
        self.model = tk.StringVar(value=self.saved.get("model", ""))
        self.port = tk.StringVar(value=str(self.saved.get("port", 8080)))
        self.ctx = tk.StringVar(value=str(self.saved.get("context_size", 4096)))
        self.threads = tk.StringVar(value=str(self.saved.get("cpu_threads", 0)))
        self.ngl = tk.StringVar(value=str(self.saved.get("gpu_layers", 0)))
        self.max_tokens = tk.StringVar(value=str(self.saved.get("max_output_tokens", 512)))
        self.temperature = tk.StringVar(value=str(self.saved.get("temperature", 0.7)))
        self.ram_budget = tk.StringVar(value=str(self.saved.get("ram_budget_percent", 40)))
        self.mode = tk.StringVar(value=self.saved.get("execution_mode", "performance"))
        self.gpu_policy = tk.StringVar(value=self.saved.get("gpu_policy", "auto"))
        self.image_backend = tk.StringVar(value=self.saved.get("image_backend", "auto"))
        self.text_scale = tk.StringVar(value=self.saved.get("text_scale", "medium"))
        self.startup = tk.StringVar(value=self.saved.get("startup_behavior", "ask"))
        self.remote_workers = tk.StringVar(value=self.saved.get("remote_workers", ""))
        self.gpu_devices = tk.StringVar(value=self.saved.get("gpu_devices", ""))
        self.key = tk.StringVar(value="plm_" + secrets.token_urlsafe(24))
        self.status = tk.StringVar(value="Inference stopped")
        self.cluster_status = tk.StringVar(value="Cluster control stopped")
        self.pair_code = tk.StringVar(value="Start the secure cluster service to create a code")
        self.fingerprint = tk.StringVar(value="Certificate fingerprint: not generated")
        self.hardware_text = tk.StringVar(value="Detecting hardware…")
        self.hw = None
        self.compute_choice = tk.StringVar(value=self.saved.get("compute_choice", "both"))
        self._build()
        self.text_scale.trace_add('write', lambda *_: self.apply_text_scale())
        self.apply_text_scale()
        self.root.after(150, self._drain)
        self.root.after(250, self._detect_hardware)
        self.root.after(2500, self._refresh_nodes)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _load_saved(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        if self.startup.get() != "remember":
            return
        values = {"compute_choice": self.compute_choice.get(), "server": self.server.get(), "model": self.model.get(), "port": self.port.get(),
                  "context_size": self.ctx.get(), "cpu_threads": self.threads.get(), "gpu_layers": self.ngl.get(),
                  "max_output_tokens": self.max_tokens.get(), "temperature": self.temperature.get(),
                  "ram_budget_percent": self.ram_budget.get(), "execution_mode": self.mode.get(),
                  "gpu_policy": self.gpu_policy.get(), "image_backend": self.image_backend.get(),
                  "text_scale": self.text_scale.get(), "startup_behavior": self.startup.get(),
                  "remote_workers": self.remote_workers.get(), "gpu_devices": self.gpu_devices.get()}
        self.state_path.write_text(json.dumps(values, indent=2), encoding="utf-8")

    def _build(self) -> None:
        style = ttk.Style(self.root); self.style = style; style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Side.TFrame", background="#0b1628")
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Side.TLabel", background="#0b1628", foreground="#c6d5e8", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 23, "bold"))
        style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("Metric.TLabel", background=PANEL, foreground="#65b7ff", font=("Segoe UI", 23, "bold"))
        style.configure("Section.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 16, "bold"))
        style.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT, insertcolor=TEXT)
        style.configure("TCombobox", fieldbackground=PANEL2, foreground=TEXT, background=PANEL2)
        style.configure("TButton", background="#1d4774", foreground=TEXT, padding=(12, 8), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("TButton", background=[("active", BLUE), ("disabled", "#26394e")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        self.root.configure(bg=BG); self.root.geometry("1240x820"); self.root.minsize(1000, 680)
        outer = ttk.Frame(self.root); outer.pack(fill="both", expand=True)
        sidebar = ttk.Frame(outer, style="Side.TFrame", width=205, padding=(14, 20))
        sidebar.pack(side="left", fill="y"); sidebar.pack_propagate(False)
        brand = ttk.Frame(sidebar, style="Side.TFrame"); brand.pack(fill="x", pady=(0, 24))
        ttk.Label(brand, text="✦  PrivateLM", background="#0b1628", foreground="#f3f7ff",
                  font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(brand, text="LOCAL AI PLATFORM", background="#0b1628", foreground="#6faee8",
                  font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(4, 0))
        self.nav_buttons = {}
        nav_items = [("⌂", "Dashboard"), ("▥", "Performance"), ("▣", "Models"),
                     ("⌘", "Devices"), ("◇", "Privacy & Security"), ("◷", "Startup"),
                     ("☰", "Logs"), ("⚙", "Settings")]
        for glyph, name in nav_items:
            btn = tk.Button(sidebar, text=f"{glyph}   {name}", anchor="w", relief="flat",
                bd=0, padx=12, pady=11, bg="#0b1628", fg="#c6d5e8",
                activebackground="#1b3d65", activeforeground="white",
                font=("Segoe UI", 10), command=lambda n=name: self._nav_to(n))
            btn.pack(fill="x", pady=2); self.nav_buttons[name] = btn
        ttk.Label(sidebar, text="PRIVATE & LOCAL\nDevice services stay on your network",
                  background="#0b1628", foreground="#7890aa", font=("Segoe UI", 8),
                  justify="left").pack(side="bottom", anchor="w", pady=8)
        main = ttk.Frame(outer, padding=(24, 18)); main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main); top.pack(fill="x", pady=(0, 18))
        self.page_heading = tk.StringVar(value="Dashboard")
        ttk.Label(top, textvariable=self.page_heading, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="●  LOCAL HOST", foreground="#62d6a2").pack(side="right", padx=12)
        ttk.Button(top, text="Dark mode", command=lambda: None).pack(side="right")
        self.page_area = ttk.Frame(main); self.page_area.pack(fill="both", expand=True)
        self._nav_to("Dashboard")
        self.root.after(300, self._detect_hardware)

    def _card(self, parent, title, value, detail=""):
        card = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        ttk.Label(card, text=title.upper(), style="Muted.TLabel").pack(anchor="w")
        ttk.Label(card, text=value, background=PANEL, foreground="#65b7ff",
                  font=("Segoe UI", 21, "bold")).pack(anchor="w", pady=(8, 2))
        if detail:
            ttk.Label(card, text=detail, background=PANEL, foreground=MUTED,
                      wraplength=230).pack(anchor="w")
        return card

    def _section(self, parent, title, subtitle=None):
        ttk.Label(parent, text=title, style="Section.TLabel").pack(anchor="w", pady=(8, 3))
        if subtitle:
            ttk.Label(parent, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(0, 10))

    def _nav_to(self, page: str) -> None:
        self.page_heading.set(page)
        for name, btn in self.nav_buttons.items():
            btn.configure(bg="#1b3d65" if name == page else "#0b1628",
                          fg="white" if name == page else "#c6d5e8")
        for child in self.page_area.winfo_children(): child.destroy()
        if page == "Dashboard":
            self._dashboard_page()
        elif page == "Performance":
            self._performance_page()
        elif page == "Models":
            self._models_page()
        elif page == "Devices":
            self._devices_page()
        elif page == "Privacy & Security":
            self._security_page()
        elif page == "Startup":
            self._startup_page()
        elif page == "Logs":
            self._logs_page()
        else:
            self._settings_page()

    def _dashboard_page(self):
        self._section(self.page_area, "System overview", "Your local inference host at a glance")
        summary = ttk.Frame(self.page_area); summary.pack(fill="x", pady=(6, 14))
        cards = [
            ("CPU", "Detecting…", "Processor and logical threads"),
            ("RAM", "Detecting…", "System memory"),
            ("GPU / VRAM", "Detecting…", "Available graphics devices"),
            ("Inference", "Stopped", "Local model server status"),
        ]
        self.metric_values = []
        for title, value, detail in cards:
            card = self._card(summary, title, value, detail); card.pack(side="left", fill="both", expand=True, padx=(0, 10))
            self.metric_values.append((card, title))
        self._section(self.page_area, "Quick actions", "Common PrivateLM tasks")
        actions = ttk.Frame(self.page_area); actions.pack(fill="x", pady=(4, 16))
        for label, command in [("▶  Start inference", self.start), ("■  Stop inference", self.stop),
                               ("＋  Load model", lambda: self._nav_to("Models")),
                               ("⚙  Auto configure", self._auto_configure),
                               ("▦  Pair device", lambda: self._nav_to("Devices"))]:
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 8))
        lower = ttk.Frame(self.page_area); lower.pack(fill="both", expand=True)
        left = ttk.Frame(lower, style="Panel.TFrame", padding=16); left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(lower, style="Panel.TFrame", padding=16); right.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="HOST STATUS", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(left, textvariable=self.status, background=PANEL, foreground="#65b7ff",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=12)
        ttk.Label(left, text="Model: " + (Path(self.model.get()).name if self.model.get() else "No model selected"),
                  background=PANEL, foreground=MUTED).pack(anchor="w")
        ttk.Label(right, text="DEVICE CLUSTER", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(right, textvariable=self.cluster_status, background=PANEL, foreground=MUTED).pack(anchor="w", pady=12)
        ttk.Button(right, text="Open device management", command=lambda: self._nav_to("Devices")).pack(anchor="w")

    def _performance_page(self):
        self._section(self.page_area, "Hardware specifications", "Detected hardware. Unknown values are shown honestly rather than guessed.")
        hw = self.hw
        if not hw:
            ttk.Label(self.page_area, text="Scanning hardware…", style="Muted.TLabel").pack(anchor="w", pady=20); return
        self._spec_row(self.page_area, "Operating system", hw.platform)
        self._spec_row(self.page_area, "Processor", hw.cpu_name)
        self._spec_row(self.page_area, "Physical cores", str(hw.cpu_physical_cores) if hw.cpu_physical_cores else "Not reported by system")
        self._spec_row(self.page_area, "Logical threads", str(hw.cpu_logical_threads))
        self._spec_row(self.page_area, "Installed RAM", f"{hw.ram_total_mb:,} MB" if hw.ram_total_mb else "Unknown")
        self._spec_row(self.page_area, "Available RAM", f"{hw.ram_available_mb:,} MB" if hw.ram_available_mb else "Unknown")
        self._section(self.page_area, "Graphics processors")
        if not hw.gpus:
            ttk.Label(self.page_area, text="No graphics adapters reported.", style="Muted.TLabel").pack(anchor="w")
        for gpu in hw.gpus:
            panel = ttk.Frame(self.page_area, style="Panel.TFrame", padding=12); panel.pack(fill="x", pady=4)
            ttk.Label(panel, text=gpu.name, style="CardTitle.TLabel").pack(anchor="w")
            mem = f"{gpu.memory_total_mb:,} MB reported" if gpu.memory_total_mb is not None else "VRAM unknown / not reliably reported"
            ttk.Label(panel, text=f"{gpu.vendor} · {gpu.id} · {mem} · {gpu.backend_hint}",
                      background=PANEL, foreground=MUTED, wraplength=850).pack(anchor="w", pady=4)
        for note in hw.notes:
            ttk.Label(self.page_area, text="• " + note, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=3)

    def _spec_row(self, parent, label, value):
        row = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 9)); row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, background=PANEL, foreground=MUTED, width=22).pack(side="left")
        ttk.Label(row, text=value, background=PANEL, foreground=TEXT).pack(side="left")

    def _models_page(self):
        self._section(self.page_area, "Model & inference engine", "Choose the local runtime and model used by PrivateLM.")
        self._file_row(self.page_area, "llama-server.exe", self.server, self.pick_server)
        self._file_row(self.page_area, "GGUF model", self.model, self.pick_model)
        self._section(self.page_area, "Generation settings")
        for label, var in [("API port", self.port), ("Context length", self.ctx), ("Maximum output tokens", self.max_tokens),
                           ("Temperature", self.temperature), ("CPU threads", self.threads), ("GPU layers", self.ngl)]:
            self._field(self.page_area, label, var)
        ttk.Button(self.page_area, text="Detect llama.cpp devices", command=self.detect_llama_devices).pack(anchor="w", pady=10)
        ttk.Button(self.page_area, text="Save configuration", command=self._save_settings).pack(anchor="w")

    def _devices_page(self):
        self._section(self.page_area, "Device Cluster", "Pair Android devices and manage trusted workers on your private network.")
        ttk.Label(self.page_area, textvariable=self.cluster_status).pack(anchor="w", pady=4)
        row = ttk.Frame(self.page_area); row.pack(fill="x", pady=8)
        ttk.Button(row, text="Start secure cluster service", command=self.start_control).pack(side="left")
        ttk.Button(row, text="Generate pairing QR", command=self.new_pair_code).pack(side="left", padx=8)
        ttk.Button(row, text="Refresh pairing code", command=self.new_pair_code).pack(side="left")
        ttk.Label(self.page_area, textvariable=self.pair_code, foreground="#65b7ff").pack(anchor="w", pady=6)
        ttk.Label(self.page_area, textvariable=self.fingerprint, style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=4)
        self.qr_label = ttk.Label(self.page_area); self.qr_label.pack(anchor="center", pady=10)
        self.nodes = tk.Listbox(self.page_area, height=8, bg=PANEL2, fg=TEXT, selectbackground=BLUE, relief="flat")
        self.nodes.pack(fill="both", expand=True, pady=8)
        ttk.Button(self.page_area, text="Revoke selected device", command=self.revoke_selected).pack(anchor="e")
        ttk.Label(self.page_area, text="Pairing codes expire after five minutes and can only be used once. Use a trusted LAN or VPN; do not expose the host to the public internet.",
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=8)

    def _security_page(self):
        self._section(self.page_area, "Privacy & security", "Keep inference and device pairing private.")
        self._field(self.page_area, "Inference API key", self.key, "Separate from Device Cluster pairing credentials.")
        ttk.Button(self.page_area, text="Generate new API key", command=self.new_key).pack(anchor="w", pady=8)
        ttk.Label(self.page_area, text="The inference API key does not encrypt network traffic. Use a trusted private network or VPN and never port-forward this service.",
                  style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=10)

    def _startup_page(self):
        self._section(self.page_area, "Startup preferences")
        for label, value in [("Remember my settings", "remember"), ("Ask me on every startup", "ask")]:
            ttk.Radiobutton(self.page_area, text=label, value=value, variable=self.startup).pack(anchor="w", pady=8)
        self._field(self.page_area, "RAM budget (%)", self.ram_budget)
        ttk.Button(self.page_area, text="Save preferences", command=self._save_settings).pack(anchor="w", pady=12)

    def _logs_page(self):
        self._section(self.page_area, "Activity & inference logs")
        self.text = tk.Text(self.page_area, height=24, wrap="word", bg="#050c16", fg="#b9d7f5",
                            insertbackground=TEXT, relief="flat", font=("Consolas", 9))
        self.text.pack(fill="both", expand=True)
        self.log("PrivateLM dashboard ready.")
        self.log(f"Detailed inference log: {self.log_path}")

    def _settings_page(self):
        self._section(self.page_area, "Advanced settings", "Configuration options are separated from the main dashboard.")
        self._field(self.page_area, "Remote RPC nodes", self.remote_workers)
        self._field(self.page_area, "Local GPU device IDs", self.gpu_devices)
        self._field(self.page_area, "Execution mode", self.mode)
        self._field(self.page_area, "GPU policy", self.gpu_policy)
        self._field(self.page_area, "Image backend", self.image_backend)
        self._field(self.page_area, "Text size", self.text_scale)
        ttk.Button(self.page_area, text="Save settings", command=self._save_settings).pack(anchor="w", pady=10)

    def _field(self, parent, label, variable, hint=None):
        ttk.Label(parent, text=label, background=PANEL, foreground=TEXT).pack(anchor="w", pady=(10, 3))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.pack(fill="x", ipady=6)
        if hint:
            ttk.Label(parent, text=hint, background=PANEL, foreground=MUTED, wraplength=760).pack(anchor="w", pady=(2, 0))
        return entry

    def _show_page(self, index: int) -> None:
        self.page_index = index
        for child in self.page_area.winfo_children():
            child.destroy()
        titles = ["Identifying your hardware", "Choose your compute devices", "Memory and context", "Choose your AI engine", "Save and connect", "Your PrivateLM host"]
        self.page_title.set(titles[index])
        self.progress.set("SETUP COMPLETE" if index == 5 else f"STEP {index + 1} OF 5")
        self.back_button.configure(state="disabled" if index in (0, 5) else "normal")
        self.next_button.configure(text="Finish setup" if index == 4 else "Next", state="disabled" if index == 0 else "normal")
        if index == 0:
            ttk.Label(self.page_area, text="IDENTIFYING GPUs · CPU · RAM · VRAM", background=PANEL,
                      foreground="#65b7ff", font=("Segoe UI", 23, "bold")).pack(expand=True, pady=(45, 18))
            ttk.Label(self.page_area, text="PrivateLM is inspecting the hardware available to this computer.",
                      background=PANEL, foreground=MUTED, font=("Segoe UI", 12)).pack()
            self.hardware_summary = tk.StringVar(value="Scanning hardware…")
            ttk.Label(self.page_area, textvariable=self.hardware_summary, background=PANEL, foreground=TEXT,
                      justify="center", wraplength=760).pack(pady=28)
            self.root.after(900, lambda: self.next_button.configure(state="normal"))
        elif index == 1:
            ttk.Label(self.page_area, text="Choose where inference should run.", background=PANEL, foreground=MUTED).pack(anchor="w")
            self.compute_choice = getattr(self, "compute_choice", tk.StringVar(value=self.saved.get("compute_choice", "both")))
            for label, value in [("CPU only", "cpu"), ("GPU only", "gpu"), ("CPU + GPU", "both")]:
                ttk.Radiobutton(self.page_area, text=label, value=value, variable=self.compute_choice).pack(anchor="w", pady=8)
            self._field(self.page_area, "CPU threads to use (0 = automatic)", self.threads,
                        "The app detects logical threads. Leave 0 for the backend to choose automatically.")
            self._field(self.page_area, "GPU device IDs (comma-separated)", self.gpu_devices,
                        "Use Detect after selecting llama-server.exe on the engine screen. Hardware inventory alone does not guarantee backend support.")
            self._field(self.page_area, "GPU layers to offload (0 = CPU only)", self.ngl,
                        "Layer offload is the supported control; exact VRAM quotas are not generally enforceable.")
        elif index == 2:
            ttk.Label(self.page_area, text="Keep enough memory free for Windows and other apps.", background=PANEL, foreground=MUTED).pack(anchor="w")
            self._field(self.page_area, "RAM budget (%)", self.ram_budget, "Choose 10–70%. PrivateLM reserves at least 30% for the operating system; this is a policy, not a hard memory lock.")
            self._field(self.page_area, "Context length (tokens)", self.ctx, "How much conversation and prompt context the model can consider.")
            self._field(self.page_area, "Maximum output tokens", self.max_tokens, "Maximum generated response length. Must not exceed the context length.")
            self._field(self.page_area, "Temperature (0–2)", self.temperature, "Lower is more predictable; higher is more varied.")
            ttk.Button(self.page_area, text="Auto configure", command=self._auto_configure).pack(anchor="e", pady=18)
        elif index == 3:
            ttk.Label(self.page_area, text="Select the inference engine and model files.", background=PANEL, foreground=MUTED).pack(anchor="w", pady=(0, 8))
            self._file_row(self.page_area, "llama-server.exe", self.server, self.pick_server)
            self._file_row(self.page_area, "GGUF model", self.model, self.pick_model)
            ttk.Button(self.page_area, text="Detect available llama.cpp GPUs", command=self.detect_llama_devices).pack(anchor="w", pady=12)
            ttk.Label(self.page_area, text="Other compatible engines can be selected by pointing to their server executable when supported. This build currently launches llama.cpp server.", background=PANEL, foreground=MUTED, wraplength=760).pack(anchor="w", pady=8)
        elif index == 4:
            self.startup = getattr(self, "startup", tk.StringVar(value=self.saved.get("startup_behavior", "ask")))
            ttk.Label(self.page_area, text="How should PrivateLM handle these settings next time?", background=PANEL, foreground=MUTED).pack(anchor="w")
            for label, value in [("Save my settings", "remember"), ("Ask me on every startup", "ask")]:
                ttk.Radiobutton(self.page_area, text=label, value=value, variable=self.startup).pack(anchor="w", pady=10)
            self._field(self.page_area, "Host port", self.port, "Default: 8080")
            self._field(self.page_area, "Inference API key", self.key, "This key protects the OpenAI-compatible inference endpoint. Keep it private.")
            ttk.Label(self.page_area, text="The Device Cluster control service uses separate short-lived pairing codes and TLS certificate pinning.", background=PANEL, foreground=MUTED, wraplength=760).pack(anchor="w", pady=16)
        else:
            ttk.Label(self.page_area, text="Your host is ready to configure.", background=PANEL, foreground=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w", pady=(0, 12))
            ttk.Label(self.page_area, textvariable=self.status, background=PANEL, foreground="#65b7ff").pack(anchor="w", pady=4)
            ttk.Label(self.page_area, text="Inference API", background=PANEL, foreground=MUTED).pack(anchor="w", pady=(18, 3))
            ttk.Label(self.page_area, text=f"http://{lan_ip()}:{self.port.get()}/v1", background=PANEL, foreground=TEXT).pack(anchor="w")
            ttk.Label(self.page_area, text="Model alias: local-model", background=PANEL, foreground=MUTED).pack(anchor="w", pady=3)
            row = ttk.Frame(self.page_area, style="Panel.TFrame"); row.pack(fill="x", pady=18)
            ttk.Button(row, text="Start inference", command=self.start).pack(side="left")
            ttk.Button(row, text="Stop inference", command=self.stop).pack(side="left", padx=8)
            ttk.Button(row, text="Start Device Cluster service", command=self.start_control).pack(side="left", padx=8)
            ttk.Button(self.page_area, text="Create / refresh pairing code", command=self.new_pair_code).pack(anchor="w", pady=6)
            ttk.Label(self.page_area, textvariable=self.cluster_status, background=PANEL, foreground=MUTED).pack(anchor="w", pady=4)
            ttk.Label(self.page_area, textvariable=self.pair_code, background=PANEL, foreground="#65b7ff", font=("Consolas", 13, "bold")).pack(anchor="w", pady=4)
            ttk.Label(self.page_area, textvariable=self.fingerprint, background=PANEL, foreground=MUTED, wraplength=760).pack(anchor="w", pady=4)
            self.qr_label = ttk.Label(self.page_area, background=PANEL)
            self.qr_label.pack(anchor="center", pady=8)
            self.nodes = tk.Listbox(self.page_area, height=4, bg=PANEL2, fg=TEXT, selectbackground=BLUE, relief="flat")
            self.nodes.pack(fill="x", pady=10)
            ttk.Button(self.page_area, text="Revoke selected device", command=self.revoke_selected).pack(anchor="e")
            ttk.Label(self.page_area, text="Use only on a trusted private network or VPN. Never expose these services directly to the public internet.", background=PANEL, foreground=MUTED, wraplength=760).pack(anchor="w", pady=12)
            self.text = tk.Text(self.page_area, height=5, wrap="word", bg="#050c16", fg="#b9d7f5", insertbackground=TEXT, relief="flat", font=("Consolas", 9))
            self.text.pack(fill="both", expand=True, pady=(8, 0))
            self.log("PrivateLM host dashboard ready.")
            self.log(f"Detailed inference log: {self.log_path}")

    def _next_page(self) -> None:
        if self.page_index == 4:
            try:
                ClusterConfig(context_size=int(self.ctx.get()), max_output_tokens=int(self.max_tokens.get()),
                    temperature=float(self.temperature.get()), cpu_threads=int(self.threads.get() or 0),
                    ram_budget_percent=int(self.ram_budget.get()), execution_mode=self.mode.get(),
                    gpu_policy=self.gpu_policy.get(), image_backend=self.image_backend.get(),
                    text_scale=self.text_scale.get(), startup_behavior=self.startup.get()).validate()
                if not 1024 <= int(self.port.get()) <= 65535:
                    raise ValueError("Port must be between 1024 and 65535.")
                if len(self.key.get().strip()) < 16:
                    raise ValueError("API key must contain at least 16 characters.")
            except (ValueError, TypeError) as exc:
                messagebox.showerror(APP, str(exc)); return
            self._save_settings()
            self._show_page(5)
            return
        if self.page_index == 1:
            choice = self.compute_choice.get()
            self.gpu_policy.set("cpu" if choice == "cpu" else "single" if choice == "gpu" else "auto")
            if choice == "cpu": self.ngl.set("0")
        self._show_page(self.page_index + 1)

    def _previous_page(self) -> None:
        if self.page_index > 0 and self.page_index < 5:
            self._show_page(self.page_index - 1)

    def _auto_configure(self) -> None:
        self.threads.set("0")
        self.ram_budget.set("40")
        self.ctx.set("4096")
        self.max_tokens.set("512")
        self.temperature.set("0.7")
        self.ngl.set("0" if self.compute_choice.get() == "cpu" else "99")
        self.log("Applied conservative automatic defaults. GPU layer offload is still validated by llama.cpp at launch.")

    def apply_text_scale(self) -> None:
        scale = {"small": 0.88, "medium": 1.0, "large": 1.16}.get(self.text_scale.get(), 1.0)
        style = getattr(self, "style", ttk.Style(self.root))
        style.configure("TLabel", font=("Segoe UI", max(8, round(10 * scale))))
        style.configure("Muted.TLabel", font=("Segoe UI", max(8, round(10 * scale))))
        style.configure("Title.TLabel", font=("Segoe UI", max(16, round(24 * scale)), "bold"))
        style.configure("PanelTitle.TLabel", font=("Segoe UI", max(9, round(12 * scale)), "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", max(10, round(13 * scale)), "bold"))
        style.configure("TButton", font=("Segoe UI", max(8, round(9 * scale))))
        style.configure("TEntry", font=("Segoe UI", max(8, round(10 * scale))))
        style.configure("TCombobox", font=("Segoe UI", max(8, round(10 * scale))))
        if hasattr(self, "text"):
            self.text.configure(font=("Consolas", max(8, round(9 * scale))))

    def _section(self, parent: ttk.Frame, title: str, subtitle: str | None = None) -> None:
        ttk.Label(parent, text=title, style="Section.TLabel").pack(anchor="w", pady=(10, 6))
        if subtitle:
            ttk.Label(parent, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

    def _file_row(self, parent: ttk.Frame, label: str, var: tk.StringVar, command) -> None:
        row = ttk.Frame(parent); row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, style="Muted.TLabel", width=22).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        if command: ttk.Button(row, text="Browse…", command=command).pack(side="left", padx=6)

    def _choice(self, parent: ttk.Frame, label: str, var: tk.StringVar, values: list[str]) -> None:
        cell = ttk.Frame(parent, style="Panel.TFrame"); cell.pack(side="left", fill="x", expand=True, padx=3)
        ttk.Label(cell, text=label, background=PANEL, foreground=MUTED).pack(anchor="w")
        ttk.Combobox(cell, textvariable=var, values=values, state="readonly").pack(fill="x")

    def _detect_hardware(self) -> None:
        try:
            hw = detect_hardware()
            ram = f"{hw.ram_available_mb or '?'} MB available / {hw.ram_total_mb or '?'} MB total RAM"
            gpus = "; ".join(f"{g.name} ({g.memory_total_mb or 'VRAM unknown'} MB)" for g in hw.gpus) or "No GPU inventory available"
            self.hw = hw
            summary = f"{hw.platform} · {hw.cpu_name} · {hw.cpu_physical_cores or 'unknown'} physical cores / {hw.cpu_logical_threads} logical threads · {ram}\n{gpus}"
            self.hardware_text.set(summary)
            if hasattr(self, "hardware_summary"):
                self.hardware_summary.set(summary)
            if hasattr(self, "metric_values"):
                gpu_text = ", ".join((g.name.split("(")[0].strip() + " · " +
                    (f"{g.memory_total_mb} MB" if g.memory_total_mb is not None else "VRAM unknown")) for g in hw.gpus) or "No GPU detected"
                values = {"CPU": hw.cpu_name, "RAM": f"{(hw.ram_available_mb or 0)//1024:.1f} / {(hw.ram_total_mb or 0)//1024:.1f} GB", "GPU / VRAM": gpu_text, "Inference": self.status.get()}
                for card, title in self.metric_values:
                    children = card.winfo_children()
                    if title in values and len(children) > 1:
                        children[1].configure(text=values[title])
            self.threads.set(self.threads.get() if int(self.threads.get() or 0) > 0 else str(hw.cpu_logical_threads))
            self.log("Hardware inventory complete. Backend compatibility is checked separately at launch.")
        except Exception as exc:
            self.hardware_text.set(f"Hardware detection unavailable: {exc}")
            if hasattr(self, "hardware_summary"):
                self.hardware_summary.set(f"Hardware detection unavailable: {exc}")

    def pick_server(self) -> None:
        path = filedialog.askopenfilename(title="Select llama-server.exe", filetypes=[("Windows executable", "*.exe"), ("All files", "*.*")])
        if path: self.server.set(path)

    def pick_model(self) -> None:
        path = filedialog.askopenfilename(title="Select GGUF model", filetypes=[("GGUF model", "*.gguf"), ("All files", "*.*")])
        if path: self.model.set(path)

    def detect_llama_devices(self) -> None:
        exe = Path(self.server.get().strip())
        if not exe.is_file():
            messagebox.showwarning(APP, "Select llama-server.exe first."); return
        try:
            result = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            output = result.stdout + "\n" + result.stderr
            devices = []
            for line in output.splitlines():
                match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*\d+)\s*:", line)
                if match and match.group(1).upper() != "CPU": devices.append(match.group(1))
            if not devices:
                self.log("llama-server did not list GPU devices. Check that the EXE includes a GPU backend.")
                messagebox.showinfo(APP, "No GPU device IDs were parsed. Review the activity log and ensure your llama-server build includes a GPU backend.")
                return
            self.gpu_devices.set(",".join(dict.fromkeys(devices)))
            self.log("llama.cpp GPU devices: " + ", ".join(devices))
        except (OSError, subprocess.SubprocessError) as exc:
            messagebox.showerror(APP, f"Device detection failed: {exc}")

    def toggle_key(self) -> None:
        visible = self.key_entry.cget("show") != ""
        self.key_entry.configure(show="" if visible else "•")

    def copy_key(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.key.get())
            self.root.update()
            self.log("Inference API key copied to clipboard. Treat it like a password.")
        except tk.TclError as exc:
            messagebox.showerror(APP, f"Could not copy API key: {exc}")

    def new_key(self) -> None:
        self.key.set("plm_" + secrets.token_urlsafe(24))

    def start(self) -> None:
        if self.proc and self.proc.poll() is None: return
        exe, model = Path(self.server.get().strip()), Path(self.model.get().strip())
        if not exe.is_file() or not model.is_file() or model.suffix.lower() != ".gguf":
            messagebox.showerror(APP, "Choose a valid llama-server.exe and a local .gguf model."); return
        try:
            port, ctx, threads, ngl, tokens = map(int, (self.port.get(), self.ctx.get(), self.threads.get(), self.ngl.get(), self.max_tokens.get()))
            temperature = float(self.temperature.get())
            ClusterConfig(context_size=ctx, max_output_tokens=tokens, temperature=temperature, cpu_threads=threads,
                ram_budget_percent=int(self.ram_budget.get()), execution_mode=self.mode.get(),
                gpu_policy=self.gpu_policy.get(), image_backend=self.image_backend.get(),
                text_scale=self.text_scale.get(), startup_behavior=self.startup.get()).validate()
            if not (1024 <= port <= 65535 and threads >= 0 and ngl >= 0):
                raise ValueError("Invalid port, thread or GPU layer count")
        except (ValueError, TypeError) as exc:
            messagebox.showerror(APP, f"Check inference and cluster settings: {exc}"); return
        key = self.key.get().strip()
        if len(key) < 16:
            messagebox.showerror(APP, "API key must contain at least 16 characters."); return
        rpc = [x.strip() for x in self.remote_workers.get().split(",") if x.strip()]
        if self.mode.get() == "performance" and rpc:
            self.log("Performance mode ignores remote nodes; clear the RPC list or select a group mode.")
            rpc = []
        if self.mode.get() != "performance" and rpc:
            help_result = subprocess.run([str(exe), "--help"], capture_output=True, text=True,
                errors="replace", timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if "--rpc" not in (help_result.stdout + help_result.stderr):
                messagebox.showerror(APP, "This llama-server build does not advertise --rpc. Remote workers were not enabled. Use a build compiled with GGML_RPC."); return
        selected_devices = [x.strip() for x in self.gpu_devices.get().split(",") if x.strip()]
        if self.gpu_policy.get() == "single" and len(selected_devices) != 1:
            messagebox.showerror(APP, "Single GPU mode requires exactly one device ID. Click Detect llama.cpp devices and select one ID."); return
        ngl_effective = 0 if self.gpu_policy.get() == "cpu" else "all" if self.mode.get() == "extreme_force" else ngl
        cmd = [str(exe), "-m", str(model), "--host", "0.0.0.0", "--port", str(port), "-c", str(ctx),
               "-t", str(threads), "-ngl", str(ngl_effective), "-n", str(tokens), "--temp", str(temperature),
               "-a", "local-model", "--api-key", key]
        if selected_devices and self.gpu_policy.get() in ("single", "all_compatible"):
            help_text = help_result.stdout + help_result.stderr if rpc else subprocess.run(
                [str(exe), "--help"], capture_output=True, text=True, errors="replace", timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            if "--device" not in help_text:
                messagebox.showerror(APP, "This llama-server build does not advertise --device. GPU selection was not applied."); return
            cmd.extend(["--device", ",".join(selected_devices)])
        if rpc: cmd.extend(["--rpc", ",".join(rpc)])
        try:
            self._save_settings()
            with open(self.log_path, "a", encoding="utf-8", errors="replace") as log:
                log.write("\n\n=== PrivateLM inference started ===\n"); log.flush()
                self.proc = subprocess.Popen(cmd, cwd=str(exe.parent), stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.status.set("Starting inference…")
            self.log("Launching local inference. RPC nodes: " + (", ".join(rpc) if rpc else "none"))
            self.log(f"Android/provider base URL: http://{lan_ip()}:{port}/v1 · model: local-model")
            threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()
        except Exception as exc:
            self.log(f"Start failed: {exc}"); messagebox.showerror(APP, str(exc))

    def _watch(self, proc) -> None:
        code = proc.wait()
        self.log_queue.put(f"llama-server exited with code {code}. See {self.log_path}")
        self.root.after(0, lambda: self.status.set("Inference stopped"))

    def stop(self) -> None:
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired: proc.kill()
        self.proc = None; self.status.set("Inference stopped")
        self.log("Inference server stopped.")

    def start_control(self) -> None:
        if self.control:
            messagebox.showinfo(APP, "The secure Device Cluster service is already running."); return
        try:
            ip = lan_ip()
            cert, key, fingerprint = create_tls_identity(data_dir() / "tls", ip)
            self.control = ClusterControlServer(self.registry, cert, key, port=8765,
                on_log=lambda msg: self.log_queue.put(msg))
            self.control.start()
            self.cluster_status.set(f"HTTPS control service: https://{ip}:8765")
            self.fingerprint.set("SHA-256 certificate pin: " + fingerprint)
            self.new_pair_code()
            self.log("Device Cluster control plane started with TLS 1.2+ and certificate pinning support.")
        except Exception as exc:
            self.control = None
            messagebox.showerror(APP, f"Could not start secure cluster service: {exc}\n\nInstall dependencies with the Build-Windows-EXE script.")

    def stop_control(self) -> None:
        if self.control:
            self.control.stop(); self.control = None
        self.cluster_status.set("Cluster control stopped")
        self.pair_code.set("Start the secure cluster service to create a code")
        self.log("Device Cluster control service stopped.")

    def new_pair_code(self) -> None:
        if not self.control:
            messagebox.showwarning(APP, "Start the secure cluster service first."); return
        code, _expiry = self.registry.issue_pairing_code()
        self.pair_code.set(f"One-time pairing code: {code}  ·  valid for 5 minutes")
        payload = json.dumps({"service":"PrivateLM Device Cluster","coordinator":f"https://{lan_ip()}:8765",
            "pairing_code":code,"certificate_sha256":self.fingerprint.get().replace("SHA-256 certificate pin: ","")})
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=7, border=3)
        qr.add_data(payload); qr.make(fit=True)
        image = qr.make_image(fill_color="#07111f", back_color="#ffffff").convert("RGB")
        image.thumbnail((190, 190))
        self.qr_photo = ImageTk.PhotoImage(image)
        if hasattr(self, "qr_label"): self.qr_label.configure(image=self.qr_photo)
        self.log("Issued a short-lived, single-use pairing code and refreshed the QR payload. Android currently supports manual entry of these pairing details.")

    def publish_config(self) -> None:
        try:
            changes = {"execution_mode": self.mode.get(), "context_size": int(self.ctx.get()),
                "max_output_tokens": int(self.max_tokens.get()), "temperature": float(self.temperature.get()),
                "cpu_threads": int(self.threads.get()), "gpu_policy": self.gpu_policy.get(),
                "ram_budget_percent": int(self.ram_budget.get()), "image_backend": self.image_backend.get(),
                "startup_behavior": self.startup.get(), "text_scale": self.text_scale.get(),
                "selected_gpu_ids": [x.strip() for x in self.gpu_devices.get().split(",") if x.strip()],
                "model_label": Path(self.model.get()).name if self.model.get() else ""}
            config = self.registry.update_config(changes)
            self._save_settings()
            self.log(f"Published cluster settings revision {config['revision']} to paired members (members apply after heartbeat).")
            self._refresh_nodes()
        except Exception as exc:
            messagebox.showerror(APP, f"Settings were not published: {exc}")

    def _refresh_nodes(self) -> None:
        if hasattr(self, "nodes"):
            self.nodes.delete(0, "end")
            for node in self.registry.snapshot():
                status = "online" if node["online"] else "offline"
                ack = f"rev {node['config_ack_revision']} {'OK' if node['config_ack_ok'] else 'pending/rejected'}"
                self.nodes.insert("end", f"{node['id']}  |  {node['name']} ({node['platform']})  |  {status}  |  {ack}")
        self.root.after(2500, self._refresh_nodes)

    def revoke_selected(self) -> None:
        selection = self.nodes.curselection()
        if not selection: return
        node = self.registry.snapshot()[selection[0]]
        if messagebox.askyesno(APP, f"Revoke credentials for {node['name']}?"):
            self.registry.revoke(node["id"]); self._refresh_nodes(); self.log(f"Revoked device {node['name']}.")

    def log(self, message: str) -> None:
        if hasattr(self, "text"):
            self.text.configure(state="normal")
            self.text.insert("end", message.rstrip() + "\n")
            self.text.see("end"); self.text.configure(state="disabled")

    def _drain(self) -> None:
        while True:
            try: self.log(self.log_queue.get_nowait())
            except queue.Empty: break
        self.root.after(150, self._drain)

    def close(self) -> None:
        self.stop(); self.stop_control(); self.root.destroy()


def main() -> None:
    root = tk.Tk()
    HostApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
