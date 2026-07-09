import pytest
from fastapi.testclient import TestClient

from pdp.main import app

client = TestClient(app)

@pytest.mark.http
def test_openapi_schema_completeness():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    
    missing = []
    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/api"):
            continue
        for method, operation in path_item.items():
            responses = operation.get("responses", {})
            for status, resp in responses.items():
                # Only check 2xx responses (success)
                if not status.startswith("2"):
                    continue
                if status == "204":
                    continue
                content = resp.get("content", {})
                if "application/json" not in content:
                    missing.append(f"{method.upper()} {path} ({status}) missing application/json content")
                else:
                    json_schema = content["application/json"].get("schema", {})
                    # A completely untyped dict without response_model looks like empty dict {} in the schema
                    if not json_schema:
                        missing.append(f"{method.upper()} {path} ({status}) missing typed schema")

    assert not missing, f"Routes missing OpenAPI typed schema:\n" + "\n".join(missing)
