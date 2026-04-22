const API = {
  async get(path) {
    const res = await fetch(`/api${path}`);
    if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
    return res.json();
  },
};
