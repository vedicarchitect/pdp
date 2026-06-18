# Frontend UI Kit — Spec

## Purpose

Defines the reusable CVA-based component library for the PDP frontend. All UI surfaces SHALL use these components rather than ad-hoc inline markup.

## Requirements

### Requirement: Reusable UI component library

The system SHALL provide a shared component library under `frontend/src/components/ui/` containing at minimum: `Button`, `DataTable`, `Dialog`, `Tabs`, `Card`, `Select`, `Input`, `NumberField`, `Switch`, `Toast`, `Badge`, `Skeleton`, and `Tooltip`. All components SHALL use Class Variance Authority (CVA) for variant management and consume design tokens from `index.css`.

#### Scenario: Button renders with correct variant styling
- **WHEN** a `Button` component is rendered with `variant="primary"`
- **THEN** it applies the primary color scheme (emerald background, white text) and correct size classes

#### Scenario: Button renders all variant types
- **WHEN** a `Button` component is rendered with `variant="danger"`
- **THEN** it applies the danger color scheme (red background, white text)

---

### Requirement: DataTable with sort, filter, and pagination

The `DataTable` component SHALL wrap `@tanstack/react-table` and support: column sorting (click header to toggle asc/desc/none), global text search filtering (when `searchable=true`), row pagination (default `pageSize=25`), row click handler (`onRowClick`), and a configurable empty state message (`emptyMessage`). Sort direction SHALL be indicated by arrow icons in column headers.

#### Scenario: DataTable sorts by column
- **WHEN** a user clicks a sortable column header
- **THEN** the table rows re-order by that column ascending, and a subsequent click reverses to descending

#### Scenario: DataTable filters by search text
- **WHEN** a user types "NIFTY" into the search input of a `searchable` DataTable
- **THEN** only rows containing "NIFTY" in any column are displayed

#### Scenario: DataTable paginates
- **WHEN** a DataTable has 100 rows and `pageSize=25`
- **THEN** only 25 rows are displayed, and pagination controls show 4 pages

#### Scenario: DataTable shows empty message
- **WHEN** a DataTable has zero rows
- **THEN** the configured `emptyMessage` is displayed instead of an empty table

---

### Requirement: Dialog modal with focus trap

The `Dialog` component SHALL render a modal overlay with: a title, optional description, close button (X), overlay click-to-close (configurable), keyboard Escape to close, and focus trap within the dialog while open. The dialog SHALL use `role="dialog"` and `aria-modal="true"`.

#### Scenario: Dialog opens and traps focus
- **WHEN** a Dialog is opened
- **THEN** focus moves to the first focusable element inside the dialog, and Tab cycling stays within the dialog

#### Scenario: Dialog closes on Escape
- **WHEN** a Dialog is open and the user presses Escape
- **THEN** the dialog closes and focus returns to the trigger element

---

### Requirement: Toast notification system

The `Toast` component SHALL support variants `success`, `error`, `info`, and `warning`. Toasts SHALL auto-dismiss after a configurable duration (default 5 seconds), stack in the bottom-right corner, and support manual dismiss via a close button. A `useToast()` hook SHALL provide `toast({ variant, title, description })` for imperative invocation.

#### Scenario: Success toast auto-dismisses
- **WHEN** `toast({ variant: "success", title: "Order approved" })` is called
- **THEN** a green success toast appears in the bottom-right and disappears after 5 seconds

#### Scenario: Multiple toasts stack
- **WHEN** three toasts are triggered in rapid succession
- **THEN** all three are visible stacked vertically, each dismissing independently

---

### Requirement: Barrel export for component library

The file `frontend/src/components/ui/index.ts` SHALL export all UI components from the library so that consumers can import with a single path: `import { Button, Card, DataTable } from "@/components/ui"`.

#### Scenario: Single import path works
- **WHEN** a route file imports `{ Button, Card, Badge }` from `"@/components/ui"`
- **THEN** the import resolves successfully and the components render correctly
