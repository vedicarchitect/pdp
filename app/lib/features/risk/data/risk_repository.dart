import '../../../core/network/api_client.dart';
import '../domain/risk_models.dart';

class RiskRepository {
  final ApiClient _api;

  RiskRepository(this._api);

  Future<DailyLossStatus> getDailyLoss() async {
    final response = await _api.getJson('/api/v1/risk/daily-loss');
    return DailyLossStatus.fromJson(response);
  }

  Future<RiskSettings> getRiskSettings() async {
    final response = await _api.getJson('/api/v1/settings/risk');
    return RiskSettings.fromJson(response);
  }

  Future<void> triggerKillSwitch() async {
    await _api.postJson('/api/v1/risk/kill');
  }

  Future<void> modifyPositionRisk(
    String securityId, {
    double? stopLoss,
    double? target,
    double? trailingSl,
  }) async {
    await _api.postJson('/api/v1/risk/positions/$securityId/modify', body: {
      if (stopLoss != null) 'stop_loss': stopLoss,
      if (target != null) 'target': target,
      if (trailingSl != null) 'trailing_sl': trailingSl,
    });
  }
}
