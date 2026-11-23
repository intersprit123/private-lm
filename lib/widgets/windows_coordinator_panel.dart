import 'dart:async';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';
import 'package:llama_flutter_android/llama_flutter_android.dart';

import '../core/constants.dart';
import '../services/cluster_service.dart';
import '../services/hive_service.dart';
import '../services/windows_cluster_client.dart';

/// UI for joining a Windows PrivateLM coordinator as a settings/control member.
/// It deliberately does not label a paired phone as an inference worker.
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
  String _status = 'Not connected to a Windows coordinator';
  String _details = 'Pairing syncs settings only. Compute participation is verified separately.';
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

  Future<Map<String, dynamic>> _identity() async {
    final cluster = Get.find<ClusterService>();
    final freeRam = await LlamaCluster.localFreeRamMb();
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
        'native_rpc_worker_running': cluster.worker.value.running,
        'native_rpc_port': LlamaCluster.defaultPort,
        'native_rpc_version': 'rpc7',
        'compute_note': 'Native Android phone-cluster RPC is separate from the Windows control pairing.',
      },
    };
  }

  Future<void> _pair() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _status = 'Verifying TLS certificate and pairing…';
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
      if (mode != 'performance') unsupported.add('remote compute mode');
      if (config['gpu_policy'] != 'auto') unsupported.add('GPU policy');
      if (config['image_backend'] != 'auto') unsupported.add('image backend');
      if (config['startup_behavior'] != 'remember') unsupported.add('startup behavior');
      if (config['text_scale'] != 'medium') unsupported.add('text scale');
      if ((config['selected_gpu_ids'] is List) &&
          (config['selected_gpu_ids'] as List).isNotEmpty) unsupported.add('selected GPU IDs');
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
              TextField(controller: _host, decoration: _decoration('Coordinator HTTPS address', hint: 'https://192.168.1.10:8765')),
              const SizedBox(height: 8),
              TextField(controller: _code, keyboardType: TextInputType.number, maxLength: 8, decoration: _decoration('One-time pairing code')),
              const SizedBox(height: 8),
              TextField(controller: _fingerprint, maxLines: 2, decoration: _decoration('SHA-256 certificate fingerprint', hint: 'Paste the 64-character fingerprint shown on Windows')),
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
