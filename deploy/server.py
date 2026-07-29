"""数学智能体评测器 - Web 服务 v2
=============================
改进: 可视化进度条 - 报告下载 - 任务持久化
"""

import asyncio
import datetime
import json
import os
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "测试工具"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "转化工具"))

from flask import Flask, request, jsonify, send_from_directory, render_template_string

app = Flask(__name__, static_folder=None)

TASKS_FILE = Path("测试结果/任务记录.json")

def _load_tasks() -> dict:
    if TASKS_FILE.exists():
        try:
            return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_tasks():
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tasks_lock:
        sorted_items = sorted(tasks.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)[:50]
        data = dict(sorted_items)
    TASKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

tasks: dict = _load_tasks()
tasks_lock = threading.Lock()

INDEX_HTML = r"""{% raw %}<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数学智能体评测器</title>
<style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:"Microsoft YaHei",sans-serif; background:#f0f2f5; color:#333; }
    .container { max-width:820px; margin:40px auto; padding:20px; }
    h1 { text-align:center; color:#1a1a2e; margin-bottom:30px; }
    .card { background:#fff; border-radius:12px; padding:24px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,.08); }
    .card h2 { font-size:18px; margin-bottom:16px; color:#16213e; }
    label { display:block; margin-bottom:6px; font-weight:600; }
    input, select { width:100%; padding:10px 12px; border:1px solid #d9d9d9; border-radius:8px; font-size:14px; margin-bottom:14px; }
    input[type=file] { padding:8px; }
    .btn { display:inline-block; padding:10px 24px; background:#4361ee; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:15px; text-decoration:none; }
    .btn:hover { background:#3a56d4; }
    .btn:disabled { background:#aaa; cursor:not-allowed; }
    .btn-sm { padding:5px 14px; font-size:13px; }
    .btn-outline { background:transparent; color:#4361ee; border:1px solid #4361ee; }
    .btn-outline:hover { background:#f0f4ff; }
    .status { padding:12px 16px; border-radius:8px; margin-top:12px; font-size:14px; }
    .status.running { background:#fff3cd; color:#856404; }
    .status.done { background:#d4edda; color:#155724; }
    .status.error { background:#f8d7da; color:#721c24; }
    .progress-wrap { margin-top:10px; }
    .progress-bar { width:100%; height:10px; background:#e9ecef; border-radius:5px; overflow:hidden; }
    .progress-fill { height:100%; background:linear-gradient(90deg,#4361ee,#7209b7); border-radius:5px; transition:width 0.5s; width:30%; }
    .progress-fill.indeterminate { width:30%; animation:indeterminate 1.5s ease-in-out infinite; }
    @keyframes indeterminate { 0% { transform:translateX(-100%); } 100% { transform:translateX(400%); } }
    .progress-text { margin-top:6px; font-size:13px; color:#666; }
    .task-item { display:flex; justify-content:space-between; align-items:center; padding:12px 0; border-bottom:1px solid #eee; flex-wrap:wrap; gap:8px; }
    .task-left { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
    .task-right { display:flex; gap:8px; flex-wrap:wrap; }
    .badge { padding:3px 10px; border-radius:12px; font-size:12px; white-space:nowrap; }
    .badge.running { background:#fff3cd; color:#856404; }
    .badge.done { background:#d4edda; color:#155724; }
    .badge.error { background:#f8d7da; color:#721c24; }
    .spinner { display:inline-block; width:14px; height:14px; border:2px solid #ccc; border-top-color:#4361ee; border-radius:50%; animation:spin 0.8s linear infinite; margin-right:6px; vertical-align:middle; }
    @keyframes spin { to { transform:rotate(360deg); } }
    .empty { color:#999; text-align:center; padding:20px; }
    .muted { color:#999; font-size:13px; }
</style>
</head>
<body>
<div class="container">
  <h1>数学智能体评测器</h1>

  <div class="card">
    <h2>上传文件评测</h2>
    <form id="evalForm" enctype="multipart/form-data">
      <label>选择文件（PDF / Word / JSON / CSV）</label>
      <input type="file" name="file" accept=".pdf,.docx,.json,.csv" required>
      <div style="display:flex;gap:12px;flex-wrap:wrap;">
        <div style="flex:1;min-width:150px;">
          <label>最大并发数</label>
          <input type="number" name="concurrency" value="3" min="1" max="20">
        </div>
        <div style="flex:1;min-width:150px;">
          <label>最大评测题数（0=全部）</label>
          <input type="number" name="max_problems" value="0" min="0">
        </div>
      </div>
      <button type="submit" class="btn">开始评测</button>
    </form>
    <div id="uploadStatus"></div>
  </div>

  <div class="card">
    <h2>最近任务</h2>
    <div id="taskList">加载中...</div>
  </div>
</div>

<script>
async function loadTasks() {
  try {
    const r = await fetch('/api/tasks');
    const tasks = await r.json();
    const el = document.getElementById('taskList');
    if (!tasks.length) { el.innerHTML = '<p class="empty">暂无任务</p>'; return; }
    el.innerHTML = tasks.map(t => {
      const tm = t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : '';
      const fb = t.status === 'done'
        ? '<a href="/api/results/' + t.id + '/report.html" target="_blank" class="btn btn-sm">查看</a> ' +
          '<a href="/api/results/' + t.id + '/report.html" download class="btn btn-sm btn-outline">下载</a>'
        : '';
      const statusText = t.status === 'running' ? '<span class="spinner"></span>运行中'
        : t.status === 'done' ? '完成' : '失败';
      return '<div class="task-item"><div class="task-left"><strong style="font-family:monospace;">'
        + t.id.slice(0,8) + '</strong> <span>' + (t.filename || '')
        + '</span> <span class="badge ' + t.status + '">' + statusText
        + '</span></div><div class="task-right">' + fb
        + (tm ? '<span class="muted">' + tm + '</span>' : '')
        + '</div></div>';
    }).join('');
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
    if (data.task_id) {
      st.innerHTML = '<div class="progress-wrap"><div class="progress-bar"><div class="progress-fill indeterminate"></div></div><div class="progress-text">已提交，等待开始...</div></div>';
      form.reset();
      pollTask(data.task_id);
    } else {
      st.innerHTML = '<div class="status error">' + data.error + '</div>';
    }
  } catch(err) {
    document.getElementById('uploadStatus').innerHTML = '<div class="status error">网络错误: ' + err.message + '</div>';
  }
  btn.disabled = false;
  btn.textContent = '开始评测';
  loadTasks();
});

async function pollTask(taskId) {
  const st = document.getElementById('uploadStatus');
  for (let i=0; i<600; i++) {
    await new Promise(r=>setTimeout(r,2000));
    try {
      const r = await fetch('/api/tasks');
      const tasks = await r.json();
      const t = tasks.find(x=>x.id===taskId);
      if (!t) break;
      if (t.status === 'done') {
        st.innerHTML = '<div class="status done">评测完成！<a href="/api/results/' + taskId + '/report.html" target="_blank" class="btn btn-sm" style="margin-left:10px">查看报告</a><a href="/api/results/' + taskId + '/report.html" download class="btn btn-sm btn-outline" style="margin-left:6px">下载</a></div>';
        loadTasks(); return;
      }
      if (t.status === 'error') {
        st.innerHTML = '<div class="status error">评测失败: ' + (t.error || '未知错误') + '</div>';
        loadTasks(); return;
      }
      st.innerHTML = '<div class="progress-wrap"><div class="progress-bar"><div class="progress-fill indeterminate"></div></div><div class="progress-text">' + (t.progress || '评测中...') + '</div></div>';
    } catch(e) { break; }
  }
  st.innerHTML = '<div class="status error">评测超时，请检查 API 或网络</div>';
}

loadTasks();
setInterval(loadTasks, 5000);
</script>
</body>
</html>{% endraw %}"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    with tasks_lock:
        task_list = sorted(tasks.values(), key=lambda t: t.get("created_at", ""), reverse=True)[:20]
    return jsonify(task_list)

@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    if "file" not in request.files:
        return jsonify({"error": "请上传文件"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400

    concurrency = int(request.form.get("concurrency", 3))
    max_problems = int(request.form.get("max_problems", 0))

    upload_dir = Path("测试结果/原始问题")
    upload_dir.mkdir(parents=True, exist_ok=True)
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
    _save_tasks()

    def _run():
        import asyncio as _aio
        try:
            from main import auto_convert, run_evaluation
            with tasks_lock:
                tasks[task_id]["progress"] = "转换文件中..."
            _save_tasks()

            if max_problems > 0:
                json_path = auto_convert(file_path=str(saved_path), max_problems=max_problems)
            else:
                json_path = auto_convert(file_path=str(saved_path))

            num = _count_problems(json_path)
            with tasks_lock:
                tasks[task_id]["progress"] = f"评测中 ({num} 道题)..."
            _save_tasks()

            async def _eval():
                return await run_evaluation(json_path, concurrency)

            html_path = _aio.run(_eval())

            result_dir = Path("测试结果/测试结果展示") / task_id
            result_dir.mkdir(parents=True, exist_ok=True)
            if html_path and os.path.exists(html_path):
                import shutil
                shutil.copy(html_path, result_dir / "report.html")

            with tasks_lock:
                tasks[task_id]["status"] = "done"
                tasks[task_id]["progress"] = f"完成 ({num} 道题)"
                tasks[task_id]["finished_at"] = datetime.datetime.now().isoformat()
            _save_tasks()
        except Exception as e:
            err_msg = str(e)[:200]
            with tasks_lock:
                tasks[task_id]["status"] = "error"
                tasks[task_id]["error"] = err_msg
                tasks[task_id]["finished_at"] = datetime.datetime.now().isoformat()
            _save_tasks()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "message": "评测任务已提交"})

def _count_problems(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return len(json.load(fh))
    except Exception:
        return 0

@app.route("/api/results/<task_id>/<path:filename>")
def serve_result(task_id, filename):
    result_dir = Path("测试结果/测试结果展示") / task_id
    return send_from_directory(str(result_dir), filename, as_attachment="download" in request.args)

if __name__ == "__main__":
    print("数学智能体评测器 Web 服务 v2 启动中...")
    print("   访问地址: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
