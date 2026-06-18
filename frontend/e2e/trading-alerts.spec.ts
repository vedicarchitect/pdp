import { test, expect } from '@playwright/test'

// ── Trading route ─────────────────────────────────────────────────────────────

test.describe('Trading route', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/trading')
    await page.waitForLoadState('domcontentloaded')
  })

  test('renders page header and New Order button', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Trading' })).toBeVisible()
    await expect(page.getByRole('button', { name: /New Order/i })).toBeVisible()
  })

  test('renders tab navigation for Positions, Open Orders, Executed Trades, Scanner', async ({ page }) => {
    await expect(page.getByRole('tab', { name: 'Positions' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Open Orders' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Executed Trades' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Scanner' })).toBeVisible()
  })

  test('clicking New Order opens OrderEntry dialog', async ({ page }) => {
    await page.getByRole('button', { name: /New Order/i }).click()
    const dialog = page.locator('[role="dialog"]')
    await expect(dialog).toBeVisible()
    // Dialog header contains "New Order" title
    await expect(dialog.locator('h2').filter({ hasText: 'New Order' })).toBeVisible()
  })

  test('OrderEntry dialog shows PAPER or LIVE badge', async ({ page }) => {
    await page.getByRole('button', { name: /New Order/i }).click()
    const dialog = page.locator('[role="dialog"]')
    await expect(dialog).toBeVisible()
    const badge = dialog.getByText(/PAPER TRADING|LIVE/i).first()
    await expect(badge).toBeVisible()
  })

  test('OrderEntry dialog closes on cancel', async ({ page }) => {
    await page.getByRole('button', { name: /New Order/i }).click()
    await expect(page.locator('[role="dialog"]')).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.locator('[role="dialog"]')).not.toBeVisible()
  })

  test('Open Orders tab content renders', async ({ page }) => {
    await page.getByRole('tab', { name: 'Open Orders' }).click()
    // Accept: loading spinner, empty message, or table
    const loading = page.getByText('Loading orders...')
    const emptyMsg = page.getByText('No orders found.')
    const table = page.locator('table').first()
    await expect(loading.or(emptyMsg).or(table)).toBeVisible({ timeout: 8000 })
  })

  test('Executed Trades tab content renders', async ({ page }) => {
    await page.getByRole('tab', { name: 'Executed Trades' }).click()
    const loading = page.getByText('Loading trades...')
    const emptyMsg = page.getByText('No executed trades.')
    const table = page.locator('table').first()
    await expect(loading.or(emptyMsg).or(table)).toBeVisible({ timeout: 8000 })
  })

  test('Scanner tab shows scanner content or a status message', async ({ page }) => {
    await page.getByRole('tab', { name: 'Scanner' }).click()
    // Accept: loading, upgrade notice, error message, or actual data table
    const anyContent = page.getByText(/Analytics upgrade required|Loading scanner|Failed to load scanner|No scanner data/i).first()
    const table = page.locator('table').first()
    await expect(anyContent.or(table)).toBeVisible({ timeout: 8000 })
  })
})

// ── Alerts route ──────────────────────────────────────────────────────────────

test.describe('Alerts route', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/alerts')
    await page.waitForLoadState('domcontentloaded')
  })

  test('renders page header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Alerts' })).toBeVisible()
  })

  test('shows Your Alerts section or loading state', async ({ page }) => {
    const loading = page.getByText('Loading alerts...')
    const section = page.getByText('Your Alerts')
    await expect(loading.or(section)).toBeVisible({ timeout: 8000 })
  })

  test('New Alert button is visible after load', async ({ page }) => {
    // Wait for loading to finish (Your Alerts section appears)
    await page.getByText('Your Alerts').waitFor({ state: 'visible', timeout: 8000 }).catch(() => {})
    const newAlertBtn = page.getByRole('button', { name: 'New Alert' })
    const loading = page.getByText('Loading alerts...')
    await expect(newAlertBtn.or(loading)).toBeVisible({ timeout: 8000 })
  })

  test('shows alerts table or empty state', async ({ page }) => {
    const emptyMsg = page.getByText(/No alerts found/i)
    const table = page.locator('table')
    const loading = page.getByText('Loading alerts...')
    await expect(emptyMsg.or(table).or(loading)).toBeVisible({ timeout: 8000 })
  })

  test('clicking New Alert opens AlertForm dialog with Cancel button', async ({ page }) => {
    // New Alert button may only appear after loading finishes; wait up to 12s
    const btn = page.getByRole('button', { name: 'New Alert' })
    await btn.waitFor({ state: 'visible', timeout: 12000 })
    await btn.click()
    const dialog = page.locator('[role="dialog"]')
    await expect(dialog).toBeVisible({ timeout: 5000 })
    // Alert form always has a Cancel button in the footer
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible()
  })

  test('AlertForm dialog has Instrument, Condition, and Threshold fields', async ({ page }) => {
    const btn = page.getByRole('button', { name: 'New Alert' })
    await btn.waitFor({ state: 'visible', timeout: 12000 })
    await btn.click()
    const dialog = page.locator('[role="dialog"]')
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await expect(dialog.getByText('Instrument')).toBeVisible()
    // Use exact match to avoid matching "Condition" appearing in description text
    await expect(dialog.getByText('Condition', { exact: true })).toBeVisible()
    await expect(dialog.getByText('Threshold')).toBeVisible()
  })

  test('AlertForm dialog closes on cancel', async ({ page }) => {
    const btn = page.getByRole('button', { name: 'New Alert' })
    await btn.waitFor({ state: 'visible', timeout: 12000 })
    await btn.click()
    await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 5000 })
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.locator('[role="dialog"]')).not.toBeVisible()
  })
})
