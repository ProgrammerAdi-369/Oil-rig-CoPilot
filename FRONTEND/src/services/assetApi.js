// Thin client for the Python API (copilot/server.py). Every call returns the server's JSON or throws ApiError.
// The user is sent as X-User-Id and injected into the agent by the server; X-Field-Date simulates "yesterday".

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", user, day, body, timeout = 180000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(`/api${path}`, {
      method,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(user ? { "X-User-Id": user } : {}),
        ...(day ? { "X-Field-Date": day } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error || `Request failed (${res.status})`, res.status);
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === "AbortError") throw new ApiError("The request timed out. The model may be busy; try again.", 0);
    throw new ApiError("Cannot reach the backend. Start it with: py -m copilot.server", 0);
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  meta: () => request("/meta"),
  users: () => request("/users"),
  evidence: (id) => request(`/evidence/${encodeURIComponent(id)}`),
  chats: (user) => request("/chats", { user }),
  chat: (user, id) => request(`/chats/${encodeURIComponent(id)}`, { user }),
  deleteChat: (user, id) => request(`/chats/${encodeURIComponent(id)}`, { method: "DELETE", user }),
  send: (user, chatId, message, day) =>
    request("/chat", { method: "POST", user, day, body: { chat_id: chatId, message } }),
};
