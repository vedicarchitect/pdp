## 2026-07-05 - Do not leak internal exception details
**Vulnerability:** Global FastAPI exception handler was returning `str(exc)` and `type(exc).__name__` directly in 500 error responses.
**Learning:** Returning raw exception strings can leak internal stack details, database schemas, or logic errors to the client.
**Prevention:** Return generic "InternalServerError" messages to the client and log the detailed exception internally using `structlog`.
