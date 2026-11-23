# PrivateLM Android + Windows host setup

The Android app uses the existing Custom OpenAI-compatible provider in `CloudService`. The Windows companion launches llama.cpp's `llama-server` and serves `/v1/chat/completions`.

## Android connection values

Use these values in the Custom provider screen after starting the Windows host:

- Base URL: `http://<PC-LAN-IP>:8080/v1` (do not append `/chat/completions`)
- Model: `local-model`
- API key: copy the key from the Windows host window

## Build artifacts

- Android branch: `.github/workflows/android-apk.yml` builds an arm64 release APK using CI debug signing for testing and uploads it as a workflow artifact. This is not a Play Store signing configuration.
- Windows branch: `.github/workflows/windows-host.yml` packages the Python launcher into a Windows x64 EXE and uploads it as a workflow artifact.

The Windows EXE requires a separate compatible `llama-server.exe` and a GGUF model. It is a host launcher, not a complete native Windows Flutter app.
