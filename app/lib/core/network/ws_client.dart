import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'connection_status.dart';

/// A reusable WebSocket client with exponential-backoff reconnect.
///
/// Decoded JSON-object messages are exposed as a broadcast [stream]. The socket
/// reconnects automatically (1s → 2s → 4s → 8s … capped at 30s) on unexpected
/// close, reporting transitions through [onStatus].
class WsClient {
  WsClient({required this.url, this.onStatus});

  final String url;
  final void Function(ConnStatus status)? onStatus;

  static const Duration _initialBackoff = Duration(seconds: 1);
  static const Duration _maxBackoff = Duration(seconds: 30);

  final StreamController<Map<String, dynamic>> _controller =
      StreamController<Map<String, dynamic>>.broadcast();

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _retryTimer;
  Duration _backoff = _initialBackoff;
  bool _firstAttempt = true;
  bool _closed = false;

  /// Decoded inbound messages (JSON objects only).
  Stream<Map<String, dynamic>> get stream => _controller.stream;

  /// Opens the connection. Safe to call once; reconnects are automatic.
  void connect() {
    _closed = false;
    _open();
  }

  void _open() {
    onStatus?.call(_firstAttempt ? ConnStatus.connecting : ConnStatus.reconnecting);
    try {
      final channel = WebSocketChannel.connect(Uri.parse(url));
      _channel = channel;
      _sub = channel.stream.listen(
        (dynamic data) {
          if (_firstAttempt || _backoff != _initialBackoff) {
            _firstAttempt = false;
            _backoff = _initialBackoff;
          }
          onStatus?.call(ConnStatus.connected);
          _handle(data);
        },
        onError: (_) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _handle(dynamic data) {
    if (data is! String) return;
    try {
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) {
        _controller.add(decoded);
      }
    } catch (_) {
      // Ignore malformed frames.
    }
  }

  void _scheduleReconnect() {
    _sub?.cancel();
    _sub = null;
    _channel?.sink.close();
    _channel = null;
    if (_closed) return;

    _firstAttempt = false;
    onStatus?.call(ConnStatus.reconnecting);
    _retryTimer?.cancel();
    _retryTimer = Timer(_backoff, _open);

    final next = _backoff * 2;
    _backoff = next > _maxBackoff ? _maxBackoff : next;
  }

  /// Permanently closes the client and releases resources.
  Future<void> dispose() async {
    _closed = true;
    _retryTimer?.cancel();
    await _sub?.cancel();
    await _channel?.sink.close();
    onStatus?.call(ConnStatus.disconnected);
    await _controller.close();
  }
}
