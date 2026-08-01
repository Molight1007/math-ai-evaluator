import os

server = """\"""数学智能体评测器 - Web 服务 v3
=============================
三标签页: 文件评测 / 题库评测 / 题库浏览器
\"""

import asyncio, datetime, json, os, sys, threading, uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "\u6d4b\u8bd5\u5de5\u5177"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "\u8f6c\u5316\u5de5\u5177"))

from flask import Flask, request, jsonify, send_from_directory, render_template_string

app = Flask(__name__, static_folder=None)

_RESULT_BASE = "\u6d4b\u8bd5\u7ed3\u679c"
DIR_DISPLAY = os.path.join(_RESULT_BASE, "\u6d4b\u8bd5\u7ed3\u679c\u5c55\u793a")
DIR_OUTPUT = os.path.join(_RESULT_BASE, "\u539f\u59cb\u8f93\u51fa\u548c\u63a8\u7406\u8fc7\u7a0b")
DIR_PROBLEMS = os.path.join(_RESULT_BASE, "\u539f\u59cb\u95ee\u9898")
for d in [DIR_DISPLAY, DIR_OUTPUT, DIR_PROBLEMS]:
    os.makedirs(d, exist_ok=True)

TASKS_FILE = os.path.join(_RESULT_BASE, "\u4efb\u52a1\u8bb0\u5f55.json")

def _load_tasks():
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

tasks = _load_tasks()
tasks_lock = threading.Lock()

def _save_tasks():
    os.makedirs(_RESULT_BASE, exist_ok=True)
    with tasks_lock:
        items = sorted(tasks.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)[:50]
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(items), f, ensure_ascii=False, indent=2)

_db_instance = None
def _get_db():
    global _db_instance
    if _db_instance is None:
        from question_bank import QuestionBankDB
        _db_instance = QuestionBankDB("\u9898\u5e93/\u6211\u7684\u9898\u5e93.db")
    return _db_instance

print("server.py base written, need HTML template")
"""

with open(r"E:\math-ai-evaluator\deploy\server_base.py", "w", encoding="utf-8") as f:
    f.write(server)
print("base written")