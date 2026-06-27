## ADDED Requirements

### Requirement: Retired — React CVA UI kit removed
This capability (React CVA component library) SHALL be considered retired with `frontend/`. Future shared widget requirements MUST be specified as Flutter Material widgets or entries in `app/lib/shared/widgets/` under the `trading-app` capability.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to `trading-app` and `app/lib/shared/widgets/` for active Flutter shared-widget requirements

## REMOVED Requirements

### Requirement: Reusable UI component library
**Reason**: The React CVA UI kit is removed with `frontend/`; Flutter uses Material widgets + shared widgets in `app/lib/shared/`.
**Migration**: None — superseded by `trading-app`.

### Requirement: DataTable with sort, filter, and pagination
**Reason**: React-only component removed with `frontend/`.
**Migration**: Future Flutter screens use `ListView.builder` / data tables as needed; not part of this slice.

### Requirement: Dialog modal with focus trap
**Reason**: React-only component removed with `frontend/`.
**Migration**: Flutter provides native dialogs; reintroduced per-feature later.

### Requirement: Toast notification system
**Reason**: React-only component removed with `frontend/`.
**Migration**: Flutter uses `SnackBar`/overlays; reintroduced per-feature later.

### Requirement: Barrel export for component library
**Reason**: React/TS module convention removed with `frontend/`.
**Migration**: None — Dart imports replace barrel exports.
