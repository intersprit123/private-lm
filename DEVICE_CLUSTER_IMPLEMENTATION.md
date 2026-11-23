# PrivateLM Device Cluster Implementation Plan

## Product goals

PrivateLM will share one configuration and device-cluster model across Windows and Android. The Windows application is the coordinator/host; compatible Windows and Android devices can join as members. The Android app remains useful as a normal chat client even when it is not contributing compute.

## Execution modes

1. **Performance** — run inference on one selected device. Prefer its best supported local accelerator and avoid remote-device communication overhead.
2. **Performance Group** — distribute a model/workload across selected compatible devices. Each device retains its own RAM and VRAM; the coordinator schedules supported partitions and accounts for network transfer and synchronization costs.
3. **Extreme Force** — attempt to involve all selected compatible accelerators and use a user-configured higher per-device memory budget. Always enforce OS headroom, thermal/power limits, backend constraints, and device-owner safety limits. Never promise 100% utilization or reserve all system RAM.

## Shared settings

The versioned cluster configuration will cover execution mode, model identity, context length, maximum output tokens, CPU threads, GPU policy, per-device memory budgets, image-generation backend, UI text scale, and startup behavior. The master publishes cluster-wide settings; each member validates them against local capabilities and safety limits before acknowledging application. Unsupported settings are reported to the master instead of being silently accepted.

## Pairing and security

- Pair devices using a short-lived QR pairing token; do not embed a permanent API key in QR contents.
- Issue a unique revocable credential to each paired device.
- Keep discovery and compute endpoints on trusted networks; require authenticated requests.
- Do not expose unauthenticated RPC endpoints to a LAN or the public internet.
- Use TLS or a trusted VPN for connections beyond a protected local network.

## Existing implementation to preserve

- Windows branch currently provides a Python/Tkinter launcher for llama.cpp `llama-server` with an OpenAI-compatible API.
- Android already has a `ClusterService` and native `LlamaCluster` integration for Android/iOS worker discovery, QR/manual pairing, worker status and model-split planning. This must be audited and extended rather than replaced.
- Android already supports connecting to an OpenAI-compatible provider, which can remain the chat transport to a Windows host.

## Distributed inference reality

VRAM is not physically pooled or transferred between devices. Distributed inference must use a backend that supports remote execution/partitioning. Local multi-GPU llama.cpp options and remote RPC are different mechanisms and have different compatibility/performance characteristics. Android GPU participation requires a compatible native compute backend; pairing a phone as a chat client does not make its GPU available automatically.

## Delivery milestones

1. Audit current Android cluster/native backend and Windows launcher; document supported platforms and gaps.
2. Define shared, versioned configuration schema and validation.
3. Implement secure pairing, node identity, capability reporting and master/member settings synchronization.
4. Implement Windows animated onboarding/dashboard and hardware detection.
5. Integrate the Android Device Cluster tab and shared settings while preserving existing cluster behavior.
6. Add/validate actual distributed inference backend paths (local multi-GPU and remote nodes), with benchmarks and fallback behavior.
7. Add image-generation device selection only for supported backends.
8. Build and test Windows/Android artifacts and report exactly which modes are operational.

## Acceptance criteria

- The UI never advertises a device/GPU as participating unless the backend confirms it.
- Performance mode does not schedule remote nodes.
- Performance Group can use more than three registered nodes when the selected backend and network support it.
- Extreme Force applies configurable per-node memory budgets but preserves OS headroom and device safety limits.
- Master changes are versioned, acknowledged, and rejected with a clear reason when a member cannot apply them.
- Tests cover offline nodes, incompatible GPUs, insufficient memory, pairing revocation, stale configuration and fallback to a single device.
