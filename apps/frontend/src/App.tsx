import { useEffect, useState } from 'react'
import './App.css'

type Status = 'all' | 'available' | 'not_available'
type ItemType = 'all' | 'book' | 'device'
type Item = {
  id: number
  name: string
  item_type: Exclude<ItemType, 'all'>
  status: Exclude<Status, 'all'>
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
  const [status, setStatus] = useState<Status>('all')
  const [itemType, setItemType] = useState<ItemType>('all')
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const loadItems = async () => {
    const params = new URLSearchParams()
    const trimmedQuery = query.trim()
    if (trimmedQuery) params.set('query', trimmedQuery)
    if (status !== 'all') params.set('status', status)
    if (itemType !== 'all') params.set('item_type', itemType)

    const queryString = params.toString()
    const url = queryString ? `/api/items?${queryString}` : '/api/items'

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
    <div>
      <input
        aria-label="Search items"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <select
        aria-label="Item type"
        value={itemType}
        onChange={(e) => setItemType(e.target.value as ItemType)}
      >
        <option value="all">All</option>
        <option value="book">Book</option>
        <option value="device">Device</option>
      </select>

      <select
        aria-label="Status"
        value={status}
        onChange={(e) => setStatus(e.target.value as Status)}
      >
        <option value="all">All</option>
        <option value="available">Available</option>
        <option value="not_available">Unavailable</option>
      </select>

      <button onClick={loadItems} disabled={loading}>
        {loading ? 'Loading…' : 'Search'}
      </button>

      {error && <p>Couldn't load items.</p>}

      <ul>
        {items.map((item) => (
          <li key={item.id}>
            {item.name} — {item.item_type},{' '}
            {item.status === 'available' ? 'Available' : 'Unavailable'}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default App
