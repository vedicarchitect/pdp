## ADDED Requirements

### Requirement: Retired — React animation layer removed
This capability (React/CSS micro-animations, LTP flash effects) SHALL be considered retired with `frontend/`. All UI animation requirements MUST follow the Flutter approach defined in `trading-app`: restrained implicit animations (`AnimatedDefaultTextStyle`) on changing values only, no route-transition flourishes.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to `trading-app` "Dark design system" for the active Flutter animation approach

## REMOVED Requirements

### Requirement: Interactive Micro-animations
**Reason**: React/CSS animations removed with `frontend/`.
**Migration**: Flutter uses restrained implicit animations; see `trading-app` "Dark design system" and design notes.

### Requirement: Real-time Data Animations
**Reason**: React LTP/P&L flash animations removed with `frontend/`.
**Migration**: Flutter animates only changing P&L numbers via `AnimatedDefaultTextStyle`; see `trading-app` "Live portfolio screen".
