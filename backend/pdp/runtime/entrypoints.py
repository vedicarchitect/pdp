import os
import uvicorn

# Each role runs in its own process/container, so there's no port collision from
# reusing 8000 across api/engine/ops — matches `task dev`'s port and the /readyz
# healthcheck URL baked into infra/compose/docker-compose.yml.
_PORT = int(os.environ.get("PORT", "8000"))

def run_api():
    """Entry point for pdp-api console script."""
    os.environ["PDP_ROLE"] = "api"
    uvicorn.run("pdp.main:app", host="0.0.0.0", port=_PORT, reload=False)

def run_engine():
    """Entry point for pdp-engine console script."""
    os.environ["PDP_ROLE"] = "engine"
    uvicorn.run("pdp.main:app", host="0.0.0.0", port=_PORT, reload=False)

def run_ops():
    """Entry point for pdp-ops console script."""
    os.environ["PDP_ROLE"] = "ops"
    uvicorn.run("pdp.main:app", host="0.0.0.0", port=_PORT, reload=False)
