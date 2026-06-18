export function formatAlertTitle(securityId: string): string {
  return `Alert Triggered: ${securityId}`;
}

export function formatAlertDescription(condition: string, threshold: string | number): string {
  const label = condition.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return `${label} — threshold: ${threshold}`;
}
