"""评测路由：文件/题库评测任务 + WebSocket 实时进度。

关键安全点：
- API Key 仅通过环境变量在本次任务生命周期内注入 测试工具/main.py 的 run_evaluation，
  任务结束后立即清理，绝不写入文件/数据库/日志。
- 因配置从 os.getenv 读取，服务器上请勿放置含 Key 的 .env 文件。
- 全局 asyncio.Lock 串行化评测，避免并发用户 Key 互相覆盖。
"""
import os
import sys
import asyncio
import uuid
import logging

from fastapi import APIRouter, Depends, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException

_TEST_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "测试工具"))
if _TEST_TOOLS not in sys.path:
    sys.path.insert(0, _TEST_TOOLS)

import main as eval_main  # 测试工具/main.py

from . import config
from .auth import get_current_user

logger = logging.getLogger("eval")
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/api/eval", tags=["eval"])

# task_id -> {"queue": asyncio.Queue, "status": str}
TASKS: dict = {}
_eval_lock = asyncio.Lock()

_CONVERTIBLE = {".pdf", ".docx", ".pptx", ".md", ".xlsx"}


class _EvalParams:
    def __init__(self, file_path=None, bank_name=None, count=10, domain=None,
                 concurrency=3, enable_lean=False, intern_key="", deepseek_key=""):
        self.file_path = file_path
        self.bank_name = bank_name
        self.count = count
        self.domain = domain
        self.concurrency = concurrency
        self.enable_lean = enable_lean
        self.intern_key = intern_key
        self.deepseek_key = deepseek_key


def _make_cb(queue: asyncio.Queue):
    def cb(current, total, message=""):
        try:
            queue.put_nowait({
                "type": "progress",
                "current": current,
                "total": max(total, 1),
                "message": message,
            })
        except Exception:
            pass
    return cb


async def _run_eval_task(task_id: str, params: _EvalParams):
    task = TASKS.get(task_id)
    if not task:
        return
    queue = task["queue"]
    async with _eval_lock:
        # 注入 Key 到环境变量（仅本次任务，结束清理）
        os.environ["INTERN_S1_API_KEY"] = params.intern_key or ""
        os.environ["DEEPSEEK_API_KEY"] = params.deepseek_key or ""
        try:
            cb = _make_cb(queue)
            if params.file_path:
                html_path = await eval_main.run_evaluation(
                    params.file_path, params.concurrency,
                    progress_callback=cb, bank_name=None,
                    enable_lean=params.enable_lean,
                )
            else:
                html_path = await eval_main.run_evaluation_from_bank(
                    params.bank_name, params.count, params.concurrency,
                    domain=params.domain, progress_callback=cb,
                    enable_lean=params.enable_lean,
                )
            if not html_path or not os.path.exists(html_path):
                raise RuntimeError("评测完成但未生成报告文件")
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            queue.put_nowait({
                "type": "done",
                "report_html": html,
                "report_path": os.path.basename(html_path),
            })
        except Exception as e:
            logger.exception("评测任务失败")
            queue.put_nowait({"type": "error", "message": str(e)})
        finally:
            for k in ("INTERN_S1_API_KEY", "DEEPSEEK_API_KEY"):
                os.environ.pop(k, None)


@router.post("/start")
async def start_eval(
    intern_key: str = Form(...),
    deepseek_key: str = Form(...),
    concurrency: int = Form(3),
    enable_lean: str = Form("false"),
    bank_name: str = Form(None),
    count: int = Form(10),
    domain: str = Form(None),
    file: UploadFile = File(None),
    user: dict = Depends(get_current_user),
):
    if concurrency < 1 or concurrency > 20:
        raise HTTPException(status_code=400, detail="并发数需在 1-20 之间")

    params = _EvalParams(
        bank_name=(bank_name or "").strip() or None,
        count=count, domain=(domain or "").strip() or None,
        concurrency=concurrency,
        enable_lean=str(enable_lean).lower() == "true",
        intern_key=intern_key, deepseek_key=deepseek_key,
    )

    if file is not None and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        upload_dir = os.path.join(os.getcwd(), "测试结果", "_web_uploads")
        os.makedirs(upload_dir, exist_ok=True)
        raw_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
        with open(raw_path, "wb") as f:
            f.write(await file.read())
        if ext in _CONVERTIBLE:
            try:
                loop = asyncio.get_running_loop()
                json_path = await loop.run_in_executor(None, eval_main.auto_convert, raw_path, 0)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"文件转换失败：{e}")
            if not json_path or not os.path.exists(json_path):
                raise HTTPException(status_code=400, detail="无法将文件转换为题目 JSON")
            params.file_path = json_path
        else:
            params.file_path = raw_path
    elif not params.bank_name:
        raise HTTPException(status_code=400, detail="请提供上传文件或选择题库")

    task_id = uuid.uuid4().hex
    TASKS[task_id] = {"queue": asyncio.Queue(), "status": "running"}
    asyncio.create_task(_run_eval_task(task_id, params))
    return {"task_id": task_id}


@router.websocket("/ws/{task_id}")
async def eval_ws(ws: WebSocket, task_id: str):
    await ws.accept()
    task = TASKS.get(task_id)
    if not task:
        await ws.send_json({"type": "error", "message": "任务不存在或已过期"})
        await ws.close()
        return
    try:
        while True:
            msg = await task["queue"].get()
            await ws.send_json(msg)
            if msg.get("type") in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await ws.close()
