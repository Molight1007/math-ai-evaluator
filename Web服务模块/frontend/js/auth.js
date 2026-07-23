/* 鉴权与导航：登录/注册、门禁、侧边栏用户、页面切换、审批后台。 */
const Auth = {
  init() {
    // 登录/注册切换
    document.querySelectorAll(".tab").forEach((t) => {
      t.onclick = () => {
        document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        const tab = t.dataset.tab;
        document.getElementById("login-form").classList.toggle("hidden", tab !== "login");
        document.getElementById("register-form").classList.toggle("hidden", tab !== "register");
      };
    });

    document.getElementById("login-form").onsubmit = (e) => this.onLogin(e);
    document.getElementById("register-form").onsubmit = (e) => this.onRegister(e);
    document.getElementById("logout-btn").onclick = () => this.logout();

    // 密钥面板折叠
    document.getElementById("key-head").onclick = () =>
      document.querySelector(".key-settings").classList.toggle("collapsed");

    // 显示/隐藏密码
    document.querySelectorAll(".pw-toggle").forEach((b) => {
      b.onclick = () => {
        const inp = document.getElementById(b.dataset.target);
        const show = inp.type === "password";
        inp.type = show ? "text" : "password";
        b.textContent = show ? "隐藏" : "显示";
      };
    });

    // 若已登录则直接进入
    const user = Api.getUser();
    if (user && Api.getToken()) this.enterApp(user);

    // 导航
    document.querySelectorAll(".nav-item").forEach((n) => {
      n.onclick = () => this.switchPage(n.dataset.page);
    });
  },

  msg(id, text, ok) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.className = "form-msg " + (ok ? "ok" : "err");
  },

  async onLogin(e) {
    e.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    this.msg("login-msg", "", true);
    try {
      const r = await Api.post("/api/auth/login", { username, password });
      Api.setToken(r.access_token);
      Api.setUser({ username: r.username, is_admin: r.is_admin, status: r.status });
      this.enterApp(r);
    } catch (err) {
      this.msg("login-msg", err.message, false);
    }
  },

  async onRegister(e) {
    e.preventDefault();
    const username = document.getElementById("register-username").value.trim();
    const password = document.getElementById("register-password").value;
    try {
      const r = await Api.post("/api/auth/register", { username, password });
      const tip = r.status === "pending" ? "（请等待管理员审批）" : "";
      this.msg("register-msg", r.message + tip, true);
      document.getElementById("register-form").reset();
    } catch (err) {
      this.msg("register-msg", err.message, false);
    }
  },

  enterApp(user) {
    document.getElementById("login-view").classList.add("hidden");
    document.getElementById("app-view").classList.remove("hidden");
    document.getElementById("user-name").textContent = user.username;
    document.getElementById("user-avatar").textContent = (user.username[0] || "U").toUpperCase();
    document.getElementById("user-role").textContent = user.is_admin ? "管理员" : "成员";
    document.querySelector(".admin-only").classList.toggle("hidden", !user.is_admin);
    document.getElementById("mode-badge").textContent = user.is_admin ? "管理员" : "内部测试模式";

    Eval.init();
    Bank.init();
    Bank.load();
    if (user.is_admin) Approve.init();
    this.switchPage("eval");
  },

  logout() {
    Api.clear();
    location.reload();
  },

  switchPage(page) {
    document.querySelectorAll(".nav-item").forEach((n) =>
      n.classList.toggle("active", n.dataset.page === page)
    );
    ["eval", "bank", "approve"].forEach((p) =>
      document.getElementById("page-" + p).classList.toggle("hidden", p !== page)
    );
    const titles = {
      eval: ["快速评测", "上传题目文件或选择题库，一键触发数学智能体评测。"],
      bank: ["题库管理", "查看、创建题库，并基于题库随机选题评测。"],
      approve: ["审批后台", "审批新注册的用户申请。"],
    };
    document.getElementById("page-title").textContent = titles[page][0];
    document.getElementById("page-desc").textContent = titles[page][1];
    if (page === "bank") Bank.load();
    if (page === "approve") Approve.load();
  },
};

/* 审批后台 */
const Approve = {
  init() {},
  async load() {
    try {
      const pending = await Api.get("/api/auth/pending");
      const list = document.getElementById("pending-list");
      const empty = document.getElementById("pending-empty");
      list.innerHTML = "";
      if (!pending.length) empty.classList.remove("hidden");
      else empty.classList.add("hidden");
      pending.forEach((u) => {
        const item = document.createElement("div");
        item.className = "pending-item";
        item.innerHTML =
          `<div><div class="pname">${u.username}</div>` +
          `<div class="ptime">申请于 ${u.created_at || ""}</div></div>` +
          `<div class="pending-actions">` +
          `<button class="btn-primary" data-approve="${u.username}">通过</button>` +
          `<button class="btn-ghost" data-reject="${u.username}">拒绝</button></div>`;
        list.appendChild(item);
      });
      list.querySelectorAll("[data-approve]").forEach((b) =>
        (b.onclick = () => this.act(b.dataset.approve, "approve"))
      );
      list.querySelectorAll("[data-reject]").forEach((b) =>
        (b.onclick = () => this.act(b.dataset.reject, "reject"))
      );
    } catch (err) {
      App.toast(err.message, true);
    }
  },
  async act(username, action) {
    try {
      await Api.post("/api/auth/" + action, { username });
      this.load();
      App.toast(`已${action === "approve" ? "通过" : "拒绝"} ${username}`);
    } catch (err) {
      App.toast(err.message, true);
    }
  },
};

document.addEventListener("DOMContentLoaded", () => Auth.init());
