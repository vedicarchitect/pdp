/** @type {import('@applitools/eyes-cypress').Configuration} */
module.exports = {
  apiKey: process.env.APPLITOOLS_API_KEY,
  // Visual checks are no-ops when API key is absent — tests still run functionally
  isDisabled: !process.env.APPLITOOLS_API_KEY,
  testConcurrency: 5,
  batchName: 'PDP Frontend',
  appName: 'PDP Trading Platform',
  browser: [
    { width: 1280, height: 800, name: 'chrome' },
    { width: 375, height: 812, name: 'chrome', deviceName: 'iPhone X' },
  ],
}
