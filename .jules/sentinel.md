## 2024-10-24 - Missing CORS Middleware
**Vulnerability:** The FastAPI backend is completely lacking CORS middleware configuration, despite an explicitly planned frontend that depends on cross-origin requests.
**Learning:** In backend-first projects that eventually get a frontend scaffolding, CORS middleware is often missed since Vite proxy works for dev and the initial backend doesn't serve UI. This exposes the app to Cross-Origin attacks if run on non-proxied environments and restricts legitimate integrations.
**Prevention:** Always implement `CORSMiddleware` when building REST APIs that will be consumed by a separate frontend, initializing with secure and explicit local or environment-configured defaults rather than `allow_origins=["*"]`.
