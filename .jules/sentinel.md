## 2024-05-24 - Prevent Information Leakage in Global Exception Handler
**Vulnerability:** Raw exception strings (type and message) and occasionally stack traces were exposed in HTTP 500 error responses.
**Learning:** Global exception handlers should log exact errors internally but return generic messages to avoid leaking implementation details and potential secrets.
**Prevention:** Return generic error objects like `{"error": {"type": "InternalServerError", "message": "An unexpected error occurred."}}` for unhandled exceptions.
