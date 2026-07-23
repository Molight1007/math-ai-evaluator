"""账户管理：SQLite users.db（用户名、密码哈希、审批状态、管理员标记）。"""
import os
import sqlite3
import datetime
from typing import Optional

import bcrypt
from . import config


def _hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > 72:  # bcrypt 限制 72 字节
        pw = pw[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def _conn():
    conn = sqlite3.connect(config.USERS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """创建用户表并确保管理员账号存在。"""
    conn = _conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    cur = conn.execute("SELECT 1 FROM users WHERE username=?", (config.ADMIN_USERNAME,))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (username, password_hash, status, is_admin, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                config.ADMIN_USERNAME,
                _hash_password(config.ADMIN_PASSWORD),
                "approved",
                1,
                datetime.datetime.now().isoformat(),
            ),
        )
        conn.commit()
    conn.close()


def register(username: str, password: str) -> tuple[bool, str]:
    username = (username or "").strip()
    if not username or not password:
        return False, "用户名和密码不能为空"
    if len(username) < 3 or len(username) > 32:
        return False, "用户名长度需为 3-32 个字符"
    conn = _conn()
    try:
        cur = conn.execute("SELECT 1 FROM users WHERE username=?", (username,))
        if cur.fetchone():
            return False, "用户名已存在"
        status = "approved" if config.ALLOW_PUBLIC else "pending"
        conn.execute(
            "INSERT INTO users (username, password_hash, status, is_admin, created_at) "
            "VALUES (?,?,?,?,?)",
            (username, _hash_password(password), status, 0, datetime.datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    if config.ALLOW_PUBLIC:
        return True, "注册成功，已自动通过"
    return True, "注册成功，请等待管理员审批"


def verify_password(username: str, password: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute("SELECT password_hash FROM users WHERE username=?", (username,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:72],
            row["password_hash"].encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def get_user(username: str) -> Optional[dict]:
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT username, status, is_admin, created_at FROM users WHERE username=?",
            (username,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def set_status(username: str, status: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE users SET status=? WHERE username=?", (status, username)
        )
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    return ok


def list_users() -> list:
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT username, status, is_admin, created_at FROM users ORDER BY created_at"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def is_admin(username: str) -> bool:
    u = get_user(username)
    return bool(u and u["is_admin"])
