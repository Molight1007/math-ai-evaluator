/* 题库管理页：列表、创建、删除，以及「用此题库评测」跳转到评测页。 */
const Bank = {
  init() {
    document.getElementById("create-bank-btn").onclick = () => this.create();
  },

  async load() {
    try {
      const banks = await Api.get("/api/banks");
      const grid = document.getElementById("bank-grid");
      const empty = document.getElementById("bank-empty");
      grid.innerHTML = "";
      if (!banks.length) empty.classList.remove("hidden");
      else empty.classList.add("hidden");

      const sel = document.getElementById("bank-select");
      sel.innerHTML = "";

      banks.forEach((b) => {
        const card = document.createElement("div");
        card.className = "bank-card";
        const domains = (b.domains || [])
          .map((d) => `<span class="domain-tag">${d}</span>`)
          .join("");
        card.innerHTML =
          `<h4>${b.name}</h4>` +
          `<div class="meta">${b.count} 道题</div>` +
          `<div class="domains">${domains}</div>` +
          `<div class="bank-actions">` +
          `<button class="btn-primary" data-eval="${b.name}">用此题库评测</button>` +
          `<button class="btn-ghost" data-del="${b.name}">删除</button></div>`;
        grid.appendChild(card);

        const opt = document.createElement("option");
        opt.value = b.name;
        opt.textContent = `${b.name}（${b.count}）`;
        sel.appendChild(opt);
      });

      grid.querySelectorAll("[data-eval]").forEach((btn) =>
        (btn.onclick = () => this.pickForEval(btn.dataset.eval))
      );
      grid.querySelectorAll("[data-del]").forEach((btn) =>
        (btn.onclick = () => this.remove(btn.dataset.del))
      );
    } catch (err) {
      App.toast(err.message, true);
    }
  },

  async create() {
    const name = document.getElementById("new-bank-name").value.trim();
    if (!name) { App.toast("请输入题库名称", true); return; }
    try {
      const r = await Api.post("/api/banks", { name });
      const msg = document.getElementById("bank-msg");
      msg.textContent = r.message;
      msg.className = "form-msg ok";
      document.getElementById("new-bank-name").value = "";
      this.load();
    } catch (err) {
      const msg = document.getElementById("bank-msg");
      msg.textContent = err.message;
      msg.className = "form-msg err";
    }
  },

  async remove(name) {
    if (!confirm(`确认删除题库「${name}」？此操作不可恢复。`)) return;
    try {
      await Api.del("/api/banks/" + encodeURIComponent(name));
      this.load();
    } catch (err) {
      App.toast(err.message, true);
    }
  },

  pickForEval(name) {
    Auth.switchPage("eval");
    document.querySelector('.src-tab[data-src="bank"]').click();
    document.getElementById("bank-select").value = name;
    App.toast(`已选择题库「${name}」，请确认密钥后开始评测`);
  },
};
