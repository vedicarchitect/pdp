## Context

PDP's frontend (`frontend/`) is a React 19 + TanStack Router/Query app with Tailwind v4 using `@theme` design tokens in `index.css`. It uses recharts for charts, lightweight-charts for candlestick views, and lucide-react for icons. The build tool is Vite.

Currently, each page builds its own UI ad-hoc: the intraday monitor has its own table markup, the positional monitor has different table styling, the analytics page creates cards inline, and the strategies page has its own button variants. There is no `components/ui/` directory — only three top-level components (`Sidebar.tsx`, `ModeBanner.tsx`, `CandleChart.tsx`) and three feature directories (`analytics/`, `intraday/`, `positional/`).

Three routes exist as stubs:
- `portfolio.tsx` (467 bytes) — empty placeholder
- `instruments.tsx` (493 bytes) — empty placeholder
- `backtest.tsx` (478 bytes) — empty placeholder

The existing backend APIs for portfolio (`/api/v1/portfolio/*`) and instruments (`/api/v1/instruments`) are fully functional but have no frontend consumers.

## Goals / Non-Goals

**Goals:**
- Create a reusable, consistent component library that all future proposals depend on.
- Refactor existing pages to use the shared components (reduce code duplication by ~40%).
- Make the layout responsive across desktop (≥1280px command center), tablet (768–1279px), and mobile (<768px).
- Wire the three stub routes to display real data from existing APIs.
- Establish a shared chart theming layer for visual consistency.

**Non-Goals:**
- Adding new backend endpoints or data sources.
- Building the strategy builder, backtester, or any feature-specific UI (those are separate proposals).
- Replacing recharts or lightweight-charts with a different library.
- Implementing dark/light theme toggle (keep current dark theme only, but structure tokens for future theming).

## Decisions

### D1: CVA (Class Variance Authority) for component variants

Components use CVA to define variant classes (e.g., `Button` with `variant: "primary" | "secondary" | "danger" | "ghost"`, `size: "sm" | "md" | "lg"`). CVA composes well with Tailwind and avoids runtime CSS-in-JS overhead.

```tsx
// Example: Button with CVA
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-emerald-500 text-white hover:bg-emerald-600",
        secondary: "bg-zinc-700 text-zinc-100 hover:bg-zinc-600",
        danger: "bg-red-500 text-white hover:bg-red-600",
        ghost: "hover:bg-zinc-800 text-zinc-300",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4 text-sm",
        lg: "h-10 px-6 text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  }
);
```

**Alternative considered:** shadcn/ui CLI generation. The project.md lists shadcn/ui as part of the stack, but we don't need the full CLI scaffolding — we only need the CVA pattern with our existing Tailwind v4 tokens. Building from scratch gives us full control and avoids shadcn's Radix UI dependency tree.

### D2: DataTable with TanStack Table

`DataTable` wraps `@tanstack/react-table` (already in the dependency tree via TanStack ecosystem) for sort, filter, and pagination. This replaces the manual `<table>` markup in intraday and positional monitors.

```tsx
interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T>[];
  searchable?: boolean;       // global text filter
  pageSize?: number;           // default 25
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
}
```

### D3: Command-center sidebar with collapsible nav groups

The sidebar becomes a collapsible left rail with grouped navigation:

```
┌──────────────────┐
│ PDP        [◀]   │  ← collapse toggle
├──────────────────┤
│ TRADING          │
│  ▸ Dashboard     │
│  ▸ Intraday      │
│  ▸ Positional    │
│  ▸ Strategies    │
├──────────────────┤
│ OPTIONS          │
│  ▸ Analytics     │
│  ▸ Builder  (→#2)│
├──────────────────┤
│ DATA             │
│  ▸ Portfolio     │
│  ▸ Instruments   │
│  ▸ Backtest (→#4)│
├──────────────────┤
│ SYSTEM           │
│  ▸ Events   (→#7)│
│  ▸ Alerts   (→#6)│
│  ▸ Approvals(OAC)│
│  ▸ Operations(#5)│
├──────────────────┤
│  PAPER ● KILL ▪  │  ← ModeBanner
└──────────────────┘
```

When collapsed, shows icons only with tooltips. On mobile (<768px), sidebar becomes a hamburger overlay.

### D4: Chart theme helper

`chartTheme.ts` exports a single config object consumed by both recharts and lightweight-charts:

```ts
export const chartTheme = {
  colors: {
    profit: "#10b981",   // emerald-500
    loss: "#ef4444",     // red-500
    neutral: "#71717a",  // zinc-500
    accent: "#3b82f6",   // blue-500
    series: ["#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899"],
  },
  axis: { color: "#3f3f46", fontSize: 11 },
  tooltip: { bg: "#27272a", border: "#3f3f46", text: "#fafafa" },
  grid: { color: "#27272a33" },
};
```

### D5: Portfolio route wires to existing endpoints

The `/portfolio` route fetches from:
- `GET /api/v1/portfolio/holdings` → holdings table
- `GET /api/v1/portfolio/positions` → positions table with P&L
- `GET /api/v1/portfolio/summary` → total P&L, margin used, etc.

Uses `DataTable`, `Card`, and `Badge` from the new UI kit.

### D6: Instruments route wires to existing endpoints

The `/instruments` route fetches from:
- `GET /api/v1/instruments` → searchable instrument table with filters (exchange, segment)

Uses `DataTable` with search and `Badge` for exchange segment labels.

## Risks / Trade-offs

- **CVA bundle size**: Minimal — CVA is <2KB gzipped and produces no runtime CSS. No risk.
- **TanStack Table learning curve**: The intraday/positional pages already use TanStack Query; TanStack Table is the same ecosystem. Team familiarity is assumed.
- **Refactoring existing pages**: Risk of visual regressions during migration. Mitigated by having before/after screenshots in the task verification steps.
- **No dark/light toggle**: Keeping dark-only simplifies the component library. Tokens are structured such that adding a `prefers-color-scheme` toggle later is a token-level change, not a component-level change.

## Migration Plan

1. Add `class-variance-authority` dependency (if not present).
2. Create `components/ui/` primitives — no existing code changes yet.
3. Add `chartTheme.ts` — no existing code changes yet.
4. Update `index.css` with responsive/animation/chart tokens.
5. Refactor `Sidebar.tsx` to command-center layout.
6. Migrate intraday monitor to DataTable + Card + Button.
7. Migrate positional monitor to DataTable + Card.
8. Migrate analytics panels to Card + chartTheme.
9. Wire portfolio route.
10. Wire instruments route.
11. Update backtest route with coming-soon skeleton.
12. Visual regression check on all pages.

## Open Questions

- None — this proposal uses only existing API endpoints and established frontend patterns.
