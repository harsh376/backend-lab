import assert from 'node:assert/strict'
import puppeteer, { type Browser, type Page } from 'puppeteer'
import { createServer, type ViteDevServer } from 'vite'

const PORT = 5199

const waitForItemsLoaded = async (page: Page) => {
  await page.waitForSelector('button[aria-label="Search"]:not(:disabled)')
}

const ITEMS = [
  { id: 1, name: 'Laptop', item_type: 'device', item_status: 'available' },
  { id: 2, name: 'Phone', item_type: 'device', item_status: 'not_available' },
  { id: 3, name: 'Dune', item_type: 'book', item_status: 'available' },
  {
    id: 4,
    name: 'Dune Messiah',
    item_type: 'book',
    item_status: 'not_available',
  },
  { id: 5, name: 'Dune', item_type: 'movie', item_status: 'available' },
  { id: 6, name: 'Arrival', item_type: 'movie', item_status: 'not_available' },
]

describe('App', () => {
  let server: ViteDevServer
  let browser: Browser
  let page: Page
  let responseItems: typeof ITEMS

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
    responseItems = ITEMS
    page = await browser.newPage()
    await page.setRequestInterception(true)
    page.on('request', async (request) => {
      if (new URL(request.url()).pathname === '/api/v1/catalog-items') {
        await request.respond({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(responseItems),
        })
      } else {
        await request.continue()
      }
    })
    await page.goto(`http://localhost:${PORT}`)
    await waitForItemsLoaded(page)
  })

  afterEach(async () => {
    await page?.close()
  })

  it('loads all items on page load', async () => {
    const count = await page.$$eval('li', (lis) => lis.length)

    assert.equal(count, 6)
  })

  const cases = [
    { query: '  Dune  ', type: 'all', status: 'all', ids: [3, 4, 5] },
    { query: '', type: 'device', status: 'all', ids: [1, 2] },
    { query: '', type: 'all', status: 'available', ids: [1, 3, 5] },
    { query: '', type: 'all', status: 'not_available', ids: [2, 4, 6] },
    { query: 'Dune', type: 'book', status: 'not_available', ids: [4] },
    { query: 'Missing', type: 'movie', status: 'available', ids: [] },
    { query: '   ', type: 'all', status: 'all', ids: [1, 2, 3, 4, 5, 6] },
  ]

  const filterItems = async ({
    query,
    type,
    status,
    ids,
  }: (typeof cases)[number]) => {
    await page.click('input[aria-label="Search items"]', { clickCount: 3 })
    await page.keyboard.press('Backspace')
    await page.type('input[aria-label="Search items"]', query)
    await page.select('select[aria-label="Item type"]', type)
    await page.select('select[aria-label="Status"]', status)
    responseItems = ITEMS.filter((item) => ids.includes(item.id))

    const [response] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/v1/catalog-items',
      ),
      page.click('button[aria-label="Search"]:not(:disabled)'),
    ])
    await waitForItemsLoaded(page)

    const params: Record<string, string> = {}
    if (query.trim()) params.search_query = query.trim()
    if (type !== 'all') params.item_type = type
    if (status !== 'all') params.item_status = status
    assert.deepEqual(
      Object.fromEntries(new URL(response.url()).searchParams),
      params,
    )
    assert.deepEqual(
      await page.$$eval('li', (lis) => lis.map((li) => li.textContent)),
      responseItems.map(
        (item) =>
          `${item.name} — ${item.item_type}, ${item.item_status === 'available' ? 'Available' : 'Unavailable'}`,
      ),
    )
  }

  cases.forEach((testCase) => {
    it(`filters items with query=${JSON.stringify(testCase.query)}, type=${testCase.type}, status=${testCase.status}`, async () => {
      await filterItems(testCase)
    })
  })

  it('resets filters to show all items', async () => {
    await filterItems(cases[4]!)
    await filterItems(cases[6]!)
  })
})
