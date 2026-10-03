# Frontend

Vite + React + TypeScript starter with hot reload and Oxlint.
Requires Node.js 20.19+ or 22.12+ and npm.

## Development

To run with the API from the repository root:

```bash
docker compose -f compose/base.yaml up --build
```

Open http://localhost:5173. Compose mounts the frontend source and enables polling
so edits trigger Vite hot reload, including on Docker Desktop. Container
dependencies live in a separate named volume; `npm ci` runs on startup to keep
them aligned with the lockfile. After changing dependencies, restart the frontend
with `docker compose -f compose/base.yaml restart frontend` from the repo root.

To run directly on your host instead:

From this directory:

```bash
npm ci
npm run dev
```

Open the local URL printed by Vite (normally http://localhost:5173).

## Connecting to FastAPI

Start the backend from the repository root:

```bash
docker compose -f compose/base.yaml up --build
```

During development, Vite proxies `/api/*` to `http://127.0.0.1:8000/*`,
removing the `/api` prefix. For example:

```ts
const response = await fetch('/api/health/live')
if (!response.ok) throw new Error(`API request failed: ${response.status}`)
const health = await response.json()
```

This keeps browser requests on the frontend origin without needing local CORS
configuration. Compose sets `API_PROXY_TARGET=http://api:8000` to reach the API
container. Set `API_PROXY_TARGET` when starting Vite if the API runs elsewhere.
The starter does not make API requests yet.

The proxy is for development only. In production, configure your hosting reverse
proxy to forward `/api/*` to FastAPI and remove the prefix, or use an explicit API
URL with appropriate backend CORS settings.

## Checks and production build

```bash
npm run lint
npm run format:check
npm run build
npm run preview
```

`build` type-checks the app and outputs static files to `dist/`. `preview` serves
that build locally; it is not a production server.

Run `npm run format` to format frontend files with Prettier. `format:check`
checks formatting without changing files.
