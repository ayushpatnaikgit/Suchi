import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Rewrite relative /api/* fetches to the local Python backend.
// In the Vite dev server this would normally be handled by the proxy in vite.config.ts,
// but the bundled Tauri app serves the frontend from a tauri:// protocol and has no
// proxy — so we rewrite any /api path to the absolute backend URL at app startup.
const API_HOST = "http://127.0.0.1:9876";
const originalFetch = window.fetch.bind(window);
window.fetch = function patchedFetch(input: RequestInfo | URL, init?: RequestInit) {
  if (typeof input === "string" && input.startsWith("/api")) {
    return originalFetch(`${API_HOST}${input}`, init);
  }
  if (input instanceof URL && input.pathname.startsWith("/api") && input.host === window.location.host) {
    return originalFetch(`${API_HOST}${input.pathname}${input.search}`, init);
  }
  if (input instanceof Request && input.url.includes("/api") && !input.url.startsWith("http")) {
    return originalFetch(new Request(`${API_HOST}${new URL(input.url, window.location.origin).pathname}`, input), init);
  }
  return originalFetch(input, init);
};

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
