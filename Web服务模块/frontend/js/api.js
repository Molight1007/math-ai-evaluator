/* 全局工具：令牌管理、请求封装、WebSocket 地址、Toast。 */
const TOKEN_KEY = "me_token";
const USER_KEY = "me_user";

const Api = {
  setToken(t) { localStorage.setItem(TOKEN_KEY, t); },
  getToken() { return localStorage.getItem(TOKEN_KEY); },
  setUser(u) { localStorage.setItem(USER_KEY, JSON.stringify(u)); },
  getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; }
  },
  clear() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); },

  async request(method, path, body, isForm) {
    const headers = {};
    const token = this.getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    const opts = { method, headers };
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    const res = await fetch(path, opts);
    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) data = await res.json();
    if (!res.ok) {
      const detail = data && data.detail;
      const msg = detail
        ? (typeof detail === "string" ? detail : JSON.stringify(detail))
        : `请求失败 (${res.status})`;
      throw new Error(msg);
    }
    return data;
  },
  get(path) { return this.request("GET", path); },
  post(path, body) { return this.request("POST", path, body); },
  del(path) { return this.request("DELETE", path); },
  wsUrl(taskId) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/api/eval/ws/${taskId}`;
  },
};

const App = {
  toast(msg, isErr) {
    const t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg;
    t.className = "toast" + (isErr ? " err" : "");
    t.classList.remove("hidden");
    clearTimeout(this._tt);
    this._tt = setTimeout(() => t.classList.add("hidden"), 3400);
  },
};
