## ADDED Requirements

### Requirement: Design Tokens and Variables
The frontend SHALL implement a global set of design tokens (CSS variables) for colors, typography, spacing, and border radii.

#### Scenario: Theming the application
- **WHEN** a developer creates a new UI component
- **THEN** they MUST use the predefined CSS variables from the design system rather than hardcoded hex codes or pixel values.

### Requirement: Premium Dark Mode Aesthetic
The primary visual language SHALL be a premium dark mode, utilizing tailored grays, deep blacks, and vibrant accent colors.

#### Scenario: Viewing the dashboard
- **WHEN** a user opens the application
- **THEN** the application defaults to the tailored dark mode theme.

### Requirement: Glassmorphism Elements
The design system SHALL provide base classes for glassmorphism effects (backdrop-blur, semi-transparent backgrounds) for overlays and floating elements.

#### Scenario: Displaying a modal or dropdown
- **WHEN** a contextual overlay such as a dropdown menu or modal is rendered
- **THEN** it SHALL exhibit a glassmorphism effect, blurring the content beneath it to create depth.
