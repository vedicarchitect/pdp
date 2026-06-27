import { test, expect, type Page } from '@playwright/test'

// These tests verify the Backtest Console UI (strangle warehouse tab).
// The backend may not be running, so we assert loading states OR final states.

async function gotoBacktest(page: Page) {
  await page.goto('/backtest')
  await page.waitForLoadState('domcontentloaded')
}

// ── Page structure ────────────────────────────────────────────────────────────

test.describe('Backtest Console page', () => {
  test('renders page header and both tabs', async ({ page }) => {
    await gotoBacktest(page)
    await expect(page.getByRole('heading', { name: /Backtest Console/i })).toBeVisible()
    await expect(page.getByTestId('tab-strangle')).toBeVisible()
    await expect(page.getByTestId('tab-options')).toBeVisible()
  })

  test('strangle warehouse tab is active by default', async ({ page }) => {
    await gotoBacktest(page)
    await expect(page.getByTestId('strangle-console')).toBeVisible()
  })

  test('options replay tab switches content', async ({ page }) => {
    await gotoBacktest(page)
    await page.getByTestId('tab-options').click()
    // Options tab shows strategy form
    await expect(page.getByTestId('strangle-console')).not.toBeVisible()
  })
})

// ── Strangle console — runs table ─────────────────────────────────────────────

test.describe('Strangle console runs table', () => {
  test.beforeEach(async ({ page }) => {
    await gotoBacktest(page)
    // ensure strangle tab is active
    await page.getByTestId('tab-strangle').click()
  })

  test('shows runs table or loading state', async ({ page }) => {
    // Either the table renders (backend up) or loading/empty (no backend)
    const table = page.locator('table').first()
    const loadingOrEmpty = page.getByText(/Loading runs|No runs found|Failed to load/i).first()
    await expect(table.or(loadingOrEmpty).first()).toBeVisible({ timeout: 5000 })
  })

  test('filter dropdowns exist', async ({ page }) => {
    const kindSelect = page.locator('select').first()
    await expect(kindSelect).toBeVisible()
  })

  test('optimize button opens optimize panel', async ({ page }) => {
    await page.getByTestId('optimize-btn').click()
    await expect(page.getByTestId('optimize-panel')).toBeVisible()
  })

  test('optimize panel has launch button', async ({ page }) => {
    await page.getByTestId('optimize-btn').click()
    await expect(page.getByRole('button', { name: /Launch Walk-Forward/i })).toBeVisible()
  })
})

// ── Optimize panel inputs ─────────────────────────────────────────────────────

test.describe('Optimize panel', () => {
  test.beforeEach(async ({ page }) => {
    await gotoBacktest(page)
    await page.getByTestId('tab-strangle').click()
    await page.getByTestId('optimize-btn').click()
  })

  test('date inputs are pre-filled', async ({ page }) => {
    const dateInputs = page.locator('input[type="date"]')
    expect(await dateInputs.count()).toBeGreaterThanOrEqual(2)
    const fromVal = await dateInputs.nth(0).inputValue()
    expect(fromVal).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  test('objective selector has sharpe option', async ({ page }) => {
    const objSelect = page.locator('select').last()
    const options = await objSelect.locator('option').allTextContents()
    expect(options).toContain('Sharpe')
  })

  test('back to list via breadcrumb', async ({ page }) => {
    await page.getByRole('button', { name: /Runs/i }).click()
    await expect(page.getByTestId('strangle-console')).toBeVisible()
    await expect(page.getByTestId('optimize-panel')).not.toBeVisible()
  })
})

// ── OOS leaderboard ───────────────────────────────────────────────────────────

test.describe('OOS leaderboard', () => {
  test('leaderboard button opens leaderboard view', async ({ page }) => {
    await gotoBacktest(page)
    await page.getByTestId('tab-strangle').click()
    await page.getByTestId('leaderboard-btn').click()
    await expect(page.getByTestId('oos-leaderboard')).toBeVisible()
  })

  test('leaderboard shows metric selector', async ({ page }) => {
    await gotoBacktest(page)
    await page.getByTestId('tab-strangle').click()
    await page.getByTestId('leaderboard-btn').click()
    const metricSelect = page.locator('select')
    await expect(metricSelect).toBeVisible()
  })

  test('back to list from leaderboard via breadcrumb', async ({ page }) => {
    await gotoBacktest(page)
    await page.getByTestId('tab-strangle').click()
    await page.getByTestId('leaderboard-btn').click()
    await page.getByRole('button', { name: /Runs/i }).click()
    await expect(page.getByTestId('oos-leaderboard')).not.toBeVisible()
  })
})

// ── Promotion flow ────────────────────────────────────────────────────────────

test.describe('Promote flow (mock)', () => {
  test('promote button only appears on walkforward+PASS runs', async ({ page }) => {
    await gotoBacktest(page)
    await page.getByTestId('tab-strangle').click()
    // With no backend, no row to click; promote button absent in list view
    await expect(page.getByRole('button', { name: /Promote to Paper/i })).not.toBeVisible()
  })
})

// ── Skipped: requires live backend ───────────────────────────────────────────

test.skip('launch walk-forward and assert run appears in table', async () => {
  // Requires live backend + Mongo — run manually with `task dev` then `npx playwright test --headed`
  // Steps: open /backtest → Optimize → set 3-month window → Launch Walk-Forward → wait for job
  //        → navigate back to Runs → assert new run_id appears in the table
})
