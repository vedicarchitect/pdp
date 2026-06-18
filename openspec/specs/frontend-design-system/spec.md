# Frontend Design System — Spec

## Purpose

Defines the global design language for the PDP frontend, including design tokens, dark mode aesthetic, and glassmorphism effects. All UI components SHALL consume these standards rather than hardcoded values.

## Requirements

### Requirement: Design Tokens and Variables
The frontend SHALL implement a global set of design tokens (CSS variables) for colors, typography, spacing, and border radii.

#### Scenario: Theming the application
- **WHEN** a developer creates a new UI component
- **THEN** they MUST use the predefined CSS variables from the design system rather than hardcoded hex codes or pixel values.

---

### Requirement: Premium Dark Mode Aesthetic
The primary visual language SHALL be a premium dark mode, utilizing tailored grays, deep blacks, and vibrant accent colors.

#### Scenario: Viewing the dashboard
- **WHEN** a user opens the application
- **THEN** the application defaults to the tailored dark mode theme.

---

### Requirement: Glassmorphism Elements
The design system SHALL provide base classes for glassmorphism effects (backdrop-blur, semi-transparent backgrounds) for overlays and floating elements.

#### Scenario: Displaying a modal or dropdown
- **WHEN** a contextual overlay such as a dropdown menu or modal is rendered
- **THEN** it SHALL exhibit a glassmorphism effect, blurring the content beneath it to create depth.

---

### Requirement: Responsive breakpoint tokens

The design system SHALL define responsive breakpoint tokens in `index.css` under `@theme`: `--breakpoint-sm: 640px`, `--breakpoint-md: 768px`, `--breakpoint-lg: 1024px`, `--breakpoint-xl: 1280px`. All layout components SHALL use these tokens for responsive behavior.

#### Scenario: Tokens are available in Tailwind classes
- **WHEN** a component uses the Tailwind class `md:grid-cols-2`
- **THEN** the layout switches to 2 columns at 768px viewport width

---

### Requirement: Chart color palette tokens

The design system SHALL define chart color tokens in `index.css`: `--color-chart-profit` (emerald), `--color-chart-loss` (red), `--color-chart-neutral` (zinc), `--color-chart-accent` (blue), and a series array `--color-chart-series-1` through `--color-chart-series-5`. The `chartTheme.ts` helper SHALL derive its palette from these tokens.

#### Scenario: Chart colors are consistent across pages
- **WHEN** the analytics page and the portfolio page both render P&L charts
- **THEN** profit is rendered in the same emerald tone and loss in the same red tone, derived from the shared chart tokens

---

### Requirement: Animation and transition tokens

The design system SHALL define animation tokens: `--duration-fast: 150ms`, `--duration-normal: 250ms`, `--duration-slow: 400ms`, and `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`. UI components SHALL use these tokens for hover, focus, and open/close transitions.

#### Scenario: Button hover transition uses design token duration
- **WHEN** a user hovers over a `Button`
- **THEN** the color transition completes in `--duration-fast` (150ms)
