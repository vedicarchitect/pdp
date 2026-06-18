/// <reference types="cypress" />

describe('Analytics Page', () => {
  beforeEach(() => {
    cy.visit('/analytics')
    cy.contains('Options Analytics').should('be.visible')
  })

  it('renders page header and underlying selector', () => {
    cy.get('h1').contains('Options Analytics').should('be.visible')
    cy.get('select').first().should('have.value', 'NIFTY')
    cy.visualSnapshot('analytics-header')
  })

  it('renders existing Max Pain, GEX, OI Heatmap panels', () => {
    cy.contains('Max Pain').should('be.visible')
    cy.contains('Gamma Exposure (GEX)').should('be.visible')
    cy.contains('OI Heatmap & PCR').should('be.visible')
  })

  it('renders OI Buildup panel (loading or empty in paper mode)', () => {
    cy.contains(/Loading OI Buildup|No buildup data|OI Buildup/).should('be.visible')
    cy.visualSnapshot('analytics-oi-buildup')
  })

  it('renders IV Rank Gauge (loading, data or insufficient state)', () => {
    cy.contains(/Loading IV|Implied Volatility Context|Insufficient IV history|No historical IV/).should('be.visible')
    cy.visualSnapshot('analytics-iv-gauge')
  })

  it('renders Straddle History chart (loading or empty in paper mode)', () => {
    cy.contains(/Loading Straddle History|Straddle History|No straddle data/).should('be.visible')
    cy.visualSnapshot('analytics-straddle')
  })

  it('renders Multi-Strike OI chart (loading or empty in paper mode)', () => {
    cy.contains(/Loading Multi-Strike|Multi-Strike OI|No OI series/).should('be.visible')
    cy.visualSnapshot('analytics-multi-strike-oi')
  })

  it('FII/DII panel is hidden when stub returns available:false', () => {
    cy.wait(2000)
    cy.contains('Institutional Net Flows').should('not.exist')
  })

  it('underlying selector switches to BANKNIFTY', () => {
    cy.get('select').first().select('BANKNIFTY')
    cy.get('select').first().should('have.value', 'BANKNIFTY')
    cy.visualSnapshot('analytics-banknifty')
  })

  it('full analytics page visual snapshot', () => {
    cy.wait(500)
    cy.visualSnapshot('analytics-full-page')
  })
})
