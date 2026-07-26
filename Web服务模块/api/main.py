"""FastAPI 应用入口：聚合路由、CORS、初始化用户库、托管前端静态文件。"""
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, users
from .auth import router as auth_router
from .evaluate import router as eval_router
from .bank import router as bank_router

logging.basicConfig(level=logging.INFO)

# 初始化用户库（首次启动创建表与管理员账号）
users.init_db()

app = FastAPI(title="优化版书生 AI - 数学智能体评测器", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(eval_router)
app.include_router(bank_router)

# 前端静态文件：开发期由本应用直接托管；生产环境由 Nginx 托管，此挂载作为兜底。
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
