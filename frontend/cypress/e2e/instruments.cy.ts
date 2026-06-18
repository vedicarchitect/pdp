/// <reference types="cypress" />

describe('Instruments Page', () => {
  beforeEach(() => {
    cy.visit('/instruments')
    cy.get('h1').contains('Instruments').should('be.visible')
  })

  it('renders page header', () => {
    cy.get('h1').contains('Instruments').should('be.visible')
    cy.visualSnapshot('instruments-header')
  })

  it('renders segment filter pills', () => {
    cy.get('button').contains('All').should('be.visible')
    cy.get('button').contains('NSE_EQ').should('be.visible')
    cy.get('button').contains('NSE_FNO').should('be.visible')
    cy.visualSnapshot('instruments-filter-pills')
  })

  it('clicking NSE_FNO activates the filter', () => {
    cy.get('button').contains('NSE_FNO').click()
    cy.get('button').contains('NSE_FNO').should('have.class', 'bg-primary')
    cy.visualSnapshot('instruments-nsefno-active')
  })

  it('renders Instrument Browser card', () => {
    cy.contains('Instrument Browser').should('be.visible')
  })

  it('full instruments page visual snapshot', () => {
    cy.wait(300)
    cy.visualSnapshot('instruments-full-page')
  })
})
