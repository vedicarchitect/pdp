## ADDED Requirements

### Requirement: ML training API

The system SHALL expose `POST /api/v1/ml/train` to submit an ML training job via the job runner. The endpoint SHALL accept training parameters (model type, features, date range) and return a job record. Training SHALL run asynchronously with progress reporting.

#### Scenario: Submit ML training job
- **WHEN** `POST /api/v1/ml/train` is called with valid parameters
- **THEN** a job of type `ml_train` is created and HTTP 200 is returned with the job record

---

### Requirement: ML model listing and deployment

The system SHALL expose `GET /api/v1/ml/models` returning a list of trained models with version, accuracy metrics, and active status. `POST /api/v1/ml/deploy/{version}` SHALL set the specified version as the active model for inference.

#### Scenario: List trained models
- **WHEN** `GET /api/v1/ml/models` is called with 3 trained models
- **THEN** HTTP 200 is returned with 3 model records including version, metrics, and which is active

#### Scenario: Deploy a model version
- **WHEN** `POST /api/v1/ml/deploy/v3` is called
- **THEN** model v3 becomes the active model and HTTP 200 is returned
