/// <reference types="cypress" />

// visualSnapshot(tag) — free, built-in Cypress screenshot.
// Saved to cypress/screenshots/ after the run.
// When APPLITOOLS_API_KEY is set and eyes commands are imported, swap body to:
//   cy.eyesCheckWindow({ tag, fully: true })
Cypress.Commands.add('visualSnapshot', (tag: string) => {
  cy.screenshot(tag, { overwrite: true })
})

declare global {
  namespace Cypress {
    interface Chainable {
      visualSnapshot(tag: string): Chainable<void>
    }
  }
}
