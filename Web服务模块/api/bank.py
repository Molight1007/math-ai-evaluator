"""题库路由：列表、创建、删除、领域查询（复用 测试工具/question_bank.py）。"""
import os
import sys
from fastapi import APIRouter, Depends, HTTPException

_TEST_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "测试工具"))
if _TEST_TOOLS not in sys.path:
    sys.path.insert(0, _TEST_TOOLS)

from question_bank import get_db

from .auth import get_current_user
from .schemas import BankCreateRequest

router = APIRouter(prefix="/api/banks", tags=["banks"])


def _db():
    return get_db()


@router.get("")
def list_banks(user: dict = Depends(get_current_user)):
    db = _db()
    try:
        banks = db.list_banks()  # list[dict]: name, count, created_at
    except Exception:
        banks = []
    for b in banks:
        try:
            b["domains"] = db.get_domains(b["name"]) or []
        except Exception:
            b["domains"] = []
    return banks


@router.post("")
def create_bank(req: BankCreateRequest, user: dict = Depends(get_current_user)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="题库名称不能为空")
    db = _db()
    if db.bank_exists(name):
        raise HTTPException(status_code=400, detail="题库已存在")
    db.create_bank(name)
    return {"message": f"题库 {name} 创建成功"}


@router.delete("/{bank_name}")
def delete_bank(bank_name: str, user: dict = Depends(get_current_user)):
    db = _db()
    if not db.bank_exists(bank_name):
        raise HTTPException(status_code=404, detail="题库不存在")
    db.delete_bank(bank_name)
    return {"message": f"题库 {bank_name} 已删除"}


@router.get("/{bank_name}/domains")
def bank_domains(bank_name: str, user: dict = Depends(get_current_user)):
    db = _db()
    if not db.bank_exists(bank_name):
        raise HTTPException(status_code=404, detail="题库不存在")
    try:
        return db.get_domains(bank_name) or []
    except Exception:
        return []
