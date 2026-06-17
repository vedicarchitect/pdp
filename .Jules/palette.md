## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.
## 2026-06-13 - Critical Action UX
**Learning:** Destructive modal actions (like Kill Switch) need safe defaults. Adding `autoFocus` to the Cancel button and supporting Escape key dismissal prevents accidental execution from blind keyboard entry.
**Action:** Always auto-focus the safe/cancel action and attach Escape key listeners (using capturing phase if needed) for all destructive confirmation modals.
## 2026-06-17 - Accessibility Attributes Refinement
**Learning:** Found multiple instances where semantic ARIA attributes were missing from key interaction points, such as dialog components lacking aria-labelledby and forms using unstructured spans instead of proper labels. Also found instances where emojis were read by screen readers instead of being hidden with aria-hidden.
**Action:** Always verify components functioning as dialogs have aria-labelledby/-describedby, explicitly associate input elements with their labels via ID, and hide decorative characters with aria-hidden to ensure a clean screen reader experience.
