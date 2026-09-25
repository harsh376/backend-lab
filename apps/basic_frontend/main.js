function App() {
  const [count, setCount] = React.useState(0);
  const [text, setText] = React.useState("");
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    async function loadPost() {
      try {
        const response = await fetch("https://jsonplaceholder.typicode.com/posts/1");
        if (!response.ok) {
          throw new Error(`Response status: ${response.status}`);
        }
        const result = await response.json();
        setData(result);
      } catch (error) {
        setError(error.message);
      } finally {
        setLoading(false);
      }
    }

    loadPost();
  }, []);

  return (
    <main className="container">
      <h1>React Counter</h1>
      <p>A small playground for frontend practice.</p>
      <label htmlFor="text-input">Enter text: </label>
      <input
        id="text-input"
        type="text"
        value={text}
        onChange={event => setText(event.target.value)}
      />
      <p>You typed: {text}</p>
      <div className="counter" aria-live="polite" aria-atomic="true">
        <span className="counter-label">Times clicked: </span>
        <span className="counter-value">{count}</span>
      </div>
      <div className="actions">
        <button onClick={() => setCount(current => current + 1)}>
          Click me!
        </button>
        <button className="secondary" onClick={() => setCount(0)}>
          Reset
        </button>
      </div>
      <section className="fetch-example" aria-labelledby="post-heading">
        <h2 id="post-heading">Sample post</h2>
        {loading && <p role="status">Loading post…</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {data && (
          <article>
            <h3>{data.title}</h3>
            <p>{data.body}</p>
          </article>
        )}
      </section>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
