## 2024-05-24 - Unhandled Exception Information Leakage
**Vulnerability:** Global exception handler leaked exception type and raw stringified exception messages to the client on HTTP 500 responses.
**Learning:** Returning `str(exc)` directly exposes internal system details (file paths, SQL fragments, environment state) which aids attackers in reconnaissance.
**Prevention:** Always return a generic error message (e.g., "InternalServerError", "An unexpected error occurred.") to the client while logging the detailed exception internally for debugging.
