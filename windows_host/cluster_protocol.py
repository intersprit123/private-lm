"""Pinned-TLS pairing and master/member configuration control for PrivateLM.

This control plane does not carry model tensors. Raw llama.cpp RPC is separate,
experimental, and must only be used on an isolated trusted network/VPN.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

try:
    from .cluster_config import ClusterConfig
except ImportError:  # running the frozen/standalone GUI script
    from cluster_config import ClusterConfig

MAX_BODY = 64 * 1024
PAIR_TTL_SECONDS = 300


def create_tls_identity(directory: Path, host_ip: str) -> tuple[Path, Path, str]:
    """Create a self-signed ECDSA cert; clients must pin the returned SHA-256."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import datetime

    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "cluster-control.crt", directory / "cluster-control.key"
    if not cert_path.exists() or not key_path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PrivateLM Device Cluster")])
        san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(host_ip)))
        except ValueError:
            san.append(x509.DNSName(host_ip))
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=825))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    fingerprint = cert.fingerprint(hashes.SHA256()).hex().upper()
    return cert_path, key_path, fingerprint


class ClusterRegistry:
    """Thread-safe device registry; only credential hashes are persisted."""
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.lock = threading.RLock()
        self.config = ClusterConfig()
        self.nodes: dict[str, dict[str, Any]] = {}
        self.pair_hash: str | None = None
        self.pair_expires = 0.0
        self.pair_used = False
        self.failed_attempts: dict[str, tuple[int, float]] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.config = ClusterConfig.from_dict(data.get("config", {}))
            self.nodes = data.get("nodes", {})
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.nodes = {}
            self.config = ClusterConfig()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"config": self.config.to_dict(), "nodes": self.nodes}, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def issue_pairing_code(self) -> tuple[str, float]:
        with self.lock:
            code = f"{secrets.randbelow(100_000_000):08d}"
            self.pair_hash = hashlib.sha256(code.encode()).hexdigest()
            self.pair_expires = time.time() + PAIR_TTL_SECONDS
            self.pair_used = False
            return code, self.pair_expires

    def pair(self, source: str, code: str, identity: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            attempts, until = self.failed_attempts.get(source, (0, 0.0))
            if until > time.time():
                raise PermissionError("Too many pairing attempts. Try again later.")
            supplied = hashlib.sha256(str(code).encode()).hexdigest()
            valid = (self.pair_hash is not None and not self.pair_used
                     and time.time() <= self.pair_expires
                     and hmac.compare_digest(supplied, self.pair_hash))
            if not valid:
                attempts += 1
                self.failed_attempts[source] = (attempts, time.time() + 300 if attempts >= 8 else 0.0)
                raise PermissionError("Pairing code is invalid, expired or already used.")
            self.pair_used = True
            self.pair_hash = None
            self.failed_attempts.pop(source, None)
            token = secrets.token_urlsafe(32)
            node_id = secrets.token_hex(12)
            clean = {
                "id": node_id,
                "name": str(identity.get("name", "Device"))[:80],
                "platform": str(identity.get("platform", "unknown"))[:40],
                "capabilities": identity.get("capabilities", {}) if isinstance(identity.get("capabilities", {}), dict) else {},
                "credential_hash": hashlib.sha256(token.encode()).hexdigest(),
                "paired_at": int(time.time()),
                "last_seen": int(time.time()),
                "config_ack_revision": 0,
                "config_ack_ok": False,
                "config_ack_reason": "Awaiting first configuration acknowledgement",
                "status": "paired",
            }
            clean["capabilities"] = json.loads(json.dumps(clean["capabilities"]))
            if len(json.dumps(clean["capabilities"])) > 12_000:
                clean["capabilities"] = {"warning": "capability report was too large"}
            self.nodes[node_id] = clean
            self._save()
            return {"node_id": node_id, "credential": token, "config": self.config.to_dict()}

    def _auth(self, token: str) -> dict[str, Any]:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        for node in self.nodes.values():
            if hmac.compare_digest(hashed, node.get("credential_hash", "")):
                return node
        raise PermissionError("Device credential is invalid or has been revoked.")

    def heartbeat(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            node = self._auth(token)
            node["last_seen"] = int(time.time())
            if isinstance(payload.get("capabilities"), dict):
                caps = payload["capabilities"]
                if len(json.dumps(caps)) <= 12_000:
                    node["capabilities"] = caps
            node["status"] = str(payload.get("status", "online"))[:32]
            self._save()
            return {"node_id": node["id"], "config": self.config.to_dict()}

    def acknowledge(self, token: str, revision: int, accepted: bool, reason: str = "") -> None:
        with self.lock:
            node = self._auth(token)
            if revision < 1 or revision > self.config.revision:
                raise ValueError("Acknowledged settings revision is not current")
            node["config_ack_revision"] = revision
            node["config_ack_ok"] = bool(accepted)
            node["config_ack_reason"] = str(reason)[:400]
            node["last_seen"] = int(time.time())
            self._save()

    def update_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.config = self.config.next_revision(**changes)
            self._save()
            return self.config.to_dict()

    def revoke(self, node_id: str) -> bool:
        with self.lock:
            existed = self.nodes.pop(node_id, None) is not None
            if existed:
                self._save()
            return existed

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            result = []
            for node in self.nodes.values():
                item = {k: v for k, v in node.items() if k != "credential_hash"}
                item["online"] = int(time.time()) - int(item.get("last_seen", 0)) <= 15
                result.append(item)
            return result


class ClusterControlServer:
    def __init__(self, registry: ClusterRegistry, cert: Path, key: Path,
                 host: str = "0.0.0.0", port: int = 8765,
                 on_log: Callable[[str], None] | None = None):
        self.registry, self.host, self.port = registry, host, port
        self.on_log = on_log or (lambda _message: None)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "PrivateLM-Cluster/1"
            def log_message(self, fmt: str, *args: Any) -> None:
                owner.on_log("Cluster API: " + (fmt % args))
            def _send(self, status: int, data: dict[str, Any]) -> None:
                raw = json.dumps(data, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)
            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > MAX_BODY:
                    raise ValueError("Request body must be JSON and no larger than 64 KiB")
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("JSON body must be an object")
                return value
            def _token(self) -> str:
                value = self.headers.get("Authorization", "")
                if not value.startswith("Bearer ") or len(value) > 256:
                    raise PermissionError("Missing device credential")
                return value[7:]
            def do_GET(self) -> None:
                if self.path == "/health":
                    self._send(200, {"status": "ok", "service": "PrivateLM Device Cluster", "tls": True})
                elif self.path == "/api/v1/config":
                    try:
                        owner.registry._auth(self._token())
                        self._send(200, owner.registry.config.to_dict())
                    except PermissionError as exc:
                        self._send(401, {"error": str(exc)})
                else:
                    self._send(404, {"error": "Not found"})
            def do_POST(self) -> None:
                try:
                    body = self._body()
                    if self.path == "/api/v1/pair":
                        result = owner.registry.pair(self.client_address[0], str(body.get("code", "")), body)
                        self._send(200, result)
                    elif self.path == "/api/v1/heartbeat":
                        self._send(200, owner.registry.heartbeat(self._token(), body))
                    elif self.path == "/api/v1/ack":
                        owner.registry.acknowledge(self._token(), int(body.get("revision", 0)),
                            body.get("accepted") is True, str(body.get("reason", "")))
                        self._send(200, {"ok": True})
                    else:
                        self._send(404, {"error": "Not found"})
                except PermissionError as exc:
                    self._send(403, {"error": str(exc)})
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._send(400, {"error": str(exc)})
                except Exception as exc:
                    owner.on_log(f"Cluster API error: {exc}")
                    self._send(500, {"error": "Internal server error"})
            def do_PUT(self) -> None:
                self._send(405, {"error": "Method not allowed"})
            def do_DELETE(self) -> None:
                self._send(405, {"error": "Method not allowed; revoke devices in the local host UI"})

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="PrivateLM-Cluster-HTTPS", daemon=True)
        self.thread.start()
        self.on_log(f"Secure device-control service listening on https://{self.host}:{self.port}")

    def stop(self) -> None:
        if self.thread and self.thread.is_alive():
            self.httpd.shutdown()
            self.thread.join(timeout=4)
        self.httpd.server_close()
