"""
数学智能体评测器 - Web 服务
============================
提供 REST API，支持上传文件进行评测、查看结果。
替换了原 tkinter GUI，适合在服务器上通过浏览器使用。
"""

import asyncio
import datetime
import json
import os
import sys
import threading
import uuid
from pathlib import Path

# 确保项目模块可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "测试工具"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "转化工具"))

from flask import Flask, request, jsonify, send_from_directory, render_template_string

app = Flask(__name__, static_folder=None)

# 任务存储
tasks: dict = {}
tasks_lock = threading.Lock()

# ---------- 简易 Web 首页 ----------
INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数学智能体评测器</title>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:"Microsoft YaHei",sans-serif; background:#f0f2f5; color:#333; }
  .container { max-width:800px; margin:40px auto; padding:20px; }
  h1 { text-align:center; color:#1a1a2e; margin-bottom:30px; }
  .card { background:#fff; border-radius:12px; padding:24px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,.08); }
  .card h2 { font-size:18px; margin-bottom:16px; color:#16213e; }
  label { display:block; margin-bottom:6px; font-weight:600; }
  input, select { width:100%; padding:10px 12px; border:1px solid #d9d9d9; border-radius:8px; font-size:14px; margin-bottom:14px; }
  input[type=file] { padding:8px; }
  button { padding:10px 24px; background:#4361ee; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:15px; }
  button:hover { background:#3a56d4; }
  button:disabled { background:#aaa; cursor:not-allowed; }
  .status { padding:10px 14px; border-radius:8px; margin-top:12px; font-size:14px; }
  .status.running { background:#fff3cd; color:#856404; }
  .status.done { background:#d4edda; color:#155724; }
  .status.error { background:#f8d7da; color:#721c24; }
  .task-item { display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #eee; }
  .badge { padding:3px 10px; border-radius:12px; font-size:12px; }
  .badge.running { background:#fff3cd; color:#856404; }
  .badge.done { background:#d4edda; color:#155724; }
  .badge.error { background:#f8d7da; color:#721c24; }
  a { color:#4361ee; text-decoration:none; }
  a:hover { text-decoration:underline; }
  .spinner { display:inline-block; width:14px; height:14px; border:2px solid #ccc; border-top-color:#4361ee; border-radius:50%; animation:spin 0.8s linear infinite; margin-right:6px; vertical-align:middle; }
  @keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>
<div class="container">
  <h1>🧮 数学智能体评测器</h1>

  <!-- 上传评测 -->
  <div class="card">
    <h2>📤 上传文件评测</h2>
    <form id="evalForm" enctype="multipart/form-data">
      <label>选择文件（支持 PDF / Word / JSON / CSV）</label>
      <input type="file" name="file" accept=".pdf,.docx,.json,.csv" required>
      <label>最大并发数</label>
      <input type="number" name="concurrency" value="3" min="1" max="20">
      <label>最大评测题目数（0=全部）</label>
      <input type="number" name="max_problems" value="0" min="0">
      <button type="submit">🚀 开始评测</button>
    </form>
    <div id="uploadStatus"></div>
  </div>

  <!-- 任务列表 -->
  <div class="card">
    <h2>📋 最近任务</h2>
    <div id="taskList">加载中...</div>
  </div>
</div>

<script>
async function loadTasks() {
  try {
    const r = await fetch('/api/tasks');
    const tasks = await r.json();
    const el = document.getElementById('taskList');
    if (tasks.length === 0) {
      el.innerHTML = '<p style="color:#999">暂无任务</p>';
      return;
    }
    el.innerHTML = tasks.map(t =>
      `<div class="task-item">
        <div>
          <strong>${t.id.slice(0,8)}</strong> &nbsp; ${t.filename}
          <span class="badge ${t.status}">${t.status==='running'?'运行中':t.status==='done'?'完成':'失败'}</span>
        </div>
        <div>
          ${t.status==='done' ? `<a href="/api/results/${t.id}/report.html" target="_blank">查看报告</a>` : ''}
        </div>
      </div>`
    ).join('');
  } catch(e) {
    document.getElementById('taskList').innerHTML = '<p style="color:red">加载失败</p>';
  }
}

document.getElementById('evalForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const btn = form.querySelector('button');
  btn.disabled = true;
  btn.textContent = '上传中...';

  const fd = new FormData(form);
  try {
    const r = await fetch('/api/evaluate', { method:'POST', body:fd });
    const data = await r.json();
    const st = document.getElementById('uploadStatus');
    if (r.ok) {
      st.innerHTML = `<div class="status running">✅ 任务已创建: ${data.task_id.slice(0,8)} — 评测进行中...</div>`;
      form.reset();
      pollTask(data.task_id);
    } else {
      st.innerHTML = `<div class="status error">❌ ${data.error}</div>`;
    }
  } catch(err) {
    document.getElementById('uploadStatus').innerHTML = `<div class="status error">❌ 网络错误: ${err.message}</div>`;
  }
  btn.disabled = false;
  btn.textContent = '🚀 开始评测';
  loadTasks();
});

async function pollTask(taskId) {
  const st = document.getElementById('uploadStatus');
  for (let i=0; i<120; i++) {
    await new Promise(r=>setTimeout(r,2000));
    try {
      const r = await fetch('/api/tasks');
      const tasks = await r.json();
      const t = tasks.find(x=>x.id===taskId);
      if (!t) break;
      if (t.status === 'done') {
        st.innerHTML = `<div class="status done">🎉 评测完成！<a href="/api/results/${taskId}/report.html" target="_blank">查看报告</a></div>`;
        loadTasks();
        return;
      }
      if (t.status === 'error') {
        st.innerHTML = `<div class="status error">❌ 评测失败: ${t.error || '未知错误'}</div>`;
        loadTasks();
        return;
      }
      st.innerHTML = `<div class="status running">评测中... ${t.progress || ''}</div>`;
    } catch(e) { break; }
  }
}

loadTasks();
setInterval(loadTasks, 5000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


# ---------- API ----------

@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    """上传文件并启动评测"""
    if "file" not in request.files:
        return jsonify({"error": "请上传文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400

    concurrency = int(request.form.get("concurrency", 3))
    max_problems = int(request.form.get("max_problems", 0))

    # 保存上传文件
    upload_dir = Path("测试结果/原始问题")
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix
    saved_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    saved_path = upload_dir / saved_name
    file.save(str(saved_path))

    task_id = uuid.uuid4().hex
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "filename": file.filename,
            "status": "running",
            "progress": "准备中...",
            "created_at": datetime.datetime.now().isoformat(),
        }

    thread = threading.Thread(
        target=_run_eval_task,
        args=(task_id, str(saved_path), concurrency, max_problems),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "message": "评测任务已提交"})


def _run_eval_task(task_id: str, file_path: str, concurrency: int, max_problems: int):
    """后台执行评测"""
    try:
        # 导入项目模块
        from main import auto_convert, run_evaluation

        with tasks_lock:
            tasks[task_id]["progress"] = "转换文件中..."

        # 步骤1: 转换文件
        if max_problems > 0:
            json_path = auto_convert(file_path, max_problems=max_problems)
        else:
            json_path = auto_convert(file_path)

        with tasks_lock:
            tasks[task_id]["progress"] = "评测中..."

        # 步骤2: 执行评测
        async def _run():
            return await run_evaluation(json_path, concurrency)

        html_path = asyncio.run(_run())

        # 将报告复制到任务专属目录
        result_dir = Path("测试结果/测试结果展示") / task_id
        result_dir.mkdir(parents=True, exist_ok=True)
        if html_path and os.path.exists(html_path):
            import shutil
            shutil.copy(html_path, result_dir / "report.html")

        with tasks_lock:
            tasks[task_id]["status"] = "done"
            tasks[task_id]["progress"] = "完成"
            tasks[task_id]["result_path"] = str(result_dir / "report.html")

    except Exception as e:
        with tasks_lock:
            tasks[task_id]["status"] = "error"
            tasks[task_id]["error"] = str(e)


@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    """获取最近任务列表"""
    with tasks_lock:
        task_list = sorted(
            tasks.values(),
            key=lambda t: t.get("created_at", ""),
            reverse=True,
        )[:20]
    return jsonify(task_list)


@app.route("/api/results/<task_id>/<path:filename>")
def serve_result(task_id, filename):
    """提供评测结果文件"""
    result_dir = Path("测试结果/测试结果展示") / task_id
    return send_from_directory(str(result_dir), filename)


if __name__ == "__main__":
    print("🧮 数学智能体评测器 Web 服务启动中...")
    print("   访问地址: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
