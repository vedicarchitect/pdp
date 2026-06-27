/// Formats [value] as an Indian-grouped rupee amount, e.g. `+₹1,23,456.78`.
String formatInr(double value, {bool showSign = true}) {
  final negative = value < 0;
  final fixed = value.abs().toStringAsFixed(2);
  final dot = fixed.indexOf('.');
  final intPart = fixed.substring(0, dot);
  final decPart = fixed.substring(dot + 1);
  final grouped = _indianGroup(intPart);
  final sign = negative ? '-' : (showSign ? '+' : '');
  return '$sign₹$grouped.$decPart';
}

/// Indian digit grouping: last three digits, then pairs (lakh/crore).
String _indianGroup(String digits) {
  if (digits.length <= 3) return digits;
  final last3 = digits.substring(digits.length - 3);
  final rest = digits.substring(0, digits.length - 3);
  final withCommas =
      rest.replaceAllMapped(RegExp(r'(\d)(?=(\d\d)+$)'), (m) => '${m[1]},');
  return '$withCommas,$last3';
}
