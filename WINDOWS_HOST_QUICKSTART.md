# PrivateLM Windows Host quick start

This Windows companion runs the external `llama-server.exe` process and exposes its OpenAI-compatible API on your private LAN. It is not a Windows port of the Flutter chat UI.

1. Download a Windows x64 `llama-server.exe` build from the official llama.cpp releases and have a compatible `.gguf` model available locally.
2. Run `PrivateLM-Windows-Host.exe` from the GitHub Actions artifact or build it with `windows_host/Build-Windows-EXE.ps1`.
3. Select `llama-server.exe` and the `.gguf` model. Start with context `2048`, CPU threads suited to your PC, and GPU layers `0`; test Vulkan offload only after CPU baseline works.
4. Start the server. Keep Windows Firewall access limited to **Private networks**. Do not port-forward this service to the public internet.
5. In PrivateLM Android, add a Custom OpenAI-compatible provider:
   - Name: `My Windows PC`
   - Base URL: `http://<WINDOWS-LAN-IP>:8080/v1`
   - API key: the key shown in the host app
   - Model: `local-model`
6. Ensure both devices are on the same trusted Wi-Fi network. Android cleartext HTTP is enabled for LAN connectivity in this app; avoid using this configuration on untrusted networks.

The API key is a LAN access control, not encryption. Use a trusted network or configure HTTPS/reverse-proxy protection before exposing the endpoint beyond your LAN.
