## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.
## 2026-06-13 - Critical Action UX
**Learning:** Destructive modal actions (like Kill Switch) need safe defaults. Adding `autoFocus` to the Cancel button and supporting Escape key dismissal prevents accidental execution from blind keyboard entry.
**Action:** Always auto-focus the safe/cancel action and attach Escape key listeners (using capturing phase if needed) for all destructive confirmation modals.

## 2024-05-24 - Missing ARIA roles on UI emojis and Modals
**Learning:** Found a recurring pattern in the platform where decorative emojis (like ☠, ⏳, ⚠) lack `aria-hidden="true"`, causing screen readers to mistakenly announce them. Additionally, custom modals (like the Kill Switch confirm dialog) lacked `aria-labelledby` and `aria-describedby` connecting them to their respective title and descriptions, making screen reader context confusing.
**Action:** Always add `aria-hidden="true"` to decorative emojis across all components. Ensure custom modals implement proper `aria-labelledby` and `aria-describedby` IDs to link their container with their internal title and content text.
