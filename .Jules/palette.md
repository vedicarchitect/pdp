## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.
## 2026-06-13 - Critical Action UX
**Learning:** Destructive modal actions (like Kill Switch) need safe defaults. Adding `autoFocus` to the Cancel button and supporting Escape key dismissal prevents accidental execution from blind keyboard entry.
**Action:** Always auto-focus the safe/cancel action and attach Escape key listeners (using capturing phase if needed) for all destructive confirmation modals.
## 2024-06-15 - ARIA attributes for Modal Dialogs and Toasts
**Learning:** Destructive modal dialogs (like Kill Switch) need proper `aria-labelledby` and `aria-describedby` attributes referencing the title and description elements via IDs for screen readers to convey context accurately. Toast notifications need `role="status"` and `aria-live="polite"` to be announced dynamically when they appear. Decorative emojis must be hidden with `aria-hidden="true"`.
**Action:** Always add proper ARIA IDs and live region roles to dialogs and toasts, and hide decorative elements to ensure smooth screen reader experiences.
