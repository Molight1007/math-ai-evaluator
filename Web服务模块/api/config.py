"""服务端配置（环境变量覆盖，便于部署与后续切换公开访问）。"""
import os
from typing import List

# JWT 配置
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-change-me-math-evaluator-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 天

# True = 公开注册（自动通过）；False = 内部测试（需管理员审批）
ALLOW_PUBLIC = os.getenv("ALLOW_PUBLIC", "false").lower() in ("1", "true", "yes", "on")

# 初始管理员账号（首次启动自动创建，请尽快在服务器修改密码）
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# users.db 路径（位于 api/ 目录内，独立于评测题库）
USERS_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")

# CORS：生产由 Nginx 同源托管前端；开发期可放宽
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
