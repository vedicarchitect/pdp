## ADDED Requirements

### Requirement: Retired — React design system removed
This capability (CSS/Tailwind design tokens, glassmorphism, shadcn) SHALL be considered retired with `frontend/`. All design token requirements MUST be sourced from `trading-app` "Dark design system" and `app/lib/core/theme/` instead.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to `trading-app` "Dark design system" for the active Flutter theme token requirement

## REMOVED Requirements

### Requirement: Design Tokens and Variables
**Reason**: CSS/Tailwind tokens removed with `frontend/`; Flutter centralizes tokens in `app/lib/core/theme/`.
**Migration**: See `trading-app` "Dark design system".

### Requirement: Premium Dark Mode Aesthetic
**Reason**: React dark theme removed with `frontend/`.
**Migration**: See `trading-app` "Dark design system" (`#0F172A`/`#1E2937`, `#22C55E`/`#EF4444`, Inter).

### Requirement: Glassmorphism Elements
**Reason**: React/CSS visual treatment removed with `frontend/`.
**Migration**: Dropped intentionally — the new direction is flat and minimalist.

### Requirement: Responsive breakpoint tokens
**Reason**: CSS breakpoints removed with `frontend/`.
**Migration**: Flutter uses a `LayoutBuilder` breakpoint in the shell; see `trading-app`.

### Requirement: Chart color palette tokens
**Reason**: React chart palette removed with `frontend/`.
**Migration**: Flutter chart colours come from the theme tokens; see `trading-app`.

### Requirement: Animation and transition tokens
**Reason**: CSS transition tokens removed with `frontend/`.
**Migration**: Flutter uses implicit animations on changing values only; see `trading-app`.
