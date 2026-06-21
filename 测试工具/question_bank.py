"""
题库管理系统 — 基于 SQLite 的题目持久化存储与 CRUD 操作。

功能：
- 创建/删除题库
- 添加题目（手动 / 从 JSON/CSV/Word/PDF 批量导入）
- 随机选题（支持按领域筛选）
- 题库统计

数据库文件：测试工具/question_bank.db
"""

import json
import logging
import os
import random
import sqlite3
import uuid
import asyncio  # 用于 audit_quality 中调用异步匹配方法
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
            # 答案映射表：存储「答案文档条目 → 题库题目」的匹配关系
            conn.execute("""
                CREATE TABLE IF NOT EXISTS answer_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bank_name TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    question_text TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    match_reason TEXT DEFAULT '',
                    source_file TEXT DEFAULT '',
                    source_page INTEGER DEFAULT 0,
                    answer_index INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (bank_name) REFERENCES banks(name) ON DELETE CASCADE
                )
            """)
            # 为 answer_mapping 创建索引，加速按题库+题目查询
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_answer_mapping_lookup
                ON answer_mapping(bank_name, problem_id)
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

    # 支持导入的文件扩展名集合
    SUPPORTED_IMPORT_EXTS: set = {
        ".json", ".csv", ".docx", ".pdf",
        ".pptx", ".ppt", ".md", ".xlsx",
    }

    def import_from_file(self, filepath: str, bank_name: str) -> dict:
        """
        从多种格式文件批量导入题目到题库。

        支持格式: .json / .csv / .docx / .pdf / .pptx / .ppt / .md / .xlsx

        参数:
            filepath: 题目文件路径
            bank_name: 目标题库名称

        返回:
            {"added": int, "skipped": int, "total": int}

        异常:
            ValueError: 题库不存在或文件格式不支持
        """
        if not self.bank_exists(bank_name):
            raise ValueError(f"题库不存在: {bank_name}，请先创建")

        ext = os.path.splitext(filepath)[1].lower()

        # 需要转化的格式 → 调用转化工具转为 Problem 列表
        if ext == ".docx":
            from 转化工具.docx_to_json import convert_docx
            raw_problems = convert_docx(filepath)
        elif ext == ".pdf":
            from 转化工具.pdf_to_json import convert_pdf
            raw_problems = convert_pdf(filepath)
        elif ext in (".pptx", ".ppt"):
            from 转化工具.ppt_to_json import convert_ppt
            raw_problems = convert_ppt(filepath)
        elif ext == ".md":
            from 转化工具.md_to_json import convert_md
            raw_problems = convert_md(filepath)
        elif ext == ".xlsx":
            from 转化工具.xlsx_to_json import convert_xlsx
            raw_problems = convert_xlsx(filepath)
        elif ext in (".json", ".csv"):
            raw_problems = load_problems(filepath)
        else:
            supported = ", ".join(sorted(self.SUPPORTED_IMPORT_EXTS))
            raise ValueError(f"不支持的文件格式: {ext}（支持 {supported}）")

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

        优化：用 Python random.sample + 两步查询替代 ORDER BY RANDOM()，
        避免 SQLite 全表扫描+排序的 O(n log n) 开销。
        """
        # 第一步：只查询符合条件的 ID 列表（轻量查询）
        id_query = "SELECT problem_id FROM problems WHERE bank_name = ?"
        params: list = [bank_name]
        if domain:
            id_query += " AND domain = ?"
            params.append(domain)

        with self._connect() as conn:
            rows = conn.execute(id_query, params).fetchall()
        all_ids = [r["problem_id"] for r in rows]

        if not all_ids:
            return []

        # Python 层随机采样（O(k) 操作，远快于 SQL 层 RANDOM 排序）
        sampled_ids = random.sample(all_ids, min(count, len(all_ids)))

        # 第二步：精确查询选中的题目内容
        placeholders = ",".join("?" for _ in sampled_ids)
        query = f"SELECT problem_id, question, domain, reference_answer FROM problems WHERE problem_id IN ({placeholders})"

        with self._connect() as conn:
            rows = conn.execute(query, sampled_ids).fetchall()

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

    def _update_problem_text(self, problem_id: str, bank_name: str,
                              question: str = None, reference_answer: str = None):
        """更新题目的题干或参考答案（保留其他字段不变）"""
        sets = []
        params = []
        if question is not None:
            sets.append("question = ?")
            params.append(question)
        if reference_answer is not None:
            sets.append("reference_answer = ?")
            params.append(reference_answer)
        if not sets:
            return
        params.extend([problem_id, bank_name])
        sql = f"UPDATE problems SET {', '.join(sets)} WHERE problem_id = ? AND bank_name = ?"
        with self._connect() as conn:
            conn.execute(sql, params)

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

    # === 答案映射管理 ===

    def import_answer_mappings(
        self,
        bank_name: str,
        matches: list[dict],
        source_file: str = "",
    ) -> dict:
        """
        批量导入答案映射到数据库。

        参数:
            bank_name: 目标题库名称
            matches: 匹配结果列表，每项包含:
                - answer_index: 答案条目序号
                - matched_problem_id: 匹配到的题目 ID（或 null）
                - confidence: 匹配置信度
                - match_reason: 匹配理由
                - matched_answer: 提取的答案
                - question_text: 答案文档中的题干片段（可选）
                - source_page: 来源页码（可选）
            source_file: 答案来源文件名

        返回: {"added": int, "skipped": int}
        """
        added = 0
        skipped = 0

        with self._connect() as conn:
            for m in matches:
                problem_id = m.get("matched_problem_id")
                if not problem_id:
                    skipped += 1
                    continue

                answer_text = m.get("matched_answer", "").strip()
                if not answer_text:
                    skipped += 1
                    continue

                confidence = float(m.get("confidence", 0))
                if confidence < 0.5:
                    skipped += 1
                    continue

                try:
                    conn.execute(
                        """INSERT INTO answer_mapping
                           (bank_name, problem_id, answer_text, question_text, confidence,
                            match_reason, source_file, source_page, answer_index)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            bank_name,
                            problem_id,
                            answer_text,
                            m.get("question_text", ""),
                            confidence,
                            m.get("match_reason", ""),
                            source_file,
                            m.get("source_page", 0),
                            m.get("answer_index", 0),
                        ),
                    )
                    added += 1
                except Exception as e:
                    logger.warning(f"导入答案映射失败 (problem={problem_id}): {e}")
                    skipped += 1

        logger.info(f"答案映射导入完成: 新增 {added}, 跳过 {skipped}")
        return {"added": added, "skipped": skipped}

    def get_answer_for_problem(self, bank_name: str, problem_id: str) -> Optional[dict]:
        """
        获取某道题目的匹配答案（取置信度最高的一条）。

        返回:
            {"answer_text": str, "confidence": float, "match_reason": str, "source_file": str}
            或 None（无匹配答案）
        """
        with self._connect() as conn:
            row = conn.execute(
                """SELECT answer_text, confidence, match_reason, source_file, question_text
                   FROM answer_mapping
                   WHERE bank_name = ? AND problem_id = ?
                   ORDER BY confidence DESC
                   LIMIT 1""",
                (bank_name, problem_id),
            ).fetchone()

        if row:
            return {
                "answer_text": row["answer_text"],
                "confidence": row["confidence"],
                "match_reason": row["match_reason"],
                "source_file": row["source_file"],
                "question_text": row["question_text"],
            }
        return None

    def get_all_answer_mappings(self, bank_name: str) -> list[dict]:
        """获取题库中所有答案映射（用于查看和管理）"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT am.problem_id, am.answer_text, am.confidence, am.match_reason,
                          am.source_file, am.source_page, am.answer_index, am.created_at,
                          p.question, p.domain
                   FROM answer_mapping am
                   LEFT JOIN problems p ON am.problem_id = p.problem_id AND am.bank_name = p.bank_name
                   WHERE am.bank_name = ?
                   ORDER BY am.problem_id, am.confidence DESC""",
                (bank_name,),
            ).fetchall()

        return [
            {
                "problem_id": r["problem_id"],
                "answer_text": r["answer_text"],
                "confidence": r["confidence"],
                "match_reason": r["match_reason"],
                "source_file": r["source_file"],
                "source_page": r["source_page"],
                "answer_index": r["answer_index"],
                "created_at": r["created_at"],
                "question_preview": (r["question"] or "")[:80],
                "domain": r["domain"] or "",
            }
            for r in rows
        ]

    def get_answer_mapping_stats(self, bank_name: str) -> dict:
        """获取答案映射统计信息"""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM answer_mapping WHERE bank_name = ?",
                (bank_name,),
            ).fetchone()["cnt"]

            covered = conn.execute(
                "SELECT COUNT(DISTINCT problem_id) as cnt FROM answer_mapping WHERE bank_name = ?",
                (bank_name,),
            ).fetchone()["cnt"]

            total_problems = conn.execute(
                "SELECT COUNT(*) as cnt FROM problems WHERE bank_name = ?",
                (bank_name,),
            ).fetchone()["cnt"]

        return {
            "total_mappings": total,
            "covered_problems": covered,
            "total_problems": total_problems,
            "coverage_rate": round(covered / total_problems * 100, 1) if total_problems > 0 else 0,
        }

    def delete_answer_mappings(self, bank_name: str) -> int:
        """删除题库的所有答案映射，返回删除数"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM answer_mapping WHERE bank_name = ?",
                (bank_name,),
            )
            deleted = cur.rowcount
            logger.info(f"已删除 {bank_name} 的 {deleted} 条答案映射")
            return deleted

    def delete_answer_mapping_by_id(self, mapping_id: int) -> bool:
        """删除单条答案映射"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM answer_mapping WHERE id = ?",
                (mapping_id,),
            )
            return cur.rowcount > 0

    # === 完整答案导入流程（提取 + 匹配 + 入库） ===

    def import_answers_from_file(
        self,
        answer_file: str,
        bank_name: str,
        batch_size: int = 15,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """
        一键完成「答案文档导入 → 智能匹配 → 入库」的完整流程。

        参数:
            answer_file: 答案文档路径 (.pptx / .docx / .txt)
            bank_name: 目标题库名称
            batch_size: 每批匹配的答案数量
            progress_callback: 进度回调

        返回:
            {
                "extracted_count": 提取的答案条数,
                "matched_count": 成功匹配数,
                "imported_count": 入库数,
                "coverage_rate": 题库覆盖率,
                "tokens_used": token 消耗,
                "latency": 总耗时,
                "errors": [...],
            }
        """
        import time as _time
        from answer_extractor import extract_answers
        from answer_matcher import match_answers_to_bank

        start_time = _time.time()

        # 验证题库存在
        if not self.bank_exists(bank_name):
            raise ValueError(f"题库不存在: {bank_name}")

        # 步骤1: 提取答案
        if progress_callback:
            progress_callback(0, 100, "正在从答案文档中提取内容...")

        answer_pairs = extract_answers(answer_file)
        extracted_count = len(answer_pairs)

        if extracted_count == 0:
            return {
                "extracted_count": 0,
                "matched_count": 0,
                "imported_count": 0,
                "coverage_rate": 0,
                "tokens_used": 0,
                "latency": 0,
                "errors": ["未能从文件中提取到任何答案"],
            }

        if progress_callback:
            progress_callback(10, 100, f"已提取 {extracted_count} 条答案，准备匹配...")

        # 步骤2: 获取题库所有题目
        bank_problems = self.get_all_problems(bank_name)
        if not bank_problems:
            raise ValueError(f"题库 {bank_name} 中没有题目，请先导入题目")

        if progress_callback:
            progress_callback(20, 100, f"正在用 AI 匹配 {extracted_count} 条答案到 {len(bank_problems)} 道题目...")

        # 步骤3: DeepSeek 智能匹配
        def match_progress(current, total, msg):
            if progress_callback:
                pct = 20 + int(current / total * 50) if total > 0 else 20
                progress_callback(pct, 100, msg)

        match_result = match_answers_to_bank(
            answer_pairs,
            bank_problems,
            batch_size=batch_size,
            progress_callback=match_progress,
        )

        # 步骤4: 入库
        if progress_callback:
            progress_callback(80, 100, "正在将匹配结果写入数据库...")

        source_filename = os.path.basename(answer_file)

        # 将 question_text 和 source_page 合并到 matches 中
        enriched_matches = []
        for m in match_result["matches"]:
            answer_idx = m.get("answer_index", 0)
            # 找到对应的原始答案条目
            orig = next(
                (ap for ap in answer_pairs if ap["index"] == answer_idx),
                None,
            )
            if orig:
                m["question_text"] = orig.get("question_text", "")
                m["source_page"] = orig.get("source_page", 0)
            enriched_matches.append(m)

        import_result = self.import_answer_mappings(
            bank_name,
            enriched_matches,
            source_file=source_filename,
        )

        # 统计覆盖率
        stats = self.get_answer_mapping_stats(bank_name)
        elapsed = round(_time.time() - start_time, 1)

        if progress_callback:
            progress_callback(100, 100, f"完成！{import_result['added']} 条答案已入库")

        return {
            "extracted_count": extracted_count,
            "matched_count": match_result["matched_count"],
            "imported_count": import_result["added"],
            "coverage_rate": stats["coverage_rate"],
            "tokens_used": match_result["tokens_used"],
            "latency": elapsed,
            "errors": match_result["errors"],
        }

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

        return f"""你是一个严格的数学题库质量管理专家兼数学题目优化工程师。请对以下{len(problems_batch)}道数学题目进行质量审核与优化。

## 题库领域分布
{domain_info}

## 待审核题目
{items_text}

## 审核要求

### 第一部分：有效性判断
请逐题判断每道题目是否为**完整、有意义、可评测的数学题**。以下情况应判定为「无效」：
1. 题干为空、只有标点符号或只有1-3个无意义字符
2. 题干只有选项没有问题（如 "A. 0 B. - C. D. ∞")
3. 题干是残缺的公式片段（如 "=____"、"lim/ x→0 x / sin2x ="、"2 3 2"）
4. 题干是乱码、无意义数字组合或格式错乱无法理解
5. 题目重复（与其他题目实质内容相同）

### 第二部分：题目复现与题干逻辑优化（重要！）
对于**有效的题目**，你必须：
1. **复现题目**：用你自己的语言重新完整描述这道数学题，修复原始题干中可能的格式错误（如 LaTeX 残缺、符号混乱、OCR 识别错乱等）
2. **优化题干逻辑**：
   - 补全被截断的条件或问题（如 "则 =" 补全为 "则该函数在点(2,1)处的值为多少？"）
   - 统一数学表达方式（将散乱的公式整理为规范的数学表述）
   - 明确选项（如果原题有选项但格式混乱，重新整理为 A/B/C/D 格式）
   - 补充必要的上下文信息（如函数定义域、积分区间等）
   - 将 OCR 导致的识别错误修正为正确的数学符号
3. **保留核心不变**：优化的题目必须与原题考查**相同的数学知识点**，答案一致

### 第三步：补全新题目
根据题库已有领域，生成少量高质量新数学题来补充题库（约 {min(3, max(1, len(problems_batch) // 5))} 道）。
新题目要求：
- 覆盖微积分、极限、导数、积分、偏导数、级数等高等数学核心知识点
- 题干完整清晰，有确定答案
- 领域从题库已有领域中选择

## 输出格式（严格 JSON，不要输出其他文字）
```json
{{
  "results": [
    {{
      "index": 1,
      "is_valid": true/false,
      "reason": "简短说明判断理由",
      "optimized_question": "【必须填写】复现并优化后的完整题干。即使原题看起来没问题，也要用规范的数学语言重写，确保清晰准确。",
      "optimized_answer": "基于优化后题干的参考答案",
      "optimization_notes": "简要说明做了哪些优化（如'修复了LaTeX格式''补全了被截断的问题''统一了选项格式'），如果无需优化则填'原题质量良好'"
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

注意：
- optimized_question 字段**对于有效题目必须填写**，不能为 null
- new_problems 数组中生成 {min(3, max(1, len(problems_batch) // 5))} 道高质量新题目
- 新题目应覆盖微积分、极限、导数、积分、偏导数、级数等高等数学核心知识点。"""

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
        optimized_count = 0
        errors = []

        # 分批处理（复用同一个事件循环，避免每批都创建/销毁 asyncio.run 的开销）
        loop = asyncio.new_event_loop()
        try:
            for batch_start in range(0, total, batch_size):
                batch = all_problems[batch_start : batch_start + batch_size]
                current_batch_end = min(batch_start + batch_size, total)

                if progress_callback:
                    progress_callback(batch_start, total, f"正在审核第 {batch_start+1}-{current_batch_end} 题...")

                try:
                    result = loop.run_until_complete(self._audit_batch_async(batch, domains))

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
                                # 用 DeepSeek 复现并优化的题干更新原题
                                opt_q = item.get("optimized_question")
                                opt_a = item.get("optimized_answer")
                                if opt_q and isinstance(opt_q, str) and len(opt_q.strip()) > 10:
                                    # 只有优化版本与原题明显不同时才更新（避免无意义的微小变化）
                                    if opt_q.strip() != p.question.strip():
                                        try:
                                            self._update_problem_text(
                                                p.id, bank_name,
                                                question=opt_q.strip(),
                                                reference_answer=opt_a.strip() if (opt_a and isinstance(opt_a, str) and opt_a.strip()) else None,
                                            )
                                            optimized_count += 1
                                            notes = item.get("optimization_notes", "")
                                            logger.info(f"[质量审核] 优化题干: {p.id} — {notes[:80]}")
                                        except Exception as e:
                                            errors.append(f"更新题目 {p.id} 失败: {e}")

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

        finally:
            loop.close()

        return {
            "total_audited": total,
            "valid_count": valid_count,
            "deleted_count": len(deleted_ids),
            "added_count": added_count,
            "optimized_count": optimized_count,
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
