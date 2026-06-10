## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.

## 2026-06-10 - Screen Reader Clutter for Visual Adornments
**Learning:** Purely decorative text elements attached to inputs (like % or currency symbols) create confusing readouts in screen readers if they aren't hidden, particularly when the label already implies the unit context.
**Action:** Use `aria-hidden="true"` on span elements used as visual decorators to keep the accessible DOM clean and prevent repetitive or confusing screen reader announcements.