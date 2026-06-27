import { test, expect } from '@playwright/test'

// ── Sidebar ──────────────────────────────────────────────────────────────────

test.describe('Sidebar', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
  })

  test('renders nav groups TRADING, OPTIONS, DATA, SYSTEM', async ({ page }) => {
    const nav = page.locator('nav')
    // Use exact text match to hit only the section header divs
    await expect(nav.getByText('TRADING', { exact: true }).first()).toBeVisible()
    await expect(nav.getByText('OPTIONS', { exact: true }).first()).toBeVisible()
    await expect(nav.getByText('DATA', { exact: true })).toBeVisible()
    await expect(nav.getByText('SYSTEM', { exact: true })).toBeVisible()
  })

  test('collapse toggle shrinks sidebar width and hides text', async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem('sidebar_collapsed'))
    await page.reload()
    await page.waitForLoadState('domcontentloaded')

    const nav = page.locator('nav').first()

    // Expanded: nav should be ~256px wide
    const expandedBox = await nav.boundingBox()
    expect(expandedBox?.width).toBeGreaterThan(100)

    // Click the desktop collapse toggle
    const collapseBtn = page.locator('nav').getByRole('button').filter({ has: page.locator('svg') }).first()
    await collapseBtn.click()
    await page.waitForTimeout(400) // wait for CSS transition

    // Collapsed: nav should be ~68px wide
    const collapsedBox = await nav.boundingBox()
    expect(collapsedBox?.width).toBeLessThan(100)

    await page.evaluate(() => localStorage.removeItem('sidebar_collapsed'))
  })

  test('collapsed state persists after reload', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('sidebar_collapsed', 'true'))
    await page.reload()
    await page.waitForLoadState('domcontentloaded')
    const dashboardLabel = page.locator('nav span').filter({ hasText: /^Dashboard$/ }).first()
    await expect(dashboardLabel).not.toBeVisible()
    await page.evaluate(() => localStorage.removeItem('sidebar_collapsed'))
  })

  test('mode badge visible in sidebar footer', async ({ page }) => {
    const nav = page.locator('nav')
    // ModeBanner renders "PAPER MODE" or "LIVE MODE" text
    const badge = nav.getByText(/PAPER MODE|LIVE MODE/i).first()
    await expect(badge).toBeVisible()
  })
})

// ── UI Kit components ─────────────────────────────────────────────────────────

test.describe('UI Kit — Strategies page', () => {
  test('renders page header using Card + Button', async ({ page }) => {
    await page.goto('/strategies')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('h1').filter({ hasText: 'Strategies' })).toBeVisible()
  })
})

// ── Analytics page ─────────────────────────────────────────────────────────────

test.describe('Analytics page', () => {
  test('renders Card containers for Max Pain, GEX, OI Heatmap', async ({ page }) => {
    await page.goto('/analytics')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('Max Pain')).toBeVisible()
    await expect(page.getByText('Gamma Exposure (GEX)')).toBeVisible()
    await expect(page.getByText('OI Heatmap & PCR')).toBeVisible()
  })

  test('underlying selector changes between NIFTY and BANKNIFTY', async ({ page }) => {
    await page.goto('/analytics')
    await page.waitForLoadState('domcontentloaded')
    const select = page.locator('select').first()
    await select.selectOption('BANKNIFTY')
    await expect(select).toHaveValue('BANKNIFTY')
  })
})

// ── Portfolio route ───────────────────────────────────────────────────────────

test.describe('Portfolio route', () => {
  test('renders page header', async ({ page }) => {
    await page.goto('/portfolio')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('h1').filter({ hasText: 'Portfolio' })).toBeVisible()
  })

  test('shows loading skeleton then stat cards or error card', async ({ page }) => {
    await page.goto('/portfolio')
    await page.waitForLoadState('domcontentloaded')
    // During load: skeleton is visible immediately; after retries: stat card or error card
    const skeleton = page.locator('.animate-pulse').first()
    const statCard = page.getByText('Day P&L')
    const errCard = page.getByText('Failed to load portfolio data')
    // At least one of: skeleton (loading) OR resolved state must be visible
    await expect(skeleton.or(statCard).or(errCard)).toBeVisible({ timeout: 5000 })
  })

  test('Open Positions card title is always rendered', async ({ page }) => {
    await page.goto('/portfolio')
    await page.waitForLoadState('domcontentloaded')
    // CardTitle "Open Positions" renders immediately regardless of API state
    await expect(page.getByRole('heading', { name: 'Open Positions' })).toBeVisible()
  })
})

// ── Instruments route ─────────────────────────────────────────────────────────

test.describe('Instruments route', () => {
  test('renders page header', async ({ page }) => {
    await page.goto('/instruments')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('h1').filter({ hasText: 'Instruments' })).toBeVisible()
  })

  test('segment filter pills are rendered', async ({ page }) => {
    await page.goto('/instruments')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByRole('button', { name: 'All' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'NSE_EQ' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'NSE_FNO' })).toBeVisible()
  })

  test('clicking a segment filter marks it as active', async ({ page }) => {
    await page.goto('/instruments')
    await page.waitForLoadState('domcontentloaded')
    const nseBtn = page.getByRole('button', { name: 'NSE_FNO' })
    await nseBtn.click()
    await expect(nseBtn).toHaveClass(/bg-primary/)
  })

  test('renders Instrument Browser card', async ({ page }) => {
    await page.goto('/instruments')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('Instrument Browser')).toBeVisible()
  })
})

// ── Backtest route ────────────────────────────────────────────────────────────

test.describe('Backtest route', () => {
  test('renders backtest console with strangle warehouse tab', async ({ page }) => {
    await page.goto('/backtest')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('h1').filter({ hasText: 'Backtest Console' })).toBeVisible()
    await expect(page.getByTestId('tab-strangle')).toBeVisible()
    await expect(page.getByTestId('tab-options')).toBeVisible()
  })

  test('options replay tab shows strategy form', async ({ page }) => {
    await page.goto('/backtest')
    await page.waitForLoadState('domcontentloaded')
    await page.getByTestId('tab-options').click()
    await expect(page.getByText('Configure a strategy and click Run Backtest')).toBeVisible()
  })
})

// ── Responsive sidebar ────────────────────────────────────────────────────────

test.describe('Responsive — mobile sidebar', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('hamburger button is visible on mobile', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
    // The mobile hamburger is outside the sidebar nav, positioned fixed top-left
    const hamburger = page.locator('button.md\\:hidden').first()
    await expect(hamburger).toBeVisible()
  })

  test('sidebar nav is off-screen by default on mobile', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
    // Nav starts with -translate-x-full so it's off-screen
    const nav = page.locator('nav').first()
    await expect(nav).toHaveClass(/-translate-x-full/)
  })
})

// ── Builder route ─────────────────────────────────────────────────────────────

test.describe('Builder route', () => {
  test('renders Strategy Builder heading', async ({ page }) => {
    await page.goto('/builder')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('h1').filter({ hasText: 'Strategy Builder' })).toBeVisible()
  })

  test('underlying selector renders with NIFTY default', async ({ page }) => {
    await page.goto('/builder')
    await page.waitForLoadState('domcontentloaded')
    const select = page.locator('select').first()
    await expect(select).toHaveValue('NIFTY')
  })

  test('Readymade Templates card renders or shows loading', async ({ page }) => {
    await page.goto('/builder')
    await page.waitForLoadState('domcontentloaded')
    const templates = page.getByText('Readymade Templates')
    const loading = page.getByText('Loading templates...')
    await expect(templates.or(loading)).toBeVisible({ timeout: 5000 })
  })

  test('legs table empty state renders', async ({ page }) => {
    await page.goto('/builder')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('No legs added. Select a template or add a leg from the chain.')).toBeVisible()
  })

  test('Add Custom Leg button renders', async ({ page }) => {
    await page.goto('/builder')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByRole('button', { name: /Add Custom Leg/i })).toBeVisible()
  })

  test('payoff chart empty state renders', async ({ page }) => {
    await page.goto('/builder')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('Add legs to see payoff chart')).toBeVisible()
  })

  test('Builder link exists in sidebar regardless of collapse state', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
    const nav = page.locator('nav')
    await expect(nav.locator('a[href="/builder"]')).toBeAttached()
  })
})

// ── Positional route ──────────────────────────────────────────────────────────

test.describe('Positional route', () => {
  test('renders Positional Positions heading', async ({ page }) => {
    await page.goto('/positional')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('h1').filter({ hasText: /Positional/i })).toBeVisible()
  })

  test('shows connecting state, no positions state, or positions table', async ({ page }) => {
    await page.goto('/positional')
    await page.waitForLoadState('domcontentloaded')
    const connecting = page.getByText(/Connecting to portfolio feed/i)
    const noPositions = page.getByText(/No open positions/i)
    const table = page.locator('table')
    await expect(connecting.or(noPositions).or(table)).toBeVisible({ timeout: 5000 })
  })

  test('ExpiryAlertPanel renders or is hidden when no positions', async ({ page }) => {
    await page.goto('/positional')
    await page.waitForLoadState('domcontentloaded')
    const panel = page.locator('[data-testid="expiry-alert-panel"]')
    const noPositions = page.getByText(/No open positions/i)
    // Panel only shows when positions exist with near-expiry legs; no-positions state is valid
    await expect(noPositions.or(panel)).toBeAttached({ timeout: 5000 })
  })

  test('Daily P&L History section renders', async ({ page }) => {
    await page.goto('/positional')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText(/Daily P&L History/i)).toBeVisible({ timeout: 5000 })
  })

  test('Positional link exists in sidebar', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
    const nav = page.locator('nav')
    await expect(nav.locator('a[href="/positional"]')).toBeAttached()
  })
})

// ── Dialog accessibility ──────────────────────────────────────────────────────

test.describe('Dialog accessibility', () => {
  test('Dialog has role=dialog and aria-modal when open on intraday', async ({ page }) => {
    await page.goto('/intraday')
    await page.waitForLoadState('domcontentloaded')
    const closeBtn = page.getByRole('button', { name: 'Close' }).first()
    const hasClose = await closeBtn.isVisible().catch(() => false)
    if (!hasClose) {
      test.skip()
      return
    }
    await closeBtn.click()
    await expect(page.locator('[role="dialog"]')).toBeVisible()
    await expect(page.locator('[aria-modal="true"]')).toBeVisible()
  })
})
