# PrivateLM Windows Host quick start

1. Download a Windows x64 llama-server.exe build and have a compatible GGUF model locally.
2. Download the PrivateLM Windows Host EXE from the latest successful Windows build workflow: https://github.com/intersprit123/private-lm/actions/workflows/windows-host.yml. Use the artifact from the run on feature/device-cluster-foundation.
3. Run the EXE, select the server and model, inspect hardware, set context/output tokens/temperature/CPU threads/GPU layers, then start inference.
4. Use Detect llama.cpp devices before selecting a single GPU. Remote nodes require a server build compiled with GGML_RPC and a compatible worker.
5. Provider base URL: http://<WINDOWS-LAN-IP>:8080/v1. The API key is shown in the app and the model alias is local-model.
6. Start Secure cluster service to issue a five-minute, single-use pairing code. The member client must pin the SHA-256 certificate fingerprint shown in the app before pairing.

## Execution profiles

- Performance uses the Windows PC only.
- Performance Group passes all listed host:port RPC workers to a compatible llama.cpp build.
- Extreme Force requests all model layers be offloaded to available compatible devices; actual utilization depends on hardware/backend support.

The control plane is HTTPS, but the inference provider endpoint is HTTP and its API key is not encrypted. llama.cpp RPC is experimental/insecure. Keep inference and RPC endpoints on a trusted private LAN or VPN only. Never port-forward them to the public internet.

Current integration status: the Windows host and secure settings/pairing control API are implemented in this branch. The Android client for this new control API and verified Android-to-Windows RPC interoperability are still follow-on integration work. Existing Android-native phone clustering is not silently assumed compatible.
