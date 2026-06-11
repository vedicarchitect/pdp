## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.

## 2026-06-11 - Input Label Associations and Busy States
**Learning:** Raw <span> tags acting as visual labels break screen reader association, and async operations often lack aria-busy attributes and loading spinners, which confuses users.
**Action:** Always convert generic text elements acting as labels into `<label htmlFor="...">` and pair them with inputs using `id`. Add `aria-busy` and explicit focus rings (`focus-visible:ring-*`) to async buttons.
