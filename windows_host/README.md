# PrivateLM Windows Host

A Windows desktop launcher for `llama.cpp`'s `llama-server.exe`. It runs a selected GGUF model on the Windows PC and exposes an authenticated OpenAI-compatible API over the private LAN. The existing PrivateLM Android app can connect through its **Custom** provider.

## Requirements

- Windows 10/11 x64.
- A Windows x64 llama.cpp build containing `llama-server.exe` (start with CPU build; try Vulkan only after CPU inference works).
- A GGUF model file.
- Python 3.10+ only if you want to build the EXE yourself.

## Build the EXE on Windows

Open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Build-Windows-EXE.ps1
```

The output is `dist\PrivateLM-Windows-Host.exe`. It is a self-contained PyInstaller executable; Python is not required on the target PC. A Windows executable must be built on Windows.

## Run

1. Open `PrivateLM-Windows-Host.exe`.
2. Browse to `llama-server.exe` and select a `.gguf` model.
3. Start with Port `8080`, Context `2048`, CPU threads `4`, GPU layers `0`.
4. Click **Start local AI server**.
5. Allow Windows Firewall access on **Private networks only**.

## Connect PrivateLM Android

Keep both devices on the same Wi-Fi. In PrivateLM, choose its **Custom** OpenAI-compatible provider:

- Base URL: `http://<WINDOWS-LAN-IP>:8080/v1`
- API key: the generated key shown in the Windows Host window
- Model: `local-model`

The Android custom provider appends `/chat/completions`, so include `/v1` exactly once.

## Security

The server binds to `0.0.0.0` for LAN access and requires an API key. Use only on a trusted private LAN. Do not port-forward this port to the public internet. The API key does not encrypt traffic; use HTTPS before exposing outside the trusted LAN.

## Performance

Begin with CPU mode (`-ngl 0`) to establish a stable baseline. A 4B Q4 model may fit in 16 GB system RAM depending on context size and background use. The laptop's 2 GB dedicated VRAM is not enough to assume full 4B offload. Test small nonzero GPU-layer values only after CPU mode is stable. RAM and VRAM are not one unified memory pool.
