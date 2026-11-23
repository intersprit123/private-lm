import 'dart:async';
import 'dart:convert';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';
import 'package:llama_flutter_android/llama_flutter_android.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../core/constants.dart';
import '../services/cluster_service.dart';
import '../services/hive_service.dart';
import '../services/windows_cluster_client.dart';

/// Joins a Windows PrivateLM coordinator as a settings/control member.
class WindowsCoordinatorPanel extends StatefulWidget {
  const WindowsCoordinatorPanel({super.key});

  @override
  State<WindowsCoordinatorPanel> createState() => _WindowsCoordinatorPanelState();
}

class _WindowsCoordinatorPanelState extends State<WindowsCoordinatorPanel> {
  final _client = WindowsClusterClient();
  final _host = TextEditingController();
  final _code = TextEditingController();
  final _fingerprint = TextEditingController();
  Timer? _timer;
  bool _paired = false;
  bool _busy = false;
  bool _polling = false;
  bool _qrVerified = false;
  String _status = 'Not connected to a Windows coordinator';
  String _details = 'Scan the QR displayed in the Windows PrivateLM app to pair securely.';
  int _lastRevision = 0;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _host.dispose();
    _code.dispose();
    _fingerprint.dispose();
    super.dispose();
  }

  Future<void> _restore() async {
    final paired = await _client.isPaired;
    final coordinator = await _client.coordinator;
    if (!mounted) return;
    setState(() {
      _paired = paired;
      if (coordinator != null) _host.text = coordinator;
      _status = paired ? 'Paired · waiting for coordinator settings' : _status;
    });
    if (paired) {
      await _sync();
      _timer = Timer.periodic(const Duration(seconds: 5), (_) => _sync());
    }
  }

  Future<void> _scanWindowsQr() async {
    final controller = MobileScannerController(
      detectionSpeed: DetectionSpeed.noDuplicates,
      formats: const [BarcodeFormat.qrCode],
    );
    var handled = false;
    try {
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Scan Windows PrivateLM QR'),
          content: SizedBox(
            width: 320,
            height: 360,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: MobileScanner(
                controller: controller,
                onDetect: (capture) async {
                  if (handled) return;
                  final raw = capture.barcodes
                      .map((barcode) => barcode.rawValue)
                      .whereType<String>()
                      .firstWhere((value) => value.isNotEmpty, orElse: () => '');
                  if (raw == null) return;
                  handled = true;
                  try {
                    final data = jsonDecode(raw);
                    if (data is! Map<String, dynamic> ||
                        data['service'] != 'PrivateLM Device Cluster') {
                      throw const FormatException(
                        'This is not a PrivateLM Device Cluster QR code. Generate the pairing QR in Windows → Devices.',
                      );
                    }
                    final coordinator = data['coordinator']?.toString() ?? '';
                    final code = data['pairing_code']?.toString() ?? '';
                    final fingerprint = data['certificate_sha256']?.toString() ?? '';
                    final uri = Uri.tryParse(coordinator);
                    final cleanPin = fingerprint.replaceAll(RegExp(r'[^0-9a-fA-F]'), '');
                    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty ||
                        !RegExp(r'^\d{8}$').hasMatch(code) ||
                        !RegExp(r'^[0-9a-fA-F]{64}$').hasMatch(cleanPin)) {
                      throw const FormatException(
                        'The PrivateLM QR is incomplete or invalid. Start the Windows cluster service and generate a fresh QR.',
                      );
                    }
                    if (!mounted) return;
                    setState(() {
                      _host.text = coordinator;
                      _code.text = code;
                      _fingerprint.text = cleanPin.toUpperCase();
                      _qrVerified = true;
                      _details = 'Windows PrivateLM QR verified. Pairing code and certificate pin loaded automatically.';
                      _status = 'QR verified · ready to pair';
                    });
                    Navigator.of(dialogContext).pop();
                  } catch (error) {
                    handled = false;
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(error.toString().replaceFirst('FormatException: ', ''))),
                    );
                  }
                },
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('Cancel'),
            ),
          ],
        ),
      );
    } finally {
      await controller.dispose();
    }
  }

  Future<Map<String, dynamic>> _identity() async {
    final cluster = Get.find<ClusterService>();
    final freeRam = await LlamaCluster.localFreeRamMb();
    final worker = cluster.worker.value;
    final safeWorkerRam = (freeRam * 0.70).floor();
    String name = cluster.deviceName;
    if (name.isEmpty) {
      final info = await DeviceInfoPlugin().androidInfo;
      name = info.model;
    }
    return {
      'name': name.isEmpty ? 'Android device' : name,
      'platform': 'Android',
      'capabilities': {
        'platform': 'Android',
        'ram_available_mb': freeRam,
        'control_protocol_version': 1,
        'worker_state': worker.running ? (worker.peer == null ? 'ready' : 'busy') : worker.starting ? 'starting' : worker.state == 'error' ? 'error' : 'stopped',
        'worker_memory_available_mb': worker.running ? safeWorkerRam : 0,
        'worker_memory_held_mb': worker.heldMb,
        'worker_throttled': worker.throttled,
        'worker_peer': worker.peer,
        'native_rpc_worker_running': worker.running,
        'native_rpc_port': LlamaCluster.defaultPort,
        'native_rpc_version': 'rpc7',
        'compute_note': 'Memory is accounted per device; it is not merged with Windows RAM.',
      },
    };
  }

  Future<void> _pair() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _status = 'Verifying Windows certificate and pairing…';
    });
    try {
      final config = await _client.pair(
        baseUrl: _host.text,
        code: _code.text,
        certificateFingerprint: _fingerprint.text,
        identity: await _identity(),
      );
      if (!mounted) return;
      setState(() {
        _paired = true;
        _status = 'Securely paired · synchronizing configuration';
      });
      await _applyConfig(config);
      if (mounted) await _showComputeMenu(config);
      _timer?.cancel();
      _timer = Timer.periodic(const Duration(seconds: 5), (_) => _sync());
    } catch (error) {
      if (mounted) setState(() => _status = 'Pairing failed: ' + error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sync() async {
    if (_polling || !_paired) return;
    _polling = true;
    try {
      final config = await _client.heartbeat(await _identity());
      await _applyConfig(config);
      if (mounted && _lastRevision == 0) {
        setState(() => _status = 'Connected · secure settings sync active');
      }
    } catch (error) {
      if (mounted) setState(() => _status = 'Coordinator unavailable: ' + error.toString());
    } finally {
      _polling = false;
    }
  }

  Future<void> _applyConfig(Map<String, dynamic> config) async {
    final revision = int.tryParse(config['revision']?.toString() ?? '') ?? 0;
    if (revision < 1 || revision <= _lastRevision) return;
    final mode = config['execution_mode']?.toString() ?? 'performance';
    final context = int.tryParse(config['context_size']?.toString() ?? '');
    final maxTokens = int.tryParse(config['max_output_tokens']?.toString() ?? '');
    final temperature = double.tryParse(config['temperature']?.toString() ?? '');
    final budget = int.tryParse(config['ram_budget_percent']?.toString() ?? '');
    String? rejection;

    if (!['performance', 'performance_group', 'extreme_force'].contains(mode)) {
      rejection = 'Unknown execution mode.';
    } else if (context == null || context < 256 || context > 32768 ||
        maxTokens == null || maxTokens < 1 || maxTokens > context ||
        temperature == null || temperature < 0 || temperature > 2 ||
        budget == null || budget < 10 || budget > 70) {
      rejection = 'Settings are outside this device’s supported context, token, temperature or RAM bounds.';
    } else {
      final hive = Get.find<HiveService>();
      await hive.setSetting(AppConstants.keyContextSize, context);
      await hive.setSetting(AppConstants.keyMaxTokens, maxTokens);
      await hive.setSetting(AppConstants.keyTemperature, temperature);
      await hive.setSetting('windows_cluster_received_config', config);
      final unsupported = <String>[];
      // Execution mode and GPU selection are coordinator-side Windows settings.
      if (config['image_backend'] != 'auto') unsupported.add('image backend');
      if (config['startup_behavior'] != 'remember') unsupported.add('startup behavior');
      if (config['text_scale'] != 'medium') unsupported.add('text scale');
      if (unsupported.isNotEmpty) {
        rejection = 'Chat defaults were saved, but this Android build cannot yet apply: ' +
            unsupported.join(', ') + '. Existing Android RPC clustering remains separate.';
      }
    }

    final accepted = rejection == null;
    final reason = accepted
        ? 'Applied context, output-token and temperature defaults. Device compute remains local.'
        : rejection!;
    await _client.acknowledge(revision: revision, accepted: accepted, reason: reason);
    _lastRevision = revision;
    if (mounted) {
      setState(() {
        _status = accepted ? 'Configuration revision ' + revision.toString() + ' applied'
            : 'Configuration revision ' + revision.toString() + ' partially applied';
        _details = reason;
      });
    }
  }

  Future<void> _showComputeMenu([Map<String, dynamic>? supplied]) async {
    final config = supplied ?? await _client.heartbeat(await _identity());
    final raw = config["available_gpu_devices"];
    final devices = raw is List ? raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).where((e) => (e["id"]?.toString() ?? "").isNotEmpty).toList() : <Map<String, dynamic>>[];
    if (!mounted) return;
    if (devices.isEmpty) { setState(() => _details = "No Windows GPU inventory received. On Windows, select llama-server.exe and click Detect GPUs first."); return; }
    final ids = devices.map((e) => e["id"].toString()).toList();
    var mode = config["execution_mode"] == "extreme_force" ? "extreme_force" : "performance";
    var policy = config["gpu_policy"] == "all_compatible" ? "all_compatible" : "single";
    var selected = (config["selected_gpu_ids"] is List ? config["selected_gpu_ids"] as List : const []).map((e) => e.toString()).where(ids.contains).toList();
    if (selected.isEmpty) selected = [ids.first];
    if (policy == "single") selected = [selected.first];
    final apply = await showDialog<bool>(context: context, barrierDismissible: false, builder: (dialogContext) => StatefulBuilder(builder: (ctx, setDialogState) => AlertDialog(
      title: const Text("Choose Windows compute mode"),
      content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Text("Choose one detected GPU or use all detected GPUs. CPU sharing is not included yet."),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(value: mode, decoration: const InputDecoration(labelText: "Execution mode"), items: const [DropdownMenuItem(value: "performance", child: Text("Performance")), DropdownMenuItem(value: "extreme_force", child: Text("Maximum GPU use"))], onChanged: (v) => setDialogState(() => mode = v ?? mode)),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(value: policy, decoration: const InputDecoration(labelText: "GPU mode"), items: const [DropdownMenuItem(value: "single", child: Text("Use one GPU")), DropdownMenuItem(value: "all_compatible", child: Text("Use all GPUs"))], onChanged: (v) => setDialogState(() { policy = v ?? policy; if (policy == "single" && selected.length > 1) selected = [selected.first]; if (policy == "all_compatible") selected = List<String>.from(ids); })),
        if (policy == "single") ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(value: selected.first, decoration: const InputDecoration(labelText: "GPU device"), items: [for (final d in devices) DropdownMenuItem(value: d["id"].toString(), child: Text("${d["id"]} — ${d["name"] ?? "GPU"}"))], onChanged: (v) => setDialogState(() { if (v != null) selected = [v]; })),
        ] else ...[const SizedBox(height: 8), Text("All GPUs: ${devices.map((d) => d["name"] ?? d["id"]).join(", ")}")],
      ])),
      actions: [TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text("Cancel")), FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text("Apply"))],
    )));
    if (apply != true) return;
    try {
      final updated = await _client.setComputeOptions(executionMode: mode, gpuPolicy: policy, selectedGpuIds: policy == "all_compatible" ? ids : selected);
      await _applyConfig(updated);
      if (mounted) setState(() => _details = "GPU selection sent to Windows. The host applies it to inference.");
    } catch (error) { if (mounted) setState(() => _status = "GPU selection failed: $error"); }
  }
  Future<void> _disconnect() async {
    _timer?.cancel();
    await _client.disconnect();
    _lastRevision = 0;
    if (!mounted) return;
    setState(() {
      _paired = false;
      _status = 'Disconnected from Windows coordinator';
      _details = 'The saved device credential was deleted from this phone.';
    });
  }

  InputDecoration _decoration(String label, {String? hint}) => InputDecoration(
        labelText: label,
        hintText: hint,
        isDense: true,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      );

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.devices_rounded),
              const SizedBox(width: 10),
              Expanded(child: Text('Windows coordinator', style: t.textTheme.titleMedium)),
              if (_paired) const Icon(Icons.verified_user_rounded, color: Colors.green),
            ]),
            const SizedBox(height: 8),
            Text(_status, style: t.textTheme.bodyMedium),
            const SizedBox(height: 4),
            Text(_details, style: t.textTheme.bodySmall),
            if (!_paired) ...[
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _busy ? null : _scanWindowsQr,
                  icon: const Icon(Icons.qr_code_scanner_rounded),
                  label: const Text('Scan Windows PrivateLM QR'),
                ),
              ),
              if (_qrVerified) ...[
                const SizedBox(height: 8),
                Row(children: [
                  const Icon(Icons.verified_rounded, color: Colors.green, size: 18),
                  const SizedBox(width: 6),
                  Expanded(child: Text('PrivateLM QR verified', style: t.textTheme.bodySmall)),
                ]),
                const SizedBox(height: 6),
                Text(_host.text, style: t.textTheme.bodySmall),
              ],
              const SizedBox(height: 8),
              TextField(controller: _host, readOnly: _qrVerified,
                  decoration: _decoration('Coordinator HTTPS address', hint: 'Scan the Windows QR to fill this')),
              const SizedBox(height: 8),
              TextField(controller: _code, readOnly: _qrVerified,
                  keyboardType: TextInputType.number, maxLength: 8,
                  decoration: _decoration('One-time pairing code')),
              const SizedBox(height: 8),
              if (_qrVerified)
                Text('Certificate fingerprint verified from QR and stored for TLS pinning. No manual paste needed.',
                    style: t.textTheme.bodySmall)
              else
                TextField(controller: _fingerprint, maxLines: 2,
                    decoration: _decoration('SHA-256 certificate fingerprint')),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _busy ? null : _pair,
                  icon: _busy
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.link_rounded),
                  label: Text(_busy ? 'Pairing…' : 'Pair with Windows'),
                ),
              ),
            ] else ...[
              const SizedBox(height: 10),
              SizedBox(width: double.infinity, child: OutlinedButton.icon(onPressed: _busy ? null : () => _showComputeMenu(), icon: const Icon(Icons.tune_rounded), label: const Text("Choose compute mode and GPU"))),
              const SizedBox(height: 8),
              Row(children: [
                const Icon(Icons.lock_rounded, size: 16),
                const SizedBox(width: 6),
                Expanded(child: Text(_host.text, style: t.textTheme.bodySmall)),
                TextButton(onPressed: _busy ? null : _disconnect, child: const Text('Disconnect')),
              ]),
            ],
            const SizedBox(height: 8),
            Text(
              'A paired device is a control-plane member, not automatically an inference worker. To revoke its access on Windows, select it in the host app and choose Revoke.',
              style: t.textTheme.bodySmall?.copyWith(color: t.colorScheme.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}
