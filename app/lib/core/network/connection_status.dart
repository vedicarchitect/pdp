import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Live-feed connection state, surfaced in the shell via [ConnectionBadge].
enum ConnStatus { connecting, connected, reconnecting, disconnected, engineDown }

extension ConnStatusLabel on ConnStatus {
  String get label => switch (this) {
        ConnStatus.connecting => 'Connecting',
        ConnStatus.connected => 'Live',
        ConnStatus.reconnecting => 'Reconnecting',
        ConnStatus.disconnected => 'Offline',
        ConnStatus.engineDown => 'Feed Offline',
      };
}

/// Current connection status. Written by the live WebSocket client (or set to
/// `connected` by the mock source) and read by the shell badge.
final connectionStatusProvider =
    StateProvider<ConnStatus>((ref) => ConnStatus.connecting);
