/// <reference types="cypress" />

describe('Sidebar', () => {
  beforeEach(() => {
    cy.visit('/')
    cy.get('nav').should('be.visible')
  })

  it('renders all nav group labels', () => {
    cy.get('nav').contains('TRADING').should('be.visible')
    cy.get('nav').contains('OPTIONS').should('be.visible')
    cy.get('nav').contains('DATA').should('be.visible')
    cy.get('nav').contains('SYSTEM').should('be.visible')
    cy.visualSnapshot('sidebar-nav-groups')
  })

  it('mode badge shows PAPER or LIVE label', () => {
    cy.get('nav').contains(/PAPER MODE|LIVE MODE/i).should('be.visible')
  })

  it('collapse button shrinks sidebar', () => {
    cy.window().then((win) => win.localStorage.removeItem('sidebar_collapsed'))
    cy.reload()
    cy.get('nav').first().invoke('outerWidth').should('be.greaterThan', 100)

    cy.get('nav').find('button').filter(':has(svg)').first().click()
    cy.wait(400)

    cy.get('nav').first().invoke('outerWidth').should('be.lessThan', 100)
    cy.visualSnapshot('sidebar-collapsed')

    cy.window().then((win) => win.localStorage.removeItem('sidebar_collapsed'))
  })

  it('collapsed state persists after reload', () => {
    cy.window().then((win) => win.localStorage.setItem('sidebar_collapsed', 'true'))
    cy.reload()
    // When collapsed, label spans are not rendered (conditional render, not CSS hide)
    // Verify sidebar is in compact width state
    cy.get('nav').first().invoke('outerWidth').should('be.lessThan', 100)
    cy.window().then((win) => win.localStorage.removeItem('sidebar_collapsed'))
  })

  it('mobile: sidebar starts off-screen at 375px', () => {
    cy.viewport(375, 812)
    cy.reload()
    cy.get('nav').first().should('have.class', '-translate-x-full')
    cy.visualSnapshot('sidebar-mobile-closed')
  })

  it('mobile: hamburger button is visible at 375px', () => {
    cy.viewport(375, 812)
    cy.reload()
    cy.get('button.md\\:hidden').first().should('be.visible')
  })
})
