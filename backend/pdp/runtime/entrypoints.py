import os
import uvicorn

def run_api():
    """Entry point for pdp-api console script."""
    os.environ["PDP_ROLE"] = "api"
    uvicorn.run("pdp.main:app", host="0.0.0.0", port=8001, reload=False)

def run_engine():
    """Entry point for pdp-engine console script."""
    os.environ["PDP_ROLE"] = "engine"
    # Port 8002 for engine
    uvicorn.run("pdp.main:app", host="0.0.0.0", port=8002, reload=False)

def run_ops():
    """Entry point for pdp-ops console script."""
    os.environ["PDP_ROLE"] = "ops"
    # Port 8003 for ops
    uvicorn.run("pdp.main:app", host="0.0.0.0", port=8003, reload=False)
