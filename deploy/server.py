# -*- coding: utf-8 -*-
"""数学智能体评测器 - Web v4 (多用户版)"""

import asyncio, datetime, hashlib, json, os, sys, threading, uuid, shutil, secrets
from pathlib import Path

_DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_DEPLOY_DIR)
if not os.path.isdir(os.path.join(_PROJECT_ROOT, "测试工具")):
    _PROJECT_ROOT = _DEPLOY_DIR
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "测试工具"))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "转化工具"))

from flask import Flask, request, jsonify, send_from_directory, render_template_string, session, redirect

app = Flask(__name__, static_folder=None)
app.secret_key = secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

_RESULT_BASE = "测试结果"
DIR_DISPLAY = os.path.join(_RESULT_BASE, "测试结果展示")
DIR_OUTPUT = os.path.join(_RESULT_BASE, "原始输出和推理过程")
DIR_PROBLEMS = os.path.join(_RESULT_BASE, "原始问题")
for d in [DIR_DISPLAY, DIR_OUTPUT, DIR_PROBLEMS]:
    os.makedirs(d, exist_ok=True)

TASKS_FILE = os.path.join(_RESULT_BASE, "任务记录.json")
BANK_DIR = "题库"
os.makedirs(BANK_DIR, exist_ok=True)

# ===== User System =====
USERS_FILE = "users.json"

def _load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Create default admin
        default = {"admin": {"password": _hash_pw("admin"), "role": "admin"}}
        _save_users(default)
        return default

def _save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

users_db = _load_users()

# ===== Task Management =====
tasks: dict = {}
tasks_lock = threading.Lock()

def _load_tasks():
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_tasks():
    os.makedirs(_RESULT_BASE, exist_ok=True)
    with tasks_lock:
        items = sorted(tasks.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)[:200]
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(items), f, ensure_ascii=False, indent=2)

tasks = _load_tasks()

_db_instance = None

def _get_db():
    global _db_instance
    if _db_instance is None:
        import sqlite3
        db_path = os.path.abspath(os.path.join(BANK_DIR, "示例题库.db"))
        from question_bank import QuestionBankDB
        _db_instance = QuestionBankDB(db_path)
        orig_connect = _db_instance._connect
        def _safe_connect():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
            except Exception:
                pass
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        _db_instance._connect = _safe_connect
    return _db_instance

def _count_problems(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return len(json.load(fh))
    except Exception:
        return 0

def _get_user():
    return session.get("user", "")

def _auth_required(f):
    def wrapper(*args, **kwargs):
        if not _get_user():
            return jsonify({"error": "请先登录"}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ===== Auth Routes =====
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if username in users_db and users_db[username]["password"] == _hash_pw(password):
        session["user"] = username
        session["role"] = users_db[username].get("role", "user")
        return jsonify({"ok": True, "username": username, "role": session["role"]})
    return jsonify({"error": "用户名或密码错误"}), 401

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/me", methods=["GET"])
def api_me():
    user = _get_user()
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "username": user, "role": session.get("role", "user")})

# ===== User Management (admin) =====
@app.route("/api/users", methods=["GET"])
def api_users():
    if session.get("role") != "admin":
        return jsonify({"error": "需要管理员权限"}), 403
    return jsonify([{"username": u, "role": d.get("role","user")} for u, d in users_db.items()])

@app.route("/api/users", methods=["POST"])
def api_create_user():
    if session.get("role") != "admin":
        return jsonify({"error": "需要管理员权限"}), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    if len(username) < 2:
        return jsonify({"error": "用户名至少2个字符"}), 400
    if username in users_db:
        return jsonify({"error": "用户已存在"}), 400
    users_db[username] = {"password": _hash_pw(password), "role": "user"}
    _save_users(users_db)
    return jsonify({"ok": True, "username": username})

@app.route("/api/users/<username>", methods=["DELETE"])
def api_delete_user(username):
    if session.get("role") != "admin":
        return jsonify({"error": "需要管理员权限"}), 403
    if username == "admin":
        return jsonify({"error": "不能删除admin"}), 400
    if username in users_db:
        del users_db[username]
        _save_users(users_db)
    return jsonify({"ok": True})

# ===== Main Page =====
@app.route("/")
def index():
    tpl_path = os.path.join(_DEPLOY_DIR, "templates", "index.html")
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            return render_template_string(f.read())
    except Exception as e:
        return render_template_string("<h1>Error</h1><pre>" + str(e) + "</pre>")

@app.route("/login.html")
def login_page():
    tpl_path = os.path.join(_DEPLOY_DIR, "templates", "login.html")
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            return render_template_string(f.read())
    except Exception:
        return render_template_string("<h1>Login</h1>")

# ===== Task API (with user filter) =====
@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    user = _get_user()
    if not user:
        return jsonify([])
    all_tasks = list(_load_tasks().values())
    # Filter by user; admin sees all
    if session.get("role") == "admin":
        user_tasks = all_tasks
    else:
        user_tasks = [t for t in all_tasks if t.get("user", "") == user]
    user_tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return jsonify(user_tasks[:50])

@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    user = _get_user()
    if not user:
        return jsonify({"error": "请先登录"}), 401
    if "file" not in request.files:
        return jsonify({"error": "请上传文件"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400
    concurrency = int(request.form.get("concurrency", 10))
    max_problems = int(request.form.get("max_problems", 0))
    multi_agent = request.form.get("multi_agent", "1") == "1"
    use_lean = request.form.get("use_lean", "0") == "1"
    upload_dir = Path(DIR_PROBLEMS)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    saved_path = upload_dir / saved_name
    file.save(str(saved_path))
    task_id = uuid.uuid4().hex
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id, "filename": file.filename,
            "status": "running", "progress": "准备中...",
            "created_at": datetime.datetime.now().isoformat(),
            "user": user,
        }
    _save_tasks()
    def _run():
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
                return await run_evaluation(json_path, concurrency, multi_agent=multi_agent, use_lean=use_lean)
            html_path = asyncio.run(_eval())
            result_dir = Path(DIR_DISPLAY) / task_id
            result_dir.mkdir(parents=True, exist_ok=True)
            if html_path and os.path.exists(html_path):
                shutil.copy(html_path, result_dir / "report.html")
            with tasks_lock:
                tasks[task_id]["status"] = "done"
                tasks[task_id]["progress"] = f"完成 ({num} 道题)"
                tasks[task_id]["finished_at"] = datetime.datetime.now().isoformat()
            _save_tasks()
        except Exception as e:
            with tasks_lock:
                tasks[task_id]["status"] = "error"
                tasks[task_id]["error"] = str(e)[:300]
                tasks[task_id]["finished_at"] = datetime.datetime.now().isoformat()
            _save_tasks()
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "message": "评测任务已提交"})

@app.route("/api/results/<task_id>/<path:filename>")
def serve_result(task_id, filename):
    result_dir = Path(DIR_DISPLAY) / task_id
    return send_from_directory(str(result_dir), filename, as_attachment="download" in request.args)

@app.route("/api/banks", methods=["GET"])
def api_banks():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    return jsonify(_get_db().list_banks())

@app.route("/api/bank/create", methods=["POST"])
def api_bank_create():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "题库名称不能为空"}), 400
    ok = _get_db().create_bank(name)
    if not ok:
        return jsonify({"error": "题库已存在"}), 400
    return jsonify({"message": f"题库创建成功"})

@app.route("/api/bank/<bank_name>/delete", methods=["POST"])
def api_bank_delete(bank_name):
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    _get_db().delete_bank(bank_name)
    return jsonify({"message": "已删除"})

@app.route("/api/bank/<bank_name>/stats", methods=["GET"])
def api_bank_stats(bank_name):
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    db = _get_db()
    problems = db.get_all_problems(bank_name)
    domains = sorted(set(p.domain for p in problems if p.domain))
    answer_count = sum(1 for p in problems if p.reference_answer and p.reference_answer.strip())
    coverage = round(answer_count / len(problems) * 100, 1) if problems else 0
    return jsonify({"problem_count": len(problems), "domains": domains, "answer_coverage": coverage})

@app.route("/api/bank/<bank_name>/problems", methods=["GET"])
def api_bank_problems(bank_name):
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    db = _get_db()
    all_p = db.get_all_problems(bank_name)
    search = request.args.get("search", "").strip()
    domain = request.args.get("domain", "").strip()
    if search:
        all_p = [p for p in all_p if search.lower() in p.question.lower()]
    if domain:
        all_p = [p for p in all_p if p.domain == domain]
    total = len(all_p)
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 50))
    page = all_p[offset:offset+limit]
    return jsonify({
        "problems": [{"problem_id": p.id, "question": p.question, "domain": p.domain or "", "reference_answer": p.reference_answer or ""} for p in page],
        "total": total
    })

@app.route("/api/bank/<bank_name>/problem/<problem_id>", methods=["GET"])
def api_bank_problem_detail(bank_name, problem_id):
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    p = _get_db().get_problem(problem_id, bank_name)
    if not p:
        return jsonify({"error": "题目不存在"}), 404
    return jsonify({"problem_id": p.id, "question": p.question, "domain": p.domain or "", "reference_answer": p.reference_answer or ""})

@app.route("/api/bank/<bank_name>/problem/<problem_id>/delete", methods=["POST"])
def api_bank_problem_delete(bank_name, problem_id):
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    _get_db().remove_problem(problem_id, bank_name)
    return jsonify({"message": "已删除"})

@app.route("/api/bank/import", methods=["POST"])
def api_bank_import():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    if "file" not in request.files:
        return jsonify({"error": "请上传文件"}), 400
    file = request.files["file"]
    bank_name = request.form.get("bank_name", "").strip()
    if not bank_name:
        return jsonify({"error": "请指定题库名称"}), 400
    saved_path = Path(DIR_PROBLEMS) / f"_import_{uuid.uuid4().hex[:8]}_{file.filename}"
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    file.save(str(saved_path))
    try:
        from loader import load_problems
        problems = load_problems(str(saved_path))
        db = _get_db()
        added = skipped = 0
        for p in problems:
            if db.add_problem(p, bank_name):
                added += 1
            else:
                skipped += 1
        return jsonify({"added": added, "skipped": skipped})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bank/manual-add", methods=["POST"])
def api_bank_manual_add():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    data = request.get_json()
    bank_name = data.get("bank_name", "").strip()
    question = data.get("question", "").strip()
    domain = data.get("domain", "").strip()
    answer = data.get("answer", "").strip()
    if not bank_name or not question:
        return jsonify({"error": "题库名称和题目不能为空"}), 400
    from models import Problem
    pid = f"manual_{uuid.uuid4().hex[:8]}"
    p = Problem(id=pid, question=question, domain=domain or None, reference_answer=answer or None)
    _get_db().add_problem(p, bank_name)
    return jsonify({"message": "添加成功", "problem_id": pid})

@app.route("/api/bank/<bank_name>/audit", methods=["POST"])
def api_bank_audit(bank_name):
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    try:
        result = _get_db().audit_quality(bank_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bank/import-answers", methods=["POST"])
def api_bank_import_answers():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    if "file" not in request.files:
        return jsonify({"error": "请上传文件"}), 400
    file = request.files["file"]
    bank_name = request.form.get("bank_name", "").strip()
    if not bank_name:
        return jsonify({"error": "请指定题库名称"}), 400
    saved_path = Path(DIR_PROBLEMS) / f"_answers_{uuid.uuid4().hex[:8]}_{file.filename}"
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    file.save(str(saved_path))
    try:
        db = _get_db()
        result = db.import_answers_from_doc(bank_name, str(saved_path))
        matched = result.get("matched", 0)
        total = result.get("total", 0)
        return jsonify({"matched": matched, "total": total, "match_rate": round(matched/total*100, 1) if total > 0 else 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bank/<bank_name>/random-eval", methods=["POST"])
def api_bank_random_eval(bank_name):
    user = _get_user()
    if not user:
        return jsonify({"error": "请先登录"}), 401
    data = request.get_json()
    count = int(data.get("count", 5))
    domain = data.get("domain") or None
    multi_agent = data.get("multi_agent", True)
    db = _get_db()
    problems = db.get_all_problems(bank_name)
    if domain:
        problems = [p for p in problems if p.domain == domain]
    if not problems:
        return jsonify({"error": "题库中没有符合条件的题目"}), 400
    import random
    selected = random.sample(problems, min(count, len(problems)))
    temp_json = os.path.join(DIR_PROBLEMS, f"_bank_eval_{uuid.uuid4().hex[:8]}.json")
    with open(temp_json, "w", encoding="utf-8") as f:
        json.dump([{"id": p.id, "question": p.question, "domain": p.domain or "", "reference_answer": p.reference_answer or ""} for p in selected], f, ensure_ascii=False, indent=2)
    task_id = uuid.uuid4().hex
    with tasks_lock:
        tasks[task_id] = {"id": task_id, "filename": f"[题库]{bank_name}-随机{len(selected)}题", "status": "running", "progress": f"准备评测 {len(selected)} 道题...", "created_at": datetime.datetime.now().isoformat(), "user": user}
    _save_tasks()
    def _run():
        try:
            from main import run_evaluation
            with tasks_lock:
                tasks[task_id]["progress"] = f"评测中 ({len(selected)} 道题)..."
            _save_tasks()
            async def _eval():
                return await run_evaluation(temp_json, min(10, len(selected)), multi_agent=multi_agent)
            html_path = asyncio.run(_eval())
            result_dir = Path(DIR_DISPLAY) / task_id
            result_dir.mkdir(parents=True, exist_ok=True)
            if html_path and os.path.exists(html_path):
                shutil.copy(html_path, result_dir / "report.html")
            with tasks_lock:
                tasks[task_id]["status"] = "done"
                tasks[task_id]["progress"] = f"完成 ({len(selected)} 道题)"
                tasks[task_id]["finished_at"] = datetime.datetime.now().isoformat()
            _save_tasks()
        except Exception as e:
            with tasks_lock:
                tasks[task_id]["status"] = "error"
                tasks[task_id]["error"] = str(e)[:300]
                tasks[task_id]["finished_at"] = datetime.datetime.now().isoformat()
            _save_tasks()
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "message": "评测任务已提交"})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    from config import get_config, has_config
    try:
        if has_config():
            cfg = get_config()
            return jsonify({"intern_key": cfg.intern_s1.api_key, "intern_url": cfg.intern_s1.base_url, "intern_model": cfg.intern_s1.model, "deepseek_key": cfg.deepseek.api_key, "deepseek_url": cfg.deepseek.base_url, "deepseek_model": cfg.deepseek.model})
    except Exception:
        pass
    return jsonify({"intern_key": os.environ.get("INTERN_S1_API_KEY", ""), "intern_url": os.environ.get("INTERN_S1_BASE_URL", ""), "intern_model": os.environ.get("INTERN_S1_MODEL", "intern-s1"), "deepseek_key": os.environ.get("DEEPSEEK_API_KEY", ""), "deepseek_url": os.environ.get("DEEPSEEK_BASE_URL", ""), "deepseek_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")})

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    if not _get_user():
        return jsonify({"error": "请先登录"}), 401
    data = request.get_json()
    from config import save_config
    try:
        save_config(intern_s1_key=data.get("intern_key", ""), deepseek_key=data.get("deepseek_key", ""), intern_s1_url=data.get("intern_url") or None, deepseek_url=data.get("deepseek_url") or None, intern_s1_model=data.get("intern_model") or None, deepseek_model=data.get("deepseek_model") or None)
        return jsonify({"message": "设置已保存"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("=" * 50)
    print("  数学智能体评测器 Web v4 (多用户)")
    print("  访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
