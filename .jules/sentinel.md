## 2024-05-23 - Prevent Information Leakage in API Responses
**Vulnerability:** Global exception handler leaked raw exception types and messages (`str(exc)`) directly to API clients.
**Learning:** Exposing raw exceptions can reveal sensitive internal system details, stack traces, or database schema info to potential attackers.
**Prevention:** Always return generic error messages (e.g., "InternalServerError") to the client while logging the detailed exception internally for debugging.
