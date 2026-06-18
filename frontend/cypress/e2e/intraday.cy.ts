/// <reference types="cypress" />

describe('Intraday Page', () => {
  beforeEach(() => {
    cy.visit('/intraday')
    cy.get('body').should('be.visible')
    // wait for React to render — sidebar + main always present once JS runs
    cy.get('main').should('exist')
  })

  it('renders nav sidebar on intraday page', () => {
    cy.get('nav, aside, [data-testid="sidebar"]').should('exist')
    cy.visualSnapshot('intraday-nav')
  })

  it('renders position table or loading/empty state', () => {
    // Without backend the page shows connecting/empty state
    cy.get('main').invoke('text').should('match', /Position|Loading|No positions|Open Positions|Connecting|connecting/)
  })

  it('renders risk banner or mode badge', () => {
    cy.get('main').invoke('text').should('match', /Kill Switch|Risk|LIVE|PAPER|Connecting|connecting|paper|live/i)
  })

  it('main content area renders', () => {
    cy.get('main').should('exist')
    cy.visualSnapshot('intraday-main-region')
  })

  it('full intraday page visual snapshot', () => {
    cy.wait(500)
    cy.visualSnapshot('intraday-full-page')
  })
})
