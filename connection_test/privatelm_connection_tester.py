#!/usr/bin/env python3
"""PrivateLM Windows-to-Android connection tester.

Checks the Android PrivateLM API without starting a model or changing settings.
"""
from __future__ import annotations

import os
import queue
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

APP = "PrivateLM Connection Tester"


class Tester:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP)
        root.geometry("720x540")
        root.minsize(600, 440)
        self.events: queue.Queue[str] = queue.Queue()
        self.base = tk.StringVar(value="http://192.168.1.100:8080")
        self.key = tk.StringVar()
        self.status = tk.StringVar(value="Ready")
        self.log_path = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "PrivateLMConnectionTest" / "connection-test.log"
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._build()
        root.after(120, self._drain)

    def _build(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Test the connection from this Windows PC to the PrivateLM Android API. "
                 "No model is launched and no files on the phone are changed.",
            wraplength=670,
        ).pack(anchor="w", pady=(4, 14))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        ttk.Label(form, text="Android API address", width=20).grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.base).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(form, text="API key (if enabled)", width=20).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.key, show="•").grid(row=1, column=1, sticky="ew", pady=6)
        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=10)
        self.test_btn = ttk.Button(actions, text="Test Android connection", command=self.start_test)
        self.test_btn.pack(side="left")
        ttk.Label(actions, textvariable=self.status).pack(side="right")

        logs = ttk.LabelFrame(outer, text="Connection console", padding=8)
        logs.pack(fill="both", expand=True)
        self.output = tk.Text(logs, wrap="word", height=15, state="disabled", font=("Consolas", 9))
        self.output.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(logs, command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)
        self.write(f"Log file: {self.log_path}")
        self.write("On Android: open Server, enable Allow network access, start the server, then enter its Base URL here.")
        self.write("Use the phone's LAN IP, for example http://192.168.1.25:8080")

    def write(self, line: str):
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        message = f"[{stamp}] {line}"
        self.output.configure(state="normal")
        self.output.insert("end", message + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(message + "\n")
        except OSError:
            pass

    def start_test(self):
        if self.test_btn["state"] == "disabled":
            return
        raw = self.base.get().strip().rstrip("/")
        if not raw.startswith(("http://", "https://")):
            messagebox.showerror(APP, "Enter a full address such as http://192.168.1.25:8080")
            return
        self.test_btn.configure(state="disabled")
        self.status.set("Testing…")
        threading.Thread(target=self._test, args=(raw, self.key.get().strip()), daemon=True).start()

    def _request(self, url: str, key: str = "") -> tuple[int, str]:
        headers = {"User-Agent": "PrivateLM-Connection-Tester/1.0"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                return response.status, body
        except urllib.error.HTTPError as e:
            body = e.read(4096).decode("utf-8", errors="replace")
            return e.code, body
        except Exception as e:
            raise RuntimeError(f"{type(e).__name__}: {e}") from e

    def _test(self, base: str, key: str):
        self.events.put(f"Testing Android API at {base}")
        ok = True
        try:
            status, body = self._request(base + "/health")
            self.events.put(f"GET /health -> HTTP {status}: {body[:300]}")
            if not 200 <= status < 300:
                ok = False
                self.events.put("Health check failed. Confirm the phone server is running and network access is enabled.")
            else:
                status, body = self._request(base + "/v1/models", key)
                self.events.put(f"GET /v1/models -> HTTP {status}: {body[:600]}")
                if status == 401:
                    ok = False
                    self.events.put("Authentication failed: check the API key in Android Server settings.")
                elif not 200 <= status < 300:
                    ok = False
                    self.events.put("Models endpoint failed. Check the Android app logs for the matching [Connection] request.")
                else:
                    self.events.put("SUCCESS: Windows can reach the Android PrivateLM API.")
        except Exception as e:
            ok = False
            self.events.put(f"CONNECTION ERROR: {e}")
            self.events.put("Check same Wi-Fi, phone IP/port, Android Allow network access, and firewall/router isolation.")
        self.events.put("STATUS_OK" if ok else "STATUS_FAILED")

    def _drain(self):
        while True:
            try:
                line = self.events.get_nowait()
            except queue.Empty:
                break
            if line == "STATUS_OK":
                self.status.set("Connected")
                self.test_btn.configure(state="normal")
            elif line == "STATUS_FAILED":
                self.status.set("Connection failed")
                self.test_btn.configure(state="normal")
            else:
                self.write(line)
        self.root.after(120, self._drain)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    Tester(root)
    root.mainloop()


if __name__ == "__main__":
    main()
