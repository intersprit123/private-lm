# PrivateLM Windows Host

The Windows companion provides a local llama-server launcher, hardware inventory, three execution profiles, optional llama.cpp RPC worker routing, and a TLS-protected Device Cluster control plane.

## Build

Requirements: Windows 10/11 x64, Python 3.10+, a compatible llama-server.exe, and a local GGUF model.

    Set-ExecutionPolicy -Scope Process Bypass
    .\Build-Windows-EXE.ps1

The EXE is written to windows_host\dist\PrivateLM-Windows-Host.exe.

## Inference setup

1. Select a compatible llama-server.exe and a GGUF model.
2. Choose context, output-token limit, temperature, CPU threads and GPU layers.
3. Use Detect llama.cpp devices to inspect identifiers exposed by that exact llama.cpp build. Single-GPU mode requires exactly one selected identifier.
4. Start inference. The base URL is http://<PC-LAN-IP>:8080/v1; model alias is local-model (the port is configurable).
5. In PrivateLM Android, configure a Custom OpenAI-compatible provider with the base URL, API key and model alias.

The launcher checks --device, --rpc, and --list-devices support before enabling those options. Unsupported features are not silently advertised as working.

## Execution profiles

- Performance: no remote RPC nodes are attached. The selected PC handles inference.
- Performance Group: all entered RPC worker endpoints are passed to llama-server --rpc, but only when the executable advertises RPC support.
- Extreme Force: asks llama.cpp to offload all model layers (-ngl all) across selected local devices and listed RPC endpoints. Actual use depends on compiled backends and device availability.

The RAM budget is a versioned resource policy distributed to members. This release does not impose a hard Windows job-object or VRAM quota on llama.cpp. The validator preserves at least 30% OS headroom; do not interpret the percentage as a measured or guaranteed allocation cap.

## Device Cluster control plane

Start Secure cluster service to create a TLS 1.2+ HTTPS control endpoint on port 8765. The UI issues an 8-digit, single-use pairing code; it expires after five minutes. A paired node receives a unique random credential. Only a SHA-256 hash of the credential is saved locally. Each member sends heartbeats, receives current versioned settings and reports whether it applied or rejected the revision. Devices can be revoked from the local UI.

The certificate is self-signed. A client must verify the displayed SHA-256 certificate fingerprint (pinning) before sending a pairing code or credential. See DEVICE_CLUSTER_API.md for the protocol.

The Windows API is implemented here. The Android app-side HTTPS client still needs to implement this pinning and heartbeat contract before Android master-controlled settings sync is operational. The existing Android native phone-worker RPC path is not replaced by this API.

## Important limitations

- llama.cpp RPC is experimental, fragile and insecure. Use it only on an isolated trusted LAN or VPN. Do not expose RPC ports to the public internet.
- The inference endpoint is HTTP in this release. Its API key does not encrypt traffic. Use only on a trusted private LAN/VPN; never port-forward it.
- VRAM is not physically pooled. Remote execution moves model data and computation via a compatible backend; each GPU retains its own memory.
- Android RPC and Windows llama.cpp binaries must use compatible RPC protocol/backend builds. Successful control-plane pairing does not prove RPC inference will work.
- Image-generation backend choice is shared as a setting, but this Windows host does not yet launch or coordinate an image-generation engine.
- Benchmark tokens/second on the actual network. Remote nodes can be slower due to synchronization overhead.
