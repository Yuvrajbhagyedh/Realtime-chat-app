const TOKEN_KEY = "relay_token";
const USER_KEY = "relay_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function setSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

async function request(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  if (res.status === 401) {
    clearSession();
    if (!path.includes("/auth/")) window.location.assign("/login");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return data;
}

export const api = {
  register: (payload) => request("/api/auth/register", { method: "POST", body: payload }),
  login: async (username, password) => {
    const form = new URLSearchParams();
    form.set("username", username);
    form.set("password", password);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed");
    return data;
  },
  me: () => request("/api/users/me"),
  searchUsers: (q) => request(`/api/users/search?q=${encodeURIComponent(q)}`),
  conversations: () => request("/api/conversations"),
  conversation: (id) => request(`/api/conversations/${id}`),
  createDirect: (userId) => request("/api/conversations/direct", { method: "POST", body: { user_id: userId } }),
  createGroup: (name, memberIds) =>
    request("/api/conversations/group", { method: "POST", body: { name, member_ids: memberIds } }),
  addMembers: (id, memberIds) =>
    request(`/api/conversations/${id}/members`, { method: "POST", body: { member_ids: memberIds } }),
  lookupUser: (username) => request(`/api/users/lookup?username=${encodeURIComponent(username)}`),
  uploadAvatar: (file) => {
    const form = new FormData();
    form.set("file", file);
    return request("/api/users/me/avatar", { method: "POST", form });
  },
  uploadGroupAvatar: (id, file) => {
    const form = new FormData();
    form.set("file", file);
    return request(`/api/conversations/${id}/avatar`, { method: "POST", form });
  },
  messages: (id, beforeId) =>
    request(`/api/conversations/${id}/messages${beforeId ? `?before_id=${beforeId}` : ""}`),
  sendMessage: (id, { content, file }) => {
    const form = new FormData();
    form.set("content", content || "");
    if (file) form.set("file", file);
    return request(`/api/conversations/${id}/messages`, { method: "POST", form });
  },
  markRead: (id) => request(`/api/conversations/${id}/read`, { method: "POST" }),
  notifications: () => request("/api/notifications"),
  markNotificationsRead: () => request("/api/notifications/read", { method: "POST" }),
};
