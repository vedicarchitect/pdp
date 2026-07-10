## ADDED Requirements

### Requirement: Typed response models on all JSON endpoints

Every JSON-returning route handler SHALL declare an explicit `response_model` (a Pydantic model
or a typed `Page[T]` wrapper for lists) and an explicit `status_code`, so the auto-generated
OpenAPI schema at `/openapi.json` documents each endpoint's response shape. Response models
SHALL be defined once per resource shape in a per-module `schemas.py` and reused across
endpoints rather than duplicated inline.

#### Scenario: OpenAPI documents a response schema for a mutating route

- **WHEN** `/openapi.json` is generated
- **THEN** each mutating route declares a non-empty response schema (not an untyped object)

#### Scenario: List endpoint returns a typed page

- **WHEN** a list endpoint is called with `PaginationParams`
- **THEN** its response conforms to the declared `Page[T]` model (items + paging metadata)

### Requirement: Swagger and ReDoc remain served

The application SHALL keep the interactive Swagger UI (`/docs`) and ReDoc (`/redoc`) served from
the default FastAPI OpenAPI generation, so the completed schema is browsable without additional
tooling.

#### Scenario: Swagger UI reflects the typed schema

- **WHEN** a developer opens `/docs`
- **THEN** the mutating endpoints display their documented request and response models

### Requirement: Schema completeness is regression-guarded

A test SHALL assert that `/openapi.json` declares a response schema for every mutating route, so
a future handler returning a bare `dict` fails CI rather than silently emptying the docs.

#### Scenario: Bare-dict handler fails the contract test

- **WHEN** a mutating route is added or changed to return an untyped `dict` with no `response_model`
- **THEN** the schema-completeness test fails
