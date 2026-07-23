/* 快速评测页：来源切换、文件上传、开始评测、WebSocket 进度、报告预览与下载。 */
const Eval = {
  state: { file: null, fileName: null },

  init() {
    document.querySelectorAll(".src-tab").forEach((t) => {
      t.onclick = () => {
        document.querySelectorAll(".src-tab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        const src = t.dataset.src;
        document.getElementById("src-file").classList.toggle("hidden", src !== "file");
        document.getElementById("src-bank").classList.toggle("hidden", src !== "bank");
      };
    });

    const dz = document.getElementById("dropzone");
    const fi = document.getElementById("file-input");
    dz.onclick = () => fi.click();
    fi.onchange = () => { if (fi.files[0]) this.setFile(fi.files[0]); };
    ["dragover", "dragenter"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); })
    );
    ["dragleave", "drop"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); })
    );
    dz.addEventListener("drop", (e) => {
      const f = e.dataTransfer.files[0];
      if (f) this.setFile(f);
    });

    const conc = document.getElementById("concurrency");
    conc.oninput = () => {
      document.getElementById("conc-val").textContent = conc.value;
      this.updateKeyMirror();
    };
    document.getElementById("intern-key").oninput = () => this.updateKeyMirror();
    document.getElementById("deepseek-key").oninput = () => this.updateKeyMirror();

    document.getElementById("start-btn").onclick = () => this.start();
    document.getElementById("download-btn").onclick = () => this.download();
    this.updateKeyMirror();
  },

  setFile(f) {
    this.state.file = f;
    this.state.fileName = f.name;
    const chip = document.getElementById("file-chip");
    chip.textContent = "📄 " + f.name;
    chip.classList.remove("hidden");
  },

  updateKeyMirror() {
    const ik = document.getElementById("intern-key").value.trim();
    const dk = document.getElementById("deepseek-key").value.trim();
    const conc = document.getElementById("concurrency").value;
    document.getElementById("key-mirror").innerHTML =
      `本次将使用：Intern-S1（${ik ? "<b>已填写</b>" : "<b style='color:var(--red)'>未填写</b>"}） · ` +
      `DeepSeek（${dk ? "<b>已填写</b>" : "<b style='color:var(--red)'>未填写</b>"}） · 并发 <b>${conc}</b>`;
  },

  validateKeys() {
    const ik = document.getElementById("intern-key").value.trim();
    const dk = document.getElementById("deepseek-key").value.trim();
    if (!ik || !dk) {
      App.toast("请先在左侧填写两个 API Key", true);
      return false;
    }
    return true;
  },

  async start() {
    if (!this.validateKeys()) return;
    this.updateKeyMirror();

    const ik = document.getElementById("intern-key").value.trim();
    const dk = document.getElementById("deepseek-key").value.trim();
    const conc = parseInt(document.getElementById("concurrency").value, 10);
    const enableLean = document.getElementById("enable-lean").checked;
    const src = document.querySelector(".src-tab.active").dataset.src;

    const fd = new FormData();
    fd.append("intern_key", ik);
    fd.append("deepseek_key", dk);
    fd.append("concurrency", conc);
    fd.append("enable_lean", enableLean ? "true" : "false");
    if (src === "file") {
      if (!this.state.file) { App.toast("请先上传题目文件", true); return; }
      fd.append("file", this.state.file);
    } else {
      const bank = document.getElementById("bank-select").value;
      if (!bank) { App.toast("请选择题库", true); return; }
      fd.append("bank_name", bank);
      fd.append("count", document.getElementById("bank-count").value || "10");
      const dom = document.getElementById("bank-domain").value.trim();
      if (dom) fd.append("domain", dom);
    }

    const btn = document.getElementById("start-btn");
    btn.disabled = true;
    btn.textContent = "评测中…";
    document.getElementById("eval-idle").classList.add("hidden");
    document.getElementById("progress-wrap").classList.remove("hidden");
    document.getElementById("report-card").classList.add("hidden");
    this.setProgress(0, "提交任务…", 0);

    try {
      const r = await Api.post("/api/eval/start", fd, true);
      this.connectWS(r.task_id);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "🚀 开始评测";
      document.getElementById("progress-wrap").classList.add("hidden");
      document.getElementById("eval-idle").classList.remove("hidden");
      App.toast(err.message, true);
    }
  },

  connectWS(taskId) {
    const ws = new WebSocket(Api.wsUrl(taskId));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "progress") {
        const pct = Math.round((m.current / m.total) * 100);
        this.setProgress(pct, m.message || `进度 ${m.current}/${m.total}`, pct);
      } else if (m.type === "done") {
        this.showReport(m.report_html);
        this.finish();
      } else if (m.type === "error") {
        App.toast("评测失败：" + m.message, true);
        this.finish();
      }
    };
    ws.onerror = () => { App.toast("进度连接异常", true); this.finish(); };
  },

  setProgress(pct, text) {
    document.getElementById("progress-fill").style.width = pct + "%";
    document.getElementById("progress-text").textContent = text;
    document.getElementById("progress-pct").textContent = pct + "%";
  },

  showReport(html) {
    const blob = new Blob([html], { type: "text/html" });
    this._reportUrl = URL.createObjectURL(blob);
    document.getElementById("report-frame").src = this._reportUrl;
    document.getElementById("report-card").classList.remove("hidden");
    document.getElementById("report-card").scrollIntoView({ behavior: "smooth" });
  },

  download() {
    if (!this._reportUrl) return;
    const a = document.createElement("a");
    a.href = this._reportUrl;
    a.download = "评测报告.html";
    a.click();
  },

  finish() {
    const btn = document.getElementById("start-btn");
    btn.disabled = false;
    btn.textContent = "🚀 开始评测";
  },
};
