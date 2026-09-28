const queryInput = document.getElementById("query");
const genreSelect = document.getElementById("genre");
const btn = document.getElementById("btn");
const stateEl = document.getElementById("state");
const loadingEl = document.getElementById("loading");
const errorEl = document.getElementById("error");
const resultsEl = document.getElementById("results");

// TODO: point this at the real search endpoint
const SEARCH_URL = "http://localhost:8000/search";
const USE_MOCK = true;

const BOOKS = [
  { title: "The Shining", genre: "horror" },
  { title: "Dracula", genre: "horror" },
  { title: "Frankenstein", genre: "horror" },
  { title: "The Haunting of Hill House", genre: "horror" },
  { title: "Good Omens", genre: "comedy" },
  { title: "Catch-22", genre: "comedy" },
  { title: "The Hitchhiker's Guide to the Galaxy", genre: "comedy" },
  { title: "Three Men in a Boat", genre: "comedy" },
];

// stands in for the real endpoint: filters BOOKS by q/genre after a random delay
async function mockFetch(url) {
  const params = new URL(url).searchParams;
  const q = (params.get("q") ?? "").toLowerCase();
  const genre = params.get("genre");

  await new Promise((resolve) => setTimeout(resolve, 300 + Math.random() * 700));

  const results = BOOKS.filter(
    (book) =>
      book.title.toLowerCase().includes(q) && (!genre || book.genre === genre),
  );
  return new Response(JSON.stringify(results), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchBooks = USE_MOCK ? mockFetch : fetch;

let state = {
  query: "",
  genre: "",
  submitted: null, // the last search the user ran
  loading: false,
  results: null,
  error: null,
};

function setState(patch) {
  state = { ...state, ...patch };
  render();
}

function render() {
  // state → inputs
  queryInput.value = state.query;
  genreSelect.value = state.genre;

  // state → display
  loadingEl.hidden = !state.loading;
  btn.disabled = state.loading;
  errorEl.hidden = !state.error;
  errorEl.textContent = state.error ?? "";
  renderResults();
  stateEl.textContent = JSON.stringify(state, null, 2);
}

// assumes the API returns an array of { title, genre? }
function renderResults() {
  resultsEl.replaceChildren();
  if (state.loading || state.error || state.results === null) return;

  if (state.results.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No results";
    resultsEl.append(li);
    return;
  }

  for (const item of state.results) {
    const li = document.createElement("li");
    li.textContent = item.genre ? `${item.title} (${item.genre})` : item.title;
    resultsEl.append(li);
  }
}

// inputs → state
queryInput.addEventListener("input", (e) => {
  setState({ query: e.target.value });
});

genreSelect.addEventListener("change", (e) => {
  setState({ genre: e.target.value });
});

async function search({ query, genre }) {
  const params = new URLSearchParams({ q: query });
  if (genre) params.set("genre", genre);

  setState({ loading: true, error: null });
  try {
    const response = await fetchBooks(`${SEARCH_URL}?${params}`);
    if (!response.ok) {
      throw new Error(`Response status: ${response.status}`);
    }
    const results = await response.json();
    // ignore responses for searches that have since been replaced
    if (state.submitted.query !== query || state.submitted.genre !== genre) return;
    setState({ results, loading: false });
  } catch (error) {
    if (state.submitted.query !== query || state.submitted.genre !== genre) return;
    setState({ error: error.message, loading: false });
  }
}

btn.addEventListener("click", () => {
  const submitted = { query: state.query, genre: state.genre };
  setState({ submitted });
  search(submitted);
});

render();
