## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.
## 2026-06-13 - Critical Action UX
**Learning:** Destructive modal actions (like Kill Switch) need safe defaults. Adding `autoFocus` to the Cancel button and supporting Escape key dismissal prevents accidental execution from blind keyboard entry.
**Action:** Always auto-focus the safe/cancel action and attach Escape key listeners (using capturing phase if needed) for all destructive confirmation modals.
