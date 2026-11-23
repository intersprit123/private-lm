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
        self._build()
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
        values = {"server": self.server.get(), "model": self.model.get(), "port": self.port.get(),
                  "context_size": self.ctx.get(), "cpu_threads": self.threads.get(), "gpu_layers": self.ngl.get(),
                  "max_output_tokens": self.max_tokens.get(), "temperature": self.temperature.get(),
                  "ram_budget_percent": self.ram_budget.get(), "execution_mode": self.mode.get(),
                  "gpu_policy": self.gpu_policy.get(), "image_backend": self.image_backend.get(),
                  "text_scale": self.text_scale.get(), "startup_behavior": self.startup.get(),
                  "remote_workers": self.remote_workers.get(), "gpu_devices": self.gpu_devices.get()}
        self.state_path.write_text(json.dumps(values, indent=2), encoding="utf-8")

    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 24, "bold"))
        style.configure("PanelTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT, insertcolor=TEXT, bordercolor="#29415f")
        style.configure("TCombobox", fieldbackground=PANEL2, foreground=TEXT, background=PANEL2)
        style.configure("TButton", background="#1d4774", foreground=TEXT, padding=(12, 7), borderwidth=0)
        style.map("TButton", background=[("active", BLUE), ("disabled", "#26394e")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.configure("TSpinbox", fieldbackground=PANEL2, foreground=TEXT)

        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        outer = ttk.Frame(canvas, padding=20)
        window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        ttk.Label(outer, text="PrivateLM", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="LOCAL INFERENCE  ·  DISTRIBUTED DEVICE CONTROL", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        self._section(outer, "Hardware detected")
        ttk.Label(outer, textvariable=self.hardware_text, style="Muted.TLabel", wraplength=920).pack(fill="x", pady=(0, 12))
        self._section(outer, "Local inference engine")
        self._file_row(outer, "llama-server.exe", self.server, self.pick_server)
        self._file_row(outer, "GGUF model", self.model, self.pick_model)
        grid = ttk.Frame(outer); grid.pack(fill="x", pady=4)
        for i, (label, var) in enumerate((("API port", self.port), ("Context", self.ctx),
            ("CPU threads (0 = auto)", self.threads), ("GPU layers", self.ngl),
            ("Max output tokens", self.max_tokens), ("Temperature (0–2)", self.temperature))):
            cell = ttk.Frame(grid); cell.grid(row=i // 3, column=i % 3, sticky="ew", padx=5, pady=4)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=var).pack(fill="x")
        for i in range(3): grid.columnconfigure(i, weight=1)
        self._file_row(outer, "Remote RPC nodes", self.remote_workers, None)
        gpurow = ttk.Frame(outer); gpurow.pack(fill="x", pady=4)
        ttk.Label(gpurow, text="Local GPU device IDs", style="Muted.TLabel", width=22).pack(side="left")
        ttk.Entry(gpurow, textvariable=self.gpu_devices).pack(side="left", fill="x", expand=True)
        ttk.Button(gpurow, text="Detect llama.cpp devices", command=self.detect_llama_devices).pack(side="left", padx=6)
        ttk.Label(outer, text="Optional: exact IDs printed by this llama-server.exe --list-devices command. Single-GPU mode requires one ID.", style="Muted.TLabel", wraplength=920).pack(anchor="w", padx=6)
        ttk.Label(outer, text="Remote nodes use host:port values, require a llama-server build with GGML_RPC and must remain on an isolated trusted LAN/VPN.", style="Muted.TLabel", wraplength=920).pack(anchor="w", padx=6)
        keyrow = ttk.Frame(outer); keyrow.pack(fill="x", pady=5)
        ttk.Label(keyrow, text="Inference API key", style="Muted.TLabel", width=22).pack(side="left")
        ttk.Entry(keyrow, textvariable=self.key, show="•").pack(side="left", fill="x", expand=True)
        ttk.Button(keyrow, text="New key", command=self.new_key).pack(side="left", padx=6)
        actions = ttk.Frame(outer); actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Start inference", command=self.start).pack(side="left")
        ttk.Button(actions, text="Stop inference", command=self.stop).pack(side="left", padx=8)
        ttk.Label(actions, textvariable=self.status, style="Muted.TLabel").pack(side="right")
        self._section(outer, "Device Cluster · master settings")
        config = ttk.Frame(outer, style="Panel.TFrame", padding=12); config.pack(fill="x", pady=(0, 9))
        row = ttk.Frame(config, style="Panel.TFrame"); row.pack(fill="x")
        self._choice(row, "Execution mode", self.mode, ["performance", "performance_group", "extreme_force"])
        self._choice(row, "GPU policy", self.gpu_policy, ["auto", "cpu", "single", "all_compatible"])
        self._choice(row, "Image backend", self.image_backend, ["auto", "cpu", "gpu"])
        self._choice(row, "Text size", self.text_scale, ["small", "medium", "large"])
        row2 = ttk.Frame(config, style="Panel.TFrame"); row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="RAM budget % (10–70; at least 30% reserved for OS)", background=PANEL, foreground=MUTED).pack(side="left")
        ttk.Spinbox(row2, from_=10, to=70, width=6, textvariable=self.ram_budget).pack(side="left", padx=10)
        self._choice(row2, "Startup", self.startup, ["remember", "ask"])
        ttk.Button(config, text="Publish settings to paired devices", command=self.publish_config).pack(anchor="e", pady=(10, 0))
        control = ttk.Frame(outer, style="Panel.TFrame", padding=12); control.pack(fill="x", pady=(0, 10))
        ttk.Label(control, text="Secure pairing and device status", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(control, textvariable=self.cluster_status, background=PANEL, foreground=MUTED).pack(anchor="w", pady=3)
        row3 = ttk.Frame(control, style="Panel.TFrame"); row3.pack(fill="x", pady=5)
        ttk.Button(row3, text="Start secure cluster service", command=self.start_control).pack(side="left")
        ttk.Button(row3, text="Stop service", command=self.stop_control).pack(side="left", padx=8)
        ttk.Button(row3, text="Create one-time pairing code", command=self.new_pair_code).pack(side="left")
        ttk.Label(control, textvariable=self.pair_code, background=PANEL, foreground="#65b7ff", font=("Consolas", 11, "bold")).pack(anchor="w", pady=3)
        ttk.Label(control, textvariable=self.fingerprint, background=PANEL, foreground=MUTED, wraplength=900).pack(anchor="w")
        self.nodes = tk.Listbox(control, height=4, bg=PANEL2, fg=TEXT, selectbackground=BLUE, relief="flat")
        self.nodes.pack(fill="x", pady=7)
        ttk.Button(control, text="Revoke selected device", command=self.revoke_selected).pack(anchor="e")
        self._section(outer, "Activity and diagnostics")
        self.text = tk.Text(outer, height=9, wrap="word", bg="#050c16", fg="#b9d7f5",
                            insertbackground=TEXT, relief="flat", font=("Consolas", 9))
        self.text.pack(fill="both", expand=True)
        self.log("Choose llama-server.exe and a GGUF model. Hardware inventory is advisory; the backend must confirm GPU support.")
        self.log(f"Detailed inference log: {self.log_path}")
        ttk.Label(outer, text="Network note: the OpenAI-compatible inference endpoint is HTTP. Use only on a trusted private LAN or VPN; never port-forward it to the public internet.", style="Muted.TLabel", wraplength=920).pack(anchor="w", pady=10)

    def _section(self, parent: ttk.Frame, title: str) -> None:
        ttk.Label(parent, text=title, font=("Segoe UI", 13, "bold"), foreground="#65b7ff").pack(anchor="w", pady=(10, 6))

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
            self.hardware_text.set(f"{hw.platform} · {hw.cpu_name} · {hw.cpu_logical_threads} logical threads · {ram}\n{gpus}")
            self.threads.set(self.threads.get() if int(self.threads.get() or 0) > 0 else str(hw.cpu_logical_threads))
            self.log("Hardware inventory complete. Backend compatibility is checked separately at launch.")
        except Exception as exc:
            self.hardware_text.set(f"Hardware detection unavailable: {exc}")

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
        self.log("Issued a short-lived, single-use pairing code. It is not a permanent device key.")

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
