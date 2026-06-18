// Cypress config — must be .js (not .ts) when package.json has "type": "module"
// Cypress picks up .js before .ts so this file wins the lookup.
import { defineConfig } from 'cypress'

export default defineConfig({
  e2e: {
    baseUrl: 'http://localhost:5173',
    specPattern: 'cypress/e2e/**/*.cy.{ts,tsx}',
    supportFile: 'cypress/support/e2e.ts',
    video: false,
    screenshotOnRunFailure: true,
    viewportWidth: 1280,
    viewportHeight: 800,
    // Screenshots saved to cypress/screenshots/ — zero cost, no API key needed.
    // Applitools visual regression (optional): register free key at applitools.com,
    // then set APPLITOOLS_API_KEY and uncomment in cypress/support/e2e.ts.
  },
})
