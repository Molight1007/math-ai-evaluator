"""
题库管理系统 — 基于 SQLite 的题目持久化存储与 CRUD 操作。

功能：
- 创建/删除题库
- 添加题目（手动 / 从 JSON/CSV/Word/PDF 批量导入）
- 随机选题（支持按领域筛选）
- 题库统计

数据库文件：测试工具/question_bank.db
"""

import asyncio
import json
import logging
import os
import random
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, Callable

from models import Problem
from loader import load_problems

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question_bank.db")


class QuestionBankDB:
    """题库数据库管理类"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS banks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS problems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    problem_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    domain TEXT DEFAULT '',
                    reference_answer TEXT DEFAULT '',
                    bank_name TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (bank_name) REFERENCES banks(name) ON DELETE CASCADE,
                    UNIQUE(problem_id, bank_name)
                )
            """)

    def create_bank(self, name: str) -> bool:
        """创建新题库，返回是否创建成功（已存在则返回 False）"""
        name = name.strip()
        if not name:
            raise ValueError("题库名称不能为空")
        try:
            with self._connect() as conn:
                conn.execute("INSERT INTO banks (name) VALUES (?)", (name,))
            logger.info(f"题库已创建: {name}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"题库已存在: {name}")
            return False

    def delete_bank(self, name: str) -> bool:
        """删除题库及其下所有题目，返回是否成功"""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM banks WHERE name = ?", (name,))
            deleted = cur.rowcount > 0
            if deleted:
                conn.execute("DELETE FROM problems WHERE bank_name = ?", (name,))
            logger.info(f"题库已删除: {name}" if deleted else f"题库不存在: {name}")
            return deleted

    def list_banks(self) -> list[dict]:
        """列出所有题库，返回 [{name, count, created_at}, ...]"""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT b.name, b.created_at, COUNT(p.id) AS count
                FROM banks b
                LEFT JOIN problems p ON b.name = p.bank_name
                GROUP BY b.name
                ORDER BY b.name
            """).fetchall()
        return [{"name": r["name"], "count": r["count"], "created_at": r["created_at"]} for r in rows]

    def bank_exists(self, name: str) -> bool:
        with self._connect() as conn:
            r = conn.execute("SELECT 1 FROM banks WHERE name = ?", (name,)).fetchone()
            return r is not None

    def add_problem(self, problem: Problem, bank_name: str) -> bool:
        """添加单道题目到题库，返回是否添加成功（重复则 False）"""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO problems (problem_id, question, domain, reference_answer, bank_name) VALUES (?,?,?,?,?)",
                    (problem.id, problem.question, problem.domain or "", problem.reference_answer or "", bank_name),
                )
            logger.info(f"题目 {problem.id} 已添加到题库 {bank_name}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"题目 {problem.id} 在题库 {bank_name} 中已存在，跳过")
            return False

    def import_from_file(self, filepath: str, bank_name: str) -> dict:
        """
        从 JSON/CSV/Word/PDF 文件批量导入题目到题库。
        返回 {"added": int, "skipped": int, "total": int}
        """
        if not self.bank_exists(bank_name):
            raise ValueError(f"题库不存在: {bank_name}，请先创建")

        ext = os.path.splitext(filepath)[1].lower()

        # Word / PDF → 先转化为 Problem 列表
        if ext == ".docx":
            from 转化工具.docx_to_json import convert_docx
            raw_problems = convert_docx(filepath)
        elif ext == ".pdf":
            from 转化工具.pdf_to_json import convert_pdf
            raw_problems = convert_pdf(filepath)
        elif ext in (".json", ".csv"):
            raw_problems = load_problems(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {ext}（支持 .json / .csv / .docx / .pdf）")

        # 统一转为 Problem 对象
        problems = []
        for idx, item in enumerate(raw_problems):
            if isinstance(item, Problem):
                p = item
            elif isinstance(item, dict):
                # 先检查 key 本身，再检查别名
                def _g(key, *aliases):
                    for a in (key,) + aliases:
                        v = item.get(a)
                        if v is not None and str(v).strip():
                            return str(v).strip()
                    return ""
                pid = _g("id", "ID", "problem_id")
                q = _g("question", "Question", "problem", "content")
                # 跳过没有题目的无效条目
                if not q:
                    continue
                # id 为空则用文件名+序号自动生成
                if not pid:
                    base = os.path.splitext(os.path.basename(filepath))[0]
                    pid = f"{base}_{idx + 1:04d}"
                p = Problem(
                    id=pid,
                    question=q,
                    domain=_g("domain", "Domain", "category", "type") or None,
                    reference_answer=_g("reference_answer", "ReferenceAnswer", "answer", "Answer", "solution") or None,
                )
            else:
                continue
            # 再次确保有效数据才加入
            if not p.id or not p.question:
                continue
            # 确保同一批次内 id 不重复
            existing_ids = {pp.id for pp in problems}
            if p.id in existing_ids:
                base = os.path.splitext(os.path.basename(filepath))[0]
                p.id = f"{base}_{idx + 1:04d}"
            problems.append(p)

        added = 0
        skipped = 0
        for p in problems:
            if self.add_problem(p, bank_name):
                added += 1
            else:
                skipped += 1
        logger.info(f"导入完成: 新增 {added}, 跳过 {skipped} (题库: {bank_name})")
        return {"added": added, "skipped": skipped, "total": len(problems)}

    def get_random_problems(self, bank_name: str, count: int, domain: Optional[str] = None) -> list[Problem]:
        """
        从指定题库中随机选取 count 道题目。
        domain 可选，用于按领域筛选。
        """
        query = "SELECT problem_id, question, domain, reference_answer FROM problems WHERE bank_name = ?"
        params = [bank_name]
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " ORDER BY RANDOM() LIMIT ?"
        params.append(count)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Problem(id=r["problem_id"], question=r["question"], domain=r["domain"] or None, reference_answer=r["reference_answer"] or None)
            for r in rows
        ]

    def get_all_problems(self, bank_name: str, domain: Optional[str] = None) -> list[Problem]:
        """获取题库中所有题目，可选按领域筛选"""
        query = "SELECT problem_id, question, domain, reference_answer FROM problems WHERE bank_name = ?"
        params = [bank_name]
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " ORDER BY problem_id"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Problem(id=r["problem_id"], question=r["question"], domain=r["domain"] or None, reference_answer=r["reference_answer"] or None)
            for r in rows
        ]

    def get_problem_count(self, bank_name: str, domain: Optional[str] = None) -> int:
        """获取题库题目数量"""
        query = "SELECT COUNT(*) as cnt FROM problems WHERE bank_name = ?"
        params = [bank_name]
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        with self._connect() as conn:
            return conn.execute(query, params).fetchone()["cnt"]

    def get_domains(self, bank_name: str) -> list[str]:
        """获取题库中所有不重复的领域"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT domain FROM problems WHERE bank_name = ? AND domain != '' ORDER BY domain",
                (bank_name,),
            ).fetchall()
        return [r["domain"] for r in rows]

    def remove_problem(self, problem_id: str, bank_name: str) -> bool:
        """删除题库中的单道题目"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM problems WHERE problem_id = ? AND bank_name = ?",
                (problem_id, bank_name),
            )
            return cur.rowcount > 0

    def search_problems(self, bank_name: str, keyword: str) -> list[Problem]:
        """按关键词搜索题目（匹配题干）"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT problem_id, question, domain, reference_answer FROM problems WHERE bank_name = ? AND question LIKE ? ORDER BY problem_id",
                (bank_name, f"%{keyword}%"),
            ).fetchall()
        return [
            Problem(id=r["problem_id"], question=r["question"], domain=r["domain"] or None, reference_answer=r["reference_answer"] or None)
            for r in rows
        ]

    # === 质量审核（DeepSeek AI 审核 + 自动清理 + 补全） ===

    @staticmethod
    def _build_audit_prompt(problems_batch: list[Problem], bank_domains: list[str]) -> str:
        """构建批量题目质量审核的 DeepSeek prompt"""
        domain_info = ", ".join(bank_domains[:20]) if bank_domains else "未知"
        items_text = ""
        for i, p in enumerate(problems_batch):
            items_text += (
                f"\n【第{i+1}题】\n"
                f"ID: {p.id}\n"
                f"领域: {p.domain or '未分类'}\n"
                f"题干: {p.question}\n"
                f"参考答案: {p.reference_answer or '无'}\n"
            )

        return f"""你是一个严格的数学题库质量管理专家。请对以下{len(problems_batch)}道数学题目进行质量审核。

## 题库领域分布
{domain_info}

## 待审核题目
{items_text}

## 审核要求
请逐题判断每道题目是否为**完整、有意义、可评测的数学题**。以下情况应判定为「无效」：
1. 题干为空、只有标点符号或只有1-3个无意义字符
2. 题干只有选项没有问题（如 "A. 0 B. - C. D. ∞"）
3. 题干是残缺的公式片段（如 "=____"、"lim/ x→0 x / sin2x ="、"2 3 2"）
4. 题干是乱码、无意义数字组合或格式错乱无法理解
5. 题目重复（与其他题目实质内容相同）

## 输出格式（严格 JSON，不要输出其他文字）
```json
{{
  "results": [
    {{
      "index": 1,
      "is_valid": true/false,
      "reason": "简短说明判断理由",
      "optimized_question": "如果无效则填null；如果有效但有瑕疵可以给出优化后的完整题干，否则null",
      "optimized_answer": "优化后的答案（如果有），否则null"
    }}
  ],
  "new_problems": [
    {{
      "question": "补全的新数学题题干（与题库领域相关的高质量高等数学题）",
      "domain": "题目所属领域（从已有领域中选一个合适的）",
      "answer": "参考答案"
    }}
  ]
}}
```

注意：new_problems 数组中生成 {min(3, max(1, len(problems_batch) // 5))} 道高质量新题目来补充题库。题目应覆盖微积分、极限、导数、积分等高等数学核心知识点。"""

    @staticmethod
    def _parse_audit_response(raw_content: str) -> dict:
        """解析 DeepSeek 审核响应"""
        from llm_client import extract_json_from_text

        parsed = extract_json_from_text(raw_content)
        if parsed and isinstance(parsed, dict):
            # 确保 results 和 new_problems 存在
            parsed.setdefault("results", [])
            parsed.setdefault("new_problems", [])
            return {
                "results": parsed.get("results", []),
                "new_problems": parsed.get("new_problems", []),
                "raw": raw_content,
            }
        logger.warning(f"Failed to parse audit response, raw length={len(raw_content)}")
        return {"results": [], "new_problems": [], "raw": raw_content}

    async def _audit_batch_async(
        self,
        batch: list[Problem],
        bank_domains: list[str],
    ) -> dict:
        """调用 DeepSeek 审核一批题目"""
        from config import get_config
        from llm_client import LLMClient

        cfg = get_config()
        client = LLMClient(cfg.deepseek)

        prompt = self._build_audit_prompt(batch, bank_domains)

        messages = [
            {
                "role": "system",
                "content": "你是一个数学题库质量管理专家。你只输出 JSON 格式的审核结果，不输出任何其他解释。",
            },
            {"role": "user", "content": prompt},
        ]

        response = await client.chat(
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
        )
        return self._parse_audit_response(response["content"])

    def audit_quality(
        self,
        bank_name: str,
        batch_size: int = 10,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        """
        对题库中的所有题目进行 DeepSeek 质量审核。
        
        流程：逐批调用 DeepSeek → 判断有效性 → 删除无效题目 → 补全新题目
        
        参数:
            bank_name: 要审核的题库名称
            batch_size: 每批发送给 DeepSeek 的题目数量
            progress_callback: 进度回调 (current, total, message)
            
        返回:
            {
                "total_audited": 总审核数,
                "valid_count": 有效题目数,
                "deleted_count": 删除的无效应目数,
                "added_count": 新增补全题目数,
                "errors": 错误列表,
            }
        """
        all_problems = self.get_all_problems(bank_name)
        total = len(all_problems)

        if total == 0:
            return {
                "total_audited": 0,
                "valid_count": 0,
                "deleted_count": 0,
                "added_count": 0,
                "errors": ["题库为空"],
            }

        domains = self.get_domains(bank_name)

        deleted_ids = []
        added_count = 0
        valid_count = 0
        errors = []

        # 分批处理
        for batch_start in range(0, total, batch_size):
            batch = all_problems[batch_start : batch_start + batch_size]
            current_batch_end = min(batch_start + batch_size, total)

            if progress_callback:
                progress_callback(batch_start, total, f"正在审核第 {batch_start+1}-{current_batch_end} 题...")

            try:
                result = asyncio.run(self._audit_batch_async(batch, domains))

                # 处理审核结果
                for item in result.get("results", []):
                    idx = item.get("index", 1) - 1
                    if 0 <= idx < len(batch):
                        p = batch[idx]
                        is_valid = item.get("is_valid", True)

                        if not is_valid:
                            # 删除无效题目
                            if self.remove_problem(p.id, bank_name):
                                deleted_ids.append(p.id)
                                logger.info(f"[质量审核] 删除无效题目: {p.id} — 原因: {item.get('reason', '')}")
                        else:
                            valid_count += 1
                            # 如果有优化版本且原题有明显瑕疵，考虑更新
                            opt_q = item.get("optimized_question")
                            opt_a = item.get("optimized_answer")

                # 导入补全的新题目
                new_problems = result.get("new_problems", [])
                for np_item in new_problems:
                    q = np_item.get("question", "").strip()
                    d = np_item.get("domain", "").strip()
                    a = np_item.get("answer", "").strip()
                    if q:
                        # 使用 uuid 生成唯一题目 ID
                        new_pid = f"gen_{uuid.uuid4().hex[:8]}"
                        new_p = Problem(
                            id=new_pid,
                            question=q,
                            domain=d or None,
                            reference_answer=a or None,
                        )
                        if self.add_problem(new_p, bank_name):
                            added_count += 1
                            logger.info(f"[质量审核] 补全新题目: {new_pid}")

            except Exception as e:
                errors.append(f"Batch {batch_start//batch_size + 1}: {e}")
                logger.error(f"[质量审核] 批次处理失败: {e}")

        return {
            "total_audited": total,
            "valid_count": valid_count,
            "deleted_count": len(deleted_ids),
            "added_count": added_count,
            "errors": errors,
            "deleted_ids": deleted_ids,
        }


# 数据库单例，避免重复创建连接
_db_instance: Optional[QuestionBankDB] = None


def get_db() -> QuestionBankDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = QuestionBankDB()
    return _db_instance
