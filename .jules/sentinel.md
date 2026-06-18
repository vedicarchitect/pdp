
## 2026-06-18 - Add CORS Middleware
**Vulnerability:** Missing CORS protection
**Learning:** The frontend scaffold added in previous changes relies on Vite dev proxy but requires FastAPI CORS middleware for proper operation and security. Missing CORS configuration can lead to unauthorized cross-origin requests or break frontend integration.
**Prevention:** Always configure CORS with restricted origins when exposing an API to a web frontend.
