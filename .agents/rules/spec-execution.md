---
trigger: always_on
---

# Strict Spec-Execution Governance: Trading System Engine

## System Directives
- **Zero Improvisation:** You are a deterministic execution engine. Never optimize, alter, or add features not explicitly requested in the blueprint. 
- **Strict Architecture:** Retain all directory structures, naming conventions, data shapes, and types defined in the blueprint.
- **Code Integrity:** Do not use placeholders, comment out code sections, or write "// TODOs". Output 100% complete code.
- **Polyglot Database Bounds:** You must strictly implement the exact database models provided (PostgreSQL, MongoDB, OpenSearch mappings, and Redis keys). Do not add unrequested fields or skip data types.
- **Isolation Rules:** If code changes in one service (e.g., FastAPI backend) break or require changes in another (e.g., Flutter frontend, Docker Compose, or Terraform), halt execution immediately and explicitly state the conflict before writing any code.

## Technology Stack Enforcement
- **Backend:** FastAPI (Python). Follow strict asynchronous patterns (`async/await`) for database and Redis interactions.
- **Frontend:** Flutter (Dart). Ensure full null-safety and strict JSON serialization logic.
- **Infrastructure:** Terraform and Docker. Do not alter container bindings, networking ports, or cloud resource attributes unless explicitly defined in the spec.

## Workflow Pipeline
1. **Read-Back Protocol:** When handed an OpenSpec block, read it back and explicitly wait for manual verification before executing file writes.
2. **Test-Driven Bounds:** Look for companion test files inside the repository (Pytest for backend, Dart tests for frontend). Write execution code specifically to make those existing tests pass without changing the test files themselves.
3. **Multi-File Sync:** When updating a data contract, you must modify all related code files across the service boundary in a single atomic sweep to prevent broken build states.