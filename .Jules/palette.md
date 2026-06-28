## 2026-06-13 - Critical Action UX
**Learning:** Destructive modal actions (like Kill Switch) need safe defaults. Adding `autoFocus` to the Cancel button and supporting Escape key dismissal prevents accidental execution from blind keyboard entry.
**Action:** Always auto-focus the safe/cancel action and attach Escape key listeners (using capturing phase if needed) for all destructive confirmation modals.

## 2026-06-28 - Add Semantic Wrappers to Badges
**Learning:** In Flutter, icon-only buttons or custom widgets like mode badges and connection status indicators need explicit Semantic and Tooltip wrappers to be accessible to screen readers, especially when they represent important state.
**Action:** Wrap custom status indicator widgets in `MergeSemantics`, `Semantics`, and `Tooltip` to ensure that screen readers announce them properly.
