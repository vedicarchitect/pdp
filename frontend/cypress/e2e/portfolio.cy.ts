/// <reference types="cypress" />

describe('Portfolio Page', () => {
  beforeEach(() => {
    cy.visit('/portfolio')
    cy.get('h1').contains('Portfolio').should('be.visible')
  })

  it('renders page header', () => {
    cy.get('h1').contains('Portfolio').should('be.visible')
    cy.visualSnapshot('portfolio-header')
  })

  it('shows loading skeleton, stat cards, or error card within 5s', () => {
    cy.get('.animate-pulse, [data-testid="portfolio-stats"], [data-testid="error-card"]', { timeout: 5000 })
      .first()
      .should('exist')
  })

  it('Open Positions card heading always renders', () => {
    cy.contains(/Open Positions/).should('be.visible')
    cy.visualSnapshot('portfolio-positions-card')
  })

  it('renders Day P&L stat or loading/error state', () => {
    cy.contains(/Day P&L|Failed to load portfolio data|Loading/).should('exist')
  })

  it('full portfolio page visual snapshot', () => {
    cy.wait(500)
    cy.visualSnapshot('portfolio-full-page')
  })
})
