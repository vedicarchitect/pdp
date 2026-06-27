
## 2026-06-27 - Hardcoded Authentication Bypass
**Vulnerability:** Placeholder 'user_123' allowed unauthenticated access to alert endpoints.
**Learning:** Development placeholders for user IDs bypass authentication entirely and expose sensitive operations.
**Prevention:** Even before full JWT parsing is implemented, require tokens and use the token itself as the identifier to maintain isolation.

## 2026-06-27 - Securing Development Placeholders
**Vulnerability:** Development endpoints allowed unauthenticated access because missing tokens were allowed to default to a placeholder user ID.
**Learning:** When using placeholder IDs during development (like 'user_123' pending full JWT parsing), the presence and format of the authentication token MUST still be validated to prevent unauthenticated access. Using the raw, unvalidated token string as a user ID breaks identity persistence and allows spoofing.
**Prevention:** Enforce 401/4001 responses for missing tokens even when returning development placeholders, and never use unparsed client strings directly as identity keys.
