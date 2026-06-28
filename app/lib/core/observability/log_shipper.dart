import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';

import '../config/app_config.dart';

/// Batches Flutter log records and POSTs them to the backend log-ingest
/// endpoint in the background. Fire-and-forget — never blocks the UI.
///
/// Ship a record:
///   LogShipper.instance.ship(level: 'error', event: 'crash', screen: 'chart');
///
/// Call [dispose] when the app closes (optional — the timer self-cancels).
class LogShipper {
  LogShipper._({
    required String apiBase,
    Duration flushInterval = const Duration(seconds: 10),
    int flushThreshold = 50,
  })  : _apiBase = apiBase,
        _flushInterval = flushInterval,
        _flushThreshold = flushThreshold {
    _timer = Timer.periodic(_flushInterval, (_) => _flush());
  }

  static LogShipper? _instance;

  static LogShipper get instance {
    _instance ??= LogShipper._(apiBase: AppConfig.current.apiBase);
    return _instance!;
  }

  final String _apiBase;
  final Duration _flushInterval;
  final int _flushThreshold;
  final List<Map<String, dynamic>> _buffer = [];
  late Timer _timer;
  final _dio = Dio(BaseOptions(connectTimeout: const Duration(seconds: 5)));

  final String _build = const String.fromEnvironment('APP_BUILD', defaultValue: '');
  final String _device = Platform.operatingSystem;

  /// Enqueue a log record for the next flush. Never throws.
  void ship({
    required String event,
    String level = 'info',
    String? screen,
    Map<String, dynamic>? context,
  }) {
    _buffer.add({
      'level': level,
      'event': event,
      if (screen != null) 'screen': screen,
      if (_build.isNotEmpty) 'build': _build,
      'device': _device,
      if (context != null) 'context': context,
    });
    if (_buffer.length >= _flushThreshold) {
      _flush();
    }
  }

  void _flush() {
    if (_buffer.isEmpty) return;
    final batch = List<Map<String, dynamic>>.from(_buffer);
    _buffer.clear();
    // Fire-and-forget — discard errors silently to never block the UI.
    _dio.post<dynamic>(
      '$_apiBase/api/v1/logs/ingest',
      data: {'records': batch},
    ).ignore();
  }

  void dispose() {
    _timer.cancel();
    _flush();
  }
}
