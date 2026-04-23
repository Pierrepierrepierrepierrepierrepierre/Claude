// Helper API : tolère que le caller passe soit "/api/foo" soit "/foo".
// Évite le bug historique où certains appels finissaient en /api/api/foo.
function _normalize(path) {
  if (path.startsWith("/api")) return path;
  return path.startsWith("/") ? `/api${path}` : `/api/${path}`;
}

const API = {
  async get(path) {
    const url = _normalize(path);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`GET ${url} → ${res.status}`);
    return res.json();
  },
  async post(path, body) {
    const url = _normalize(path);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`POST ${url} → ${res.status}`);
    return res.json();
  },
};
