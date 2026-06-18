/// <reference types="cypress" />

describe('Backtest Page', () => {
  beforeEach(() => {
    cy.visit('/backtest')
    cy.contains('Options Strategy Backtester').should('be.visible')
  })

  it('renders page header', () => {
    cy.get('h1').contains('Options Strategy Backtester').should('be.visible')
    cy.visualSnapshot('backtest-header')
  })

  it('renders strategy form panel', () => {
    cy.get('form, [data-testid="strategy-form"], .grid').should('exist')
    cy.visualSnapshot('backtest-form')
  })

  it('renders empty results state', () => {
    cy.contains('Configure a strategy and click Run Backtest').should('be.visible')
  })

  it('full backtest page visual snapshot', () => {
    cy.visualSnapshot('backtest-full-page')
  })
})
