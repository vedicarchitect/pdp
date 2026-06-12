## 2026-06-08 - Interactive Table Rows Need Keyboard Support
**Learning:** Interactive <tr> elements used for expand/collapse functionality often lack keyboard navigation (tabbing and Enter/Space triggers).
**Action:** Always add `tabIndex={0}`, `onKeyDown` handlers for Enter/Space, and appropriate ARIA attributes (`aria-expanded`) to interactive rows.
## 2026-06-12 - Rollover Panel Accessibility Improvements
**Learning:** Added explicit focus-visible UI states for a hidden conditional sub-table panel. Ensuring focus rings visually highlight interactive inputs like toggles, buttons, and inputs without relying strictly on semantic element boundaries increases accessibility for keyboard navigation.
**Action:** Apply focus-visible styling specifically along with linking controls and elements via ARIA attributes and labels to form elements inside inline sub-panels that conditionally reveal themselves.
