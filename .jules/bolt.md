## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.
## 2024-07-08 - Running Linter Formatting Safely
**Learning:** Running `ruff check --fix` globally can unexpectedly modify many files with unrelated formatting and import changes, polluting the PR and causing potential merge conflicts.
**Action:** When fixing linting errors, only run fixes on the specific files targeted for modification, avoiding global `--fix` flags.
