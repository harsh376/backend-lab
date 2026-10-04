import { useEffect, useState } from 'react'
import './App.css'

type ItemStatus = 'all' | 'available' | 'not_available'
type ItemType = 'all' | 'device' | 'book' | 'movie'
type Item = {
  id: number
  name: string
  item_type: Exclude<ItemType, 'ALL'>
  item_status: Exclude<ItemStatus, 'all'>
}

const fetchItems = async (url: string): Promise<Item[]> => {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`GET ${url} failed: ${response.status}`)
  }
  return response.json()
}

function App() {
  const [query, setQuery] = useState('')
  const [itemStatus, setItemStatus] = useState<ItemStatus>('all')
  const [itemType, setItemType] = useState<ItemType>('all')
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const loadItems = async () => {
    const params = new URLSearchParams()
    const trimmedQuery = query.trim()
    if (trimmedQuery) params.set('search_query', trimmedQuery)
    if (itemStatus !== 'all') params.set('item_status', itemStatus)
    if (itemType !== 'all') params.set('item_type', itemType)

    const queryString = params.toString()
    const url = queryString
      ? `/api/v1/catalog-items?${queryString}`
      : '/api/v1/catalog-items'

    setLoading(true)
    setError(false)
    try {
      setItems(await fetchItems(url))
    } catch {
      setItems([])
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  // Load all items once on page load.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    loadItems()
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <main className="catalog">
      <header className="catalog-header">
        <h1>Item catalog</h1>
        <p>Find an item and check its availability.</p>
      </header>

      <div className="catalog-filters">
        <label className="catalog-field catalog-field-search">
          <span>Search items</span>
          <input
            placeholder="Search by name…"
            aria-label="Search items"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        <label className="catalog-field">
          <span>Item type</span>
          <select
            aria-label="Item type"
            value={itemType}
            onChange={(e) => setItemType(e.target.value as ItemType)}
          >
            <option value="all">All</option>
            <option value="device">Device</option>
            <option value="book">Book</option>
            <option value="movie">Movie</option>
          </select>
        </label>

        <label className="catalog-field">
          <span>Status</span>
          <select
            aria-label="Status"
            value={itemStatus}
            onChange={(e) => setItemStatus(e.target.value as ItemStatus)}
          >
            <option value="all">All</option>
            <option value="available">Available</option>
            <option value="not_available">Unavailable</option>
          </select>
        </label>

        <button aria-label="Search" onClick={loadItems} disabled={loading}>
          {loading ? 'Loading…' : 'Search'}
        </button>
      </div>

      {error && (
        <p className="catalog-error" role="alert">
          Couldn't load items.
        </p>
      )}

      <ul className="catalog-items" aria-label="Catalog items">
        {items.map((item) => (
          <li key={item.id}>
            {item.name} — {item.item_type},{' '}
            {item.item_status === 'available' ? 'Available' : 'Unavailable'}
          </li>
        ))}
      </ul>
    </main>
  )
}

export default App
