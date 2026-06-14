# Frontend

## Stack

Vite + React 19 + TanStack Router + TanStack Query + shadcn/ui + TypeScript

```bash
cd frontend && npm run dev    # dev server (Vite)
cd frontend && npm run build  # production bundle
cd frontend && npm test       # vitest
```

## Structure

```
frontend/src/
├── App.tsx              # Root app + TanStack Router provider
├── main.tsx             # Entry point, React 19 createRoot
├── index.css            # Global CSS (CSS variables, base styles)
├── routes/              # TanStack Router file-based routes
│   ├── __root.tsx       # Root layout (nav, sidebar)
│   ├── index.tsx        # Dashboard /
│   └── ...              # Other pages
├── components/
│   ├── ui/              # shadcn/ui primitives (do NOT edit)
│   ├── market/          # Market feed components
│   ├── orders/          # Order entry + blotter
│   ├── portfolio/       # Portfolio + P&L widgets
│   ├── positional/      # Positional trades panel
│   └── strategy/        # Strategy status cards
├── hooks/               # Custom React hooks (useWebSocket, useOrders, etc.)
├── types/               # Shared TypeScript types
└── lib/                 # Utilities (api client, formatters)
```

## API Integration

Backend base URL: `http://localhost:8000` (set in env or vite config)

WebSocket endpoints:
- `ws://localhost:8000/ws/market` — tick stream
- `ws://localhost:8000/ws/orders` — fill events
- `ws://localhost:8000/ws/portfolio` — MTM P&L
- `ws://localhost:8000/ws/options` — option chain updates

Use `hooks/useWebSocket.ts` pattern for WS connections. Use TanStack Query for REST fetches.

## shadcn/ui

Components live in `components/ui/`. Add new ones via:
```bash
cd frontend && npx shadcn-ui@latest add <component>
```
Do NOT manually edit files in `components/ui/` — they are managed by shadcn.

## Active Specs

`improvise-frontend-ui` (in-flight) — UI improvement proposals.
`frontend-shell` (archived spec) — baseline layout.
