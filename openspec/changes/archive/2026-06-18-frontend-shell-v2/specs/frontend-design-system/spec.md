## MODIFIED Requirements

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
