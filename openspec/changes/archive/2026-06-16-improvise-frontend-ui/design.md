## Context

The current PDP frontend is a basic skeleton. While functional, it lacks the professional polish required for a modern trading platform. Users interact heavily with data-dense interfaces (order books, portfolios, charts), which demand a high-quality user experience to reduce cognitive load and increase engagement. This change introduces a comprehensive design system and UI overhaul prioritizing aesthetics, modern glassmorphism elements, dark mode, and micro-animations.

## Goals / Non-Goals

**Goals:**
- Establish a global design system (`frontend-design-system`) for colors, typography, and spacing.
- Implement a modern, premium "dark mode first" aesthetic with glassmorphism effects where appropriate.
- Introduce subtle micro-animations (`ui-animations`) for user interactions (e.g., button hovers, row highlights in order books, loading states).
- Refactor the existing frontend skeleton and critical user flows to adopt the new design system.

**Non-Goals:**
- No changes to the backend API or data models.
- No new complex features (e.g., advanced charting libraries or new trading capabilities) beyond the visual and UX improvements of existing flows.
- Not implementing a full light mode in this iteration; focusing on a premium dark mode experience typical of professional trading terminals.

## Decisions

1.  **Tailwind CSS vs Vanilla CSS**: We will use Vanilla CSS for maximum flexibility and control, adhering to the project's technology stack rules. If Shadcn UI relies heavily on Tailwind, we will configure a highly tailored, custom Tailwind theme (if explicitly allowed) or refactor components to use Vanilla CSS with CSS variables for design tokens. *Decision: Use CSS modules or Vanilla CSS with custom properties for a unique, non-generic look.*
2.  **Typography**: Adopt modern, highly legible fonts like `Inter` or `Outfit` from Google Fonts to replace browser defaults, ensuring data density remains readable.
3.  **Micro-animations**: Use CSS transitions and keyframes for high-performance UI animations (e.g., flashing green/red on price ticks in the order book) rather than heavy JavaScript animation libraries, keeping the frontend lightweight.
4.  **Glassmorphism**: Use CSS `backdrop-filter: blur()` combined with subtle semi-transparent borders and backgrounds for contextual overlays (e.g., modals, dropdowns, floating action bars).

## Risks / Trade-offs

- **Risk**: Performance impact of complex CSS effects (blur, box-shadow) on data-dense views like the order book updating at 10Hz.
  - *Mitigation*: Limit heavy effects on frequently updating components. Use hardware-accelerated CSS properties (`transform`, `opacity`) for animations.
- **Risk**: Over-engineering the CSS architecture leading to maintenance difficulties.
  - *Mitigation*: Strictly define and adhere to a set of CSS variables (design tokens) in `index.css`.

## Migration Plan

1.  Add new fonts and global CSS variables to `frontend/src/index.css`.
2.  Incrementally refactor base components (buttons, inputs, cards).
3.  Apply the new design system to main layouts and routes.
4.  Add animation hooks and classes to critical data flows (e.g., OrderBook).

## Open Questions

- Should we strictly remove Tailwind CSS if the existing skeleton uses Shadcn UI (which depends on Tailwind), or should we customize the Tailwind config extensively to break away from the "generic" look? (Recommendation: Customize Tailwind extensively via config if it's already deeply integrated, otherwise stick to Vanilla CSS).
