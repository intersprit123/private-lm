# Device Cluster control API (schema v1)

Base URL: https://<coordinator-lan-ip>:8765. The server uses a self-signed ECDSA certificate. Before sending any secret, the client MUST pin the SHA-256 fingerprint shown by the coordinator UI and compare it with the peer certificate on every connection. Do not disable TLS verification globally.

## Pairing

The coordinator issues an 8-digit, single-use code with a five-minute lifetime. Pairing is allowed once per code; failed attempts are rate-limited by source IP.

POST /api/v1/pair

    {
      "code": "12345678",
      "name": "Android tablet",
      "platform": "Android",
      "capabilities": {
        "ram_total_mb": 8192,
        "ram_available_mb": 4096,
        "gpus": []
      }
    }

Success returns node_id, a per-device credential (shown only once), and the current config. Store the credential in the platform secure credential store, not in a QR code or ordinary preferences. Pairing response: 200; invalid/expired/used code: 403; malformed request: 400.

## Windows GPU selection from a paired device

An authenticated member may POST `/api/v1/compute` with `execution_mode` (`performance` or `extreme_force`), `gpu_policy` (`single` or `all_compatible`), and `selected_gpu_ids`. IDs must come from the Windows host detected llama.cpp GPU inventory. This changes the Windows host inference settings; it does not combine GPU memory across devices.

## Authenticated member endpoints

Send Authorization: Bearer <credential> over the fingerprint-pinned TLS connection.

- GET /api/v1/config — current versioned settings.
- POST /api/v1/heartbeat — member liveness and capability/status update. The response includes the canonical coordinator config.
- POST /api/v1/ack — acknowledge a revision with revision, accepted and an optional short reason.

Heartbeat example:

    {
      "status": "ready",
      "capabilities": {
        "platform": "Android",
        "ram_total_mb": 8192,
        "ram_available_mb": 3200,
        "gpus": [{"name": "Adreno", "backend_hint": "Vulkan; not yet RPC-verified"}]
      }
    }

The coordinator considers a node online for 15 seconds after its last heartbeat. Requests are limited to 64 KiB. Unknown routes and methods are rejected. A revoked credential is immediately invalid.

## Versioned configuration fields

schema_version, revision, execution_mode, model_label, context_size, max_output_tokens, temperature, cpu_threads, gpu_policy, ram_budget_percent, image_backend, startup_behavior, text_scale and selected_gpu_ids.

Execution modes are performance, performance_group and extreme_force. The RAM policy range is 10–70%, leaving at least 30% for the OS. Members must independently validate incoming settings against local thermal, battery, memory and backend constraints before applying them; unsupported configurations must be acknowledged as rejected with a reason.

This is a control plane, not an inference transport. It does not forward tensors, model files or RPC commands. Remote inference is a separate backend capability and must not be inferred from successful pairing.


## Worker health and memory accounting (protocol v1)

Members may report `worker_state` (`starting`, `ready`, `busy`, `stopped`, or `error`), `native_rpc_version`, `worker_throttled`, `worker_memory_available_mb`, and `worker_memory_held_mb`. The coordinator exposes `worker_ready`, `compute_eligible`, and a per-device `memory` summary in its local device snapshot. Eligibility requires a fresh heartbeat, a ready worker, rpc7, and no reported Android throttling.

Memory values are per-device estimates, not pooled physical RAM. The safe worker budget is reported separately from total free memory, and the coordinator clamps untrusted numeric reports. Eligibility is only a scheduling prerequisite; it does not prove tensor execution or Windows↔Android RPC interoperability.


## Worker task queue (protocol v1 extension)

Windows accepts only the allowlisted task types worker_probe, memory_report, and benchmark. An authenticated member polls GET /api/v1/tasks; tasks are scoped to that device credential. Members report progress using POST /api/v1/tasks/{task_id}/status with status (running, completed, or failed), progress (0–100), and optional bounded result or error objects.

Each assignment has a 30-second lease and at most three attempts. Expired leases or offline workers are reassigned to another eligible worker when available; otherwise the task is marked failed. Task payloads and results are limited to 8 KiB. This is control-plane groundwork: current Android builds do not yet poll this endpoint or execute these task types, so a queued health check waits until Android worker polling is implemented. It does not execute arbitrary commands or perform distributed inference.
