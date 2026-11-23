# PrivateLM Device Cluster Implementation

## Product goals

PrivateLM shares one configuration and device-cluster model across Windows and Android. The Windows application is a coordinator/host; compatible Windows and Android devices can join as members. Android remains useful as a normal chat client when it is not contributing compute.

## Execution modes

1. Performance — run inference on one selected device and avoid remote-device overhead.
2. Performance Group — use supported local and remote devices. Each device retains its own RAM/VRAM; computation is partitioned by the inference backend.
3. Extreme Force — ask the backend to offload all model layers across all selected compatible accelerators. Preserve OS headroom and respect thermal, battery and device-owner limits. No promise of 100% utilization.

## Shared settings

The versioned schema includes execution mode, model label, context window, output-token limit, temperature, CPU threads, GPU policy and selected IDs, RAM budget, image backend, startup behavior and UI text scale. Members validate settings against local capabilities and acknowledge the applied revision or reject it with a reason.

## Security

- Pair through a short-lived, one-use code; do not put permanent credentials in QR content.
- Issue unique revocable device credentials and persist only credential hashes.
- Pin the self-signed TLS certificate on members before transmitting credentials.
- Keep raw inference RPC on a trusted isolated LAN/VPN only. The upstream llama.cpp RPC transport is experimental and insecure; the control plane does not make it safe.
- The inference HTTP API is LAN-only and should not be port-forwarded.

## Existing implementation to preserve

- Windows previously had a Python/Tkinter launcher for llama.cpp llama-server.
- Android already has ClusterService, ClusterView and native LlamaCluster RPC worker integration. Preserve and audit it rather than replacing it.
- Android has an OpenAI-compatible custom-provider path to use the Windows inference HTTP endpoint.

## Implemented in feature/device-cluster-foundation

- Windows hardware inventory for CPU, system RAM and installed GPU adapters; unknown VRAM is reported as unknown rather than guessed.
- Shared validated settings schema and safety bounds (RAM budget 10–70%, leaving at least 30% OS headroom; context/output-token validation).
- TLS 1.2+ HTTPS control service with a self-signed ECDSA certificate and SHA-256 fingerprint for client pinning.
- One-time 8-digit pairing codes (five-minute lifetime), rate-limited failed attempts, one credential per node, hashed credential persistence, heartbeat, versioned config delivery, acknowledgement state and revocation.
- Windows dashboard with performance/performance-group/extreme-force profiles, context/output/temperature/CPU/GPU-layer settings, device-ID discovery and optional RPC endpoint wiring.
- Windows workflow compiles, runs unit tests and builds a one-file EXE artifact.

## Still required before claiming the complete cross-platform product

- Android HTTPS client: certificate pinning, secure credential storage, QR/manual pairing, heartbeats, config validation and acknowledgements.
- Android Device Cluster UI rename and integration of shared settings while preserving the existing phone RPC cluster.
- Build and interoperability test the same RPC protocol/backend on Windows and Android; matching versions and backend support are required.
- Real device-by-device memory budgeting, thermal/battery guardrails and benchmarks. Current RAM budget is a policy field, not an enforced hard quota.
- Image-generation worker routing and backend support.
- Test the EXE on physical Windows hardware and verify firewall/network behavior.

## Acceptance criteria

- UI never claims a device/GPU participates unless the inference backend confirms it.
- Performance never attaches remote nodes.
- Group mode accepts more than three RPC endpoints if the backend and network support them.
- Extreme Force requests all compatible model layers but does not exceed OS/device budgets.
- Settings are revisioned and members report unsupported values rather than silently accepting them.
- Offline or revoked nodes cannot silently remain active participants.
