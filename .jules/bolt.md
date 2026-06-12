## 2023-10-27 - Tick Data Table Re-renders
**Learning:** Frequent tick data updates (via websockets) in a data grid cause severe performance issues because every tick triggers a re-render of every row unless rows are heavily memoized. The inline lambda passed to child components also broke memoization.
**Action:** When building live-updating data tables, heavily use `React.memo` with carefully written deep-comparison equality functions for rows, and guarantee stable references via `useCallback` for event handlers passed downwards.
