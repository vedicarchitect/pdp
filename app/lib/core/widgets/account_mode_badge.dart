import 'package:flutter/material.dart';

/// Visual badge distinguishing LIVE (real broker) vs PAPER (simulated) mode.
///
/// - **LIVE (manual)** — amber dot + amber text; a real-money surface.
/// - **PAPER** — muted grey dot + grey text.
///
/// Use on the Portfolio/Live Account tab header and per-card headers.
class AccountModeBadge extends StatelessWidget {
  const AccountModeBadge({super.key, required this.mode});

  /// `"live"` or `"paper"`.
  final String mode;

  bool get _isLive => mode.toLowerCase() == 'live';

  @override
  Widget build(BuildContext context) {
    final color = _isLive ? Colors.amber.shade700 : Colors.grey.shade500;
    final label = _isLive ? 'LIVE (manual)' : 'PAPER';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.circle, size: 8, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: color,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
