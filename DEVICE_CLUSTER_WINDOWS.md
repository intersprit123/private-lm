# Android ↔ Windows Device Cluster setup

## Pair a phone as a coordinator member

1. On Windows, run PrivateLM-Windows-Host.exe.
2. Select **Start secure cluster service**. The host displays its HTTPS address and SHA-256 certificate fingerprint.
3. Select **Create one-time pairing code**. The code expires after five minutes and can be used once.
4. On Android, open **Device Cluster → Windows coordinator**.
5. Enter the Windows HTTPS address, the one-time code and the SHA-256 fingerprint exactly as shown. Pair.
6. Keep both devices on the same trusted private Wi-Fi network or a trusted VPN. The phone sends authenticated heartbeats every five seconds.

Android stores the unique device credential using platform secure storage. It is not included in the pairing code or QR. The Windows host stores only a credential hash and can revoke a device from its device list.

## What settings currently apply

Android validates the coordinator revision and applies supported generation defaults (context window, maximum output tokens and temperature) to its saved local settings. The app then reports whether the full revision is accepted or partially applied.

The current Android client explicitly reports unsupported settings such as remote compute mode, explicit GPU selection, non-default image backend, startup behavior or UI scaling rather than claiming they were applied.

## Important compute boundary

A successful Windows coordinator pairing only establishes an authenticated settings channel. It does not connect Android GPU memory to Windows inference.

The Android app already has a separate native llama.cpp RPC phone-worker service on port 50052. Its RPC worker is advertised with the rpc7 marker. The Windows host accepts RPC endpoints only when the selected llama.cpp server build advertises the --rpc flag; actual inference requires matching RPC protocol/build/backend support and physical-device testing. That interoperability has not yet been established in this branch.

llama.cpp currently warns that its RPC backend is experimental/insecure. Keep raw RPC and inference HTTP endpoints on a trusted isolated LAN/VPN and never port-forward them to the public internet. VRAM stays local to each physical GPU.

## Disconnect and revoke

Disconnect on Android deletes the saved local credential. To invalidate it immediately at the coordinator, select the phone in the Windows host and choose **Revoke selected device**. The Windows host considers a node offline after 15 seconds without a heartbeat.
