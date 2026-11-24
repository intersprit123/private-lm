import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Android member client for the Windows Device Cluster control plane.
/// This syncs settings only; it does not transport tensors or enable GPU sharing.
class WindowsClusterClient {
  WindowsClusterClient({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _hostKey = 'windows_cluster_host';
  static const _pinKey = 'windows_cluster_tls_pin';
  static const _credentialKey = 'windows_cluster_device_credential';
  bool _pinMismatch = false;

  Future<bool> get isPaired async =>
      (await _storage.read(key: _credentialKey))?.isNotEmpty == true;

  Future<String?> get coordinator async => _storage.read(key: _hostKey);

  Future<Map<String, dynamic>> pair({
    required String baseUrl,
    required String code,
    required String certificateFingerprint,
    required Map<String, dynamic> identity,
  }) async {
    final base = _normaliseBase(baseUrl);
    final pin = _normalisePin(certificateFingerprint);
    if (!RegExp(r'^\d{8}$').hasMatch(code.trim())) {
      throw const FormatException('Enter the eight-digit one-time pairing code.');
    }
    final response = await _request(
      base: base, pin: pin, path: '/api/v1/pair', method: 'POST',
      body: {'code': code.trim(), ...identity}, authenticated: false,
    );
    final token = response['credential'];
    if (token is! String || token.length < 32) {
      throw const FormatException('The coordinator returned an invalid device credential.');
    }
    await _storage.write(key: _hostKey, value: base);
    await _storage.write(key: _pinKey, value: pin);
    await _storage.write(key: _credentialKey, value: token);
    final config = response['config'];
    if (config is Map) return Map<String, dynamic>.from(config);
    return <String, dynamic>{};
  }

  Future<Map<String, dynamic>> heartbeat(Map<String, dynamic> capabilities) async {
    final base = await _storage.read(key: _hostKey);
    final pin = await _storage.read(key: _pinKey);
    final token = await _storage.read(key: _credentialKey);
    if (base == null || pin == null || token == null) {
      throw StateError('This device is not paired with a Windows coordinator.');
    }
    final response = await _request(
      base: base, pin: pin, token: token, path: '/api/v1/heartbeat',
      method: 'POST', body: {'status': capabilities['worker_state']?.toString() ?? 'online', 'capabilities': capabilities},
      authenticated: true,
    );
    final config = response['config'];
    if (config is Map) return Map<String, dynamic>.from(config);
    throw const FormatException('The coordinator did not return cluster settings.');
  }

  Future<void> acknowledge({
    required int revision,
    required bool accepted,
    required String reason,
  }) async {
    final base = await _storage.read(key: _hostKey);
    final pin = await _storage.read(key: _pinKey);
    final token = await _storage.read(key: _credentialKey);
    if (base == null || pin == null || token == null) throw StateError('This device is not paired.');
    await _request(
      base: base, pin: pin, token: token, path: '/api/v1/ack', method: 'POST',
      body: {'revision': revision, 'accepted': accepted, 'reason': reason},
      authenticated: true,
    );
  }

  Future<Map<String, dynamic>> setComputeOptions({
    required String executionMode,
    required String gpuPolicy,
    required List<String> selectedGpuIds,
  }) async {
    final base = await _storage.read(key: _hostKey);
    final pin = await _storage.read(key: _pinKey);
    final token = await _storage.read(key: _credentialKey);
    if (base == null || pin == null || token == null) throw StateError("This device is not paired with a Windows coordinator.");
    return _request(base: base, pin: pin, token: token, path: "/api/v1/compute", method: "POST", body: {
      "execution_mode": executionMode, "gpu_policy": gpuPolicy, "selected_gpu_ids": selectedGpuIds,
    }, authenticated: true);
  }
  /// Fetches only tasks assigned to this paired Android device.
  Future<List<Map<String, dynamic>>> pollTasks() async {
    final base = await _storage.read(key: _hostKey);
    final pin = await _storage.read(key: _pinKey);
    final token = await _storage.read(key: _credentialKey);
    if (base == null || pin == null || token == null) {
      throw StateError('This device is not paired with a Windows coordinator.');
    }
    final response = await _request(
      base: base,
      pin: pin,
      token: token,
      path: '/api/v1/tasks',
      method: 'GET',
      body: const <String, dynamic>{},
      authenticated: true,
    );
    final raw = response['tasks'];
    if (raw is! List) {
      throw const FormatException('The coordinator returned an invalid task list.');
    }
    return raw
        .whereType<Map>()
        .map((task) => Map<String, dynamic>.from(task))
        .toList(growable: false);
  }

  /// Reports bounded task progress/results to the coordinator.
  Future<Map<String, dynamic>> updateTaskStatus({
    required String taskId,
    required String status,
    int progress = 0,
    Map<String, dynamic>? result,
    String error = '',
  }) async {
    if (!RegExp(r'^[0-9a-fA-F]{24}$').hasMatch(taskId) ||
        !['running', 'completed', 'failed'].contains(status) ||
        progress < 0 ||
        progress > 100) {
      throw const FormatException('Invalid worker task ID, status or progress.');
    }
    final base = await _storage.read(key: _hostKey);
    final pin = await _storage.read(key: _pinKey);
    final token = await _storage.read(key: _credentialKey);
    if (base == null || pin == null || token == null) {
      throw StateError('This device is not paired.');
    }
    return _request(
      base: base,
      pin: pin,
      token: token,
      path: '/api/v1/tasks/$taskId/status',
      method: 'POST',
      body: {
        'status': status,
        'progress': progress,
        if (result != null) 'result': result,
        if (error.isNotEmpty)
          'error': error.length > 450 ? error.substring(0, 450) : error,
      },
      authenticated: true,
    );
  }

  Future<void> disconnect() async {
    await _storage.delete(key: _hostKey);
    await _storage.delete(key: _pinKey);
    await _storage.delete(key: _credentialKey);
  }

  Future<Map<String, dynamic>> _request({
    required String base,
    required String pin,
    required String path,
    required String method,
    required Map<String, dynamic> body,
    required bool authenticated,
    String? token,
  }) async {
    _pinMismatch = false;
    final client = HttpClient(context: SecurityContext(withTrustedRoots: false))
      ..connectionTimeout = const Duration(seconds: 8)
      ..badCertificateCallback = (certificate, host, port) {
        final actual = sha256.convert(certificate.der).toString().toUpperCase();
        final matches = actual == pin;
        if (!matches) _pinMismatch = true;
        return matches;
      };
    try {
      final uri = Uri.parse(base + path);
      final request = await client.openUrl(method, uri).timeout(const Duration(seconds: 10));
      request.headers.contentType = ContentType.json;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (authenticated) {
        final credential = token ?? await _storage.read(key: _credentialKey);
        if (credential == null) throw StateError('Missing paired-device credential.');
        request.headers.set(HttpHeaders.authorizationHeader, 'Bearer ' + credential);
      }
      // The Windows BaseHTTPRequestHandler reads Content-Length and does not
      // support chunked request bodies. Set the exact UTF-8 byte length so the
      // coordinator can parse the JSON instead of seeing an empty body.
      final bodyBytes = utf8.encode(jsonEncode(body));
      request.contentLength = bodyBytes.length;
      request.add(bodyBytes);
      final response = await request.close().timeout(const Duration(seconds: 12));
      final payload = await utf8.decoder.bind(response).join();
      Map<String, dynamic> decoded = {};
      if (payload.isNotEmpty) {
        final value = jsonDecode(payload);
        if (value is Map) decoded = Map<String, dynamic>.from(value);
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException(
          decoded['error']?.toString() ?? 'Coordinator returned HTTP ' + response.statusCode.toString(),
          uri: uri,
        );
      }
      return decoded;
    } on HandshakeException catch (error) {
      if (_pinMismatch) {
        throw const TlsException('Certificate fingerprint mismatch. Check the Windows host fingerprint before pairing.');
      }
      throw TlsException('Secure connection failed: ' + error.toString());
    } on SocketException catch (error) {
      if (_pinMismatch) {
        throw const TlsException('Certificate fingerprint mismatch. Pairing was stopped to protect your device.');
      }
      throw HttpException('Cannot reach the coordinator: ' + error.toString());
    } finally {
      client.close(force: true);
    }
  }

  String _normaliseBase(String value) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty ||
        uri.userInfo.isNotEmpty || uri.query.isNotEmpty || uri.fragment.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw const FormatException('Use the coordinator HTTPS address, e.g. https://192.168.1.10:8765');
    }
    return uri.replace(path: '').toString().replaceFirst(RegExp(r'/$'), '');
  }

  String _normalisePin(String value) {
    final pin = value.replaceAll(RegExp(r'[^0-9a-fA-F]'), '').toUpperCase();
    if (!RegExp(r'^[0-9A-F]{64}$').hasMatch(pin)) {
      throw const FormatException('Enter the 64-character SHA-256 certificate fingerprint.');
    }
    return pin;
  }
}
