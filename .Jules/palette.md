## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.
## 2026-06-13 - Critical Action UX
**Learning:** Destructive modal actions (like Kill Switch) need safe defaults. Adding `autoFocus` to the Cancel button and supporting Escape key dismissal prevents accidental execution from blind keyboard entry.
**Action:** Always auto-focus the safe/cancel action and attach Escape key listeners (using capturing phase if needed) for all destructive confirmation modals.
## 2026-07-01 - Tooltips Act as ARIA Labels in Flutter
**Learning:** In Flutter, `IconButton` widgets without text labels are completely inaccessible to screen readers unless they have a `tooltip` property, which acts as both the hover text and the semantic accessibility label.
**Action:** Always provide a descriptive `tooltip` property for icon-only buttons to ensure a11y compliance and improve desktop hover usability.
