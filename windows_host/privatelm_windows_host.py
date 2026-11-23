#!/usr/bin/env python3
"""PrivateLM Windows Host: GUI launcher for llama.cpp llama-server."""
from __future__ import annotations
import os, queue, secrets, socket, subprocess, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP = "PrivateLM Windows Host"

def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80)); return s.getsockname()[0]
    except OSError: return "127.0.0.1"
    finally: s.close()

class HostApp:
    def __init__(self, root):
        self.root=root; root.title(APP); root.geometry("760x640"); root.minsize(680,560)
        self.proc=None; self.log_queue=queue.Queue(); self.key_visible=False
        self.log_path=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"PrivateLMWindows"/"llama-server.log"
        self.log_path.parent.mkdir(parents=True,exist_ok=True)
        self.server=tk.StringVar(); self.model=tk.StringVar(); self.port=tk.StringVar(value="8080")
        self.ctx=tk.StringVar(value="2048"); self.threads=tk.StringVar(value="4"); self.ngl=tk.StringVar(value="0")
        self.key=tk.StringVar(value="plm_"+secrets.token_urlsafe(24)); self.status=tk.StringVar(value="Stopped")
        self._build(); root.after(150,self._drain); root.protocol("WM_DELETE_WINDOW",self.close)
    def _build(self):
        outer=ttk.Frame(self.root,padding=14); outer.pack(fill="both",expand=True)
        ttk.Label(outer,text=APP,font=("Segoe UI",18,"bold")).pack(anchor="w")
        ttk.Label(outer,text="Run a local GGUF model on this PC and expose an authenticated OpenAI-compatible API to PrivateLM Android.",wraplength=700).pack(anchor="w",pady=(3,12))
        form=ttk.Frame(outer); form.pack(fill="x")
        self._file_row(form,0,"llama-server.exe",self.server,self.pick_server)
        self._file_row(form,1,"GGUF model",self.model,self.pick_model)
        self._entry_row(form,2,"Port",self.port); self._entry_row(form,3,"Context size",self.ctx)
        self._entry_row(form,4,"CPU threads",self.threads); self._entry_row(form,5,"GPU layers (-ngl)",self.ngl)
        row=ttk.Frame(form); row.grid(row=6,column=0,columnspan=3,sticky="ew",padx=12,pady=5)
        ttk.Label(row,text="API key",width=18).pack(side="left")
        self.key_entry=ttk.Entry(row,textvariable=self.key,show="•"); self.key_entry.pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="Show / hide",command=self.toggle_key).pack(side="left",padx=5)
        ttk.Button(row,text="New key",command=self.new_key).pack(side="left")
        actions=ttk.Frame(outer); actions.pack(fill="x",pady=10)
        self.start_btn=ttk.Button(actions,text="Start local AI server",command=self.start); self.start_btn.pack(side="left")
        self.stop_btn=ttk.Button(actions,text="Stop server",command=self.stop,state="disabled"); self.stop_btn.pack(side="left",padx=8)
        ttk.Label(actions,textvariable=self.status).pack(side="right")
        info=ttk.LabelFrame(outer,text="Connect PrivateLM Android",padding=10); info.pack(fill="x",pady=(2,10))
        self.url=ttk.Label(info,text=f"Base URL: http://{lan_ip()}:8080/v1",font=("Consolas",10)); self.url.pack(anchor="w")
        ttk.Label(info,text="In PrivateLM → Custom provider: use the Base URL above, this API key, and model name local-model.",wraplength=690).pack(anchor="w",pady=(5,0))
        ttk.Label(info,text="Keep both devices on the same Wi-Fi. Allow the Windows Firewall prompt for Private networks only.",wraplength=690).pack(anchor="w",pady=(4,0))
        logs=ttk.LabelFrame(outer,text="Activity",padding=8); logs.pack(fill="both",expand=True)
        self.text=tk.Text(logs,height=13,wrap="word",state="disabled",font=("Consolas",9)); self.text.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(logs,command=self.text.yview); scroll.pack(side="right",fill="y"); self.text.configure(yscrollcommand=scroll.set)
        self.log("Choose llama-server.exe and a GGUF model, then start the server.")
        self.log(f"Detailed llama.cpp log: {self.log_path}")
    def _file_row(self,parent,row,label,var,fn):
        f=ttk.Frame(parent); f.grid(row=row,column=0,columnspan=3,sticky="ew",padx=12,pady=5)
        ttk.Label(f,text=label,width=18).pack(side="left"); ttk.Entry(f,textvariable=var).pack(side="left",fill="x",expand=True)
        ttk.Button(f,text="Browse…",command=fn).pack(side="left",padx=(6,0))
    def _entry_row(self,parent,row,label,var):
        f=ttk.Frame(parent); f.grid(row=row,column=0,columnspan=3,sticky="ew",padx=12,pady=5)
        ttk.Label(f,text=label,width=18).pack(side="left"); ttk.Entry(f,textvariable=var,width=12).pack(side="left")
    def pick_server(self):
        p=filedialog.askopenfilename(title="Select llama-server.exe",filetypes=[("Windows executable","*.exe"),("All files","*.*")])
        if p:self.server.set(p)
    def pick_model(self):
        p=filedialog.askopenfilename(title="Select GGUF model",filetypes=[("GGUF models","*.gguf"),("All files","*.*")])
        if p:self.model.set(p)
    def toggle_key(self):
        self.key_visible=not self.key_visible; self.key_entry.configure(show="" if self.key_visible else "•")
    def new_key(self): self.key.set("plm_"+secrets.token_urlsafe(24))
    def log(self,msg):
        self.text.configure(state="normal"); self.text.insert("end",msg.rstrip()+"\n"); self.text.see("end"); self.text.configure(state="disabled")
    def _drain(self):
        while True:
            try:self.log(self.log_queue.get_nowait())
            except queue.Empty:break
        self.root.after(150,self._drain)
    def start(self):
        if self.proc and self.proc.poll() is None:return
        exe=Path(self.server.get().strip()); model=Path(self.model.get().strip())
        if not exe.is_file(): messagebox.showerror(APP,"Choose a valid llama-server.exe."); return
        if not model.is_file() or model.suffix.lower()!=".gguf": messagebox.showerror(APP,"Choose a valid .gguf model."); return
        try:
            port,ctx,threads,ngl=map(int,(self.port.get(),self.ctx.get(),self.threads.get(),self.ngl.get()))
            if not(1024<=port<=65535 and ctx>=256 and threads>=1 and ngl>=0):raise ValueError()
        except ValueError: messagebox.showerror(APP,"Check port, context, threads and GPU layer values."); return
        key=self.key.get().strip()
        if len(key)<16: messagebox.showerror(APP,"API key must be at least 16 characters."); return
        cmd=[str(exe),"-m",str(model),"--host","0.0.0.0","--port",str(port),"-c",str(ctx),"-t",str(threads),"-ngl",str(ngl),"-a","local-model","--api-key",key]
        try:
            with open(self.log_path,"a",encoding="utf-8",errors="replace") as log:
                log.write("\n\n=== PrivateLM Windows Host started ===\n"); log.flush()
                self.proc=subprocess.Popen(cmd,cwd=str(exe.parent),stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            self.log("Starting llama-server…"); self.log("Command: "+subprocess.list2cmdline(cmd))
            self.status.set("Starting…"); self.start_btn.configure(state="disabled"); self.stop_btn.configure(state="normal")
            self.url.configure(text=f"Base URL: http://{lan_ip()}:{port}/v1")
            threading.Thread(target=self._watch,args=(self.proc,),daemon=True).start()
        except Exception as e: self.log(f"Start failed: {e}"); messagebox.showerror(APP,str(e))
    def _watch(self,proc):
        code=proc.wait(); self.log_queue.put(f"llama-server exited with code {code}. See {self.log_path}")
        self.root.after(0,self._stopped)
    def _stopped(self):
        self.status.set("Stopped"); self.start_btn.configure(state="normal"); self.stop_btn.configure(state="disabled"); self.proc=None
    def stop(self):
        p=self.proc
        if p and p.poll() is None:
            self.log("Stopping llama-server…"); p.terminate()
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill()
        self._stopped()
    def close(self): self.stop(); self.root.destroy()

def main():
    root=tk.Tk()
    try:ttk.Style().theme_use("vista")
    except tk.TclError:pass
    HostApp(root); root.mainloop()

if __name__=="__main__":main()
