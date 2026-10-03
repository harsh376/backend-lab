import assert from 'node:assert/strict'
import puppeteer, { type Browser, type Page } from 'puppeteer'
import { createServer, type ViteDevServer } from 'vite'

const PORT = 5199

describe('App', () => {
  let server: ViteDevServer
  let browser: Browser
  let page: Page

  before(async () => {
    // Start Vite in-process using your vite.config.ts
    server = await createServer({ server: { port: PORT, strictPort: true } })
    await server.listen()
    browser = await puppeteer.launch({
      headless: !process.env.HEADFUL, // HEADFUL=1 npm run test:e2e to watch it
    })
  })

  after(async () => {
    await browser?.close()
    await server?.close()
  })

  beforeEach(async () => {
    page = await browser.newPage()
    await page.goto(`http://localhost:${PORT}`)
    await page.waitForSelector('button:not(:disabled)') // Initial load done
  })

  afterEach(async () => {
    await page?.close()
  })

  it('loads all items on page load', async () => {
    const count = await page.$$eval('li', (lis) => lis.length)

    assert.equal(count, 6)
  })
})
