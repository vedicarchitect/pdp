/// One editable parameter in a strategy's param schema.
class ParamSpec {
  const ParamSpec({required this.name, required this.type, this.defaultValue, this.min, this.max});

  final String name;
  final String type; // "bool" | "int" | "float" | "str"
  final Object? defaultValue;
  final num? min;
  final num? max;

  factory ParamSpec.fromJson(Map<String, dynamic> json) {
    final bounds = json['bounds'] as Map<String, dynamic>?;
    return ParamSpec(
      name: json['name'] as String,
      type: json['type'] as String? ?? 'str',
      defaultValue: json['default'],
      min: (bounds?['min'] as num?),
      max: (bounds?['max'] as num?),
    );
  }
}

/// A registered strategy from `GET /api/v1/strategies`, spanning live and
/// backtest-only entries under one canonical id.
class StrategyInfo {
  const StrategyInfo({
    required this.id,
    required this.kind,
    required this.source,
    required this.status,
    required this.paramsSchema,
    required this.defaults,
    this.underlying,
  });

  final String id;
  final String kind;
  final String? underlying;
  final String source; // "live" | "backtest"
  final String status;
  final List<ParamSpec> paramsSchema;
  final Map<String, dynamic> defaults;

  factory StrategyInfo.fromJson(Map<String, dynamic> json) {
    return StrategyInfo(
      id: json['id'] as String,
      kind: json['kind'] as String? ?? '',
      underlying: json['underlying'] as String?,
      source: json['source'] as String? ?? 'backtest',
      status: json['status'] as String? ?? 'BACKTEST_ONLY',
      paramsSchema: (json['params_schema'] as List<dynamic>? ?? [])
          .map((e) => ParamSpec.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
      defaults: json['defaults'] as Map<String, dynamic>? ?? const {},
    );
  }
}
