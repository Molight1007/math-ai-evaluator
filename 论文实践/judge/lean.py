# -*- coding: utf-8 -*-
"""Lean 4 客观判据。

职责：把模型产出的 Lean 代码丢给真实的 Lean 编译器，判定它是不是一个
**真正成立的形式化证明**。这是整个实验区别于"LLM 自评"的根本：
Lean 不会给面子，编译不过就是不过。

关键点：
1. 临时文件必须落在 **ASCII 路径**（Lean 对非 ASCII 路径敏感，本机项目路径含中文）。
2. 通过 LEAN_PATH 挂载主项目的 Mathlib 闭包（338 个 olean，只读引用，绝不修改）。
3. `sorry` 单独标记：用了 sorry 的"证明"等于没证，但可记为"骨架正确、未完成"。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import config


@dataclass
class LeanResult:
    ok: bool = False            # 编译通过且无 sorry
    compiled: bool = False      # 编译通过（可能含 sorry）
    sorry: bool = False         # 使用了 sorry / admit / by?
    timeout: bool = False
    errors: list[str] = field(default_factory=list)
    stderr: str = ""
    stdout: str = ""
    elapsed: float = 0.0
    note: str = ""


def _resolve_lean_exe() -> str:
    """定位 lean 可执行文件。"""
    cand = config.LEAN_EXE
    if os.path.isabs(cand) and Path(cand).is_file():
        return cand
    found = shutil.which(cand)
    if found:
        return found
    if config.LEAN_FALLBACK_EXE.is_file():
        return str(config.LEAN_FALLBACK_EXE)
    return cand


def _lean_env() -> dict[str, str]:
    """构造子进程环境：用 LEAN_PATH 挂载 Mathlib 闭包（只读）。"""
    env = os.environ.copy()
    roots: list[str] = []
    if config.MATHLIB_CLOSURE.is_dir():
        roots.append(str(config.MATHLIB_CLOSURE))
    existing = env.get("LEAN_PATH", "")
    if existing:
        roots.extend(d for d in existing.split(os.pathsep) if d)
    if roots:
        env["LEAN_PATH"] = os.pathsep.join(dict.fromkeys(roots))
    return env


_LEAN_EXE: str | None = None
_LEAN_ENV: dict[str, str] | None = None
_DEBUG_DIR = config.RESULTS_DIR / "lean_debug"


def _setup() -> tuple[str, dict[str, str]]:
    global _LEAN_EXE, _LEAN_ENV
    if _LEAN_EXE is None:
        _LEAN_EXE = _resolve_lean_exe()
    if _LEAN_ENV is None:
        _LEAN_ENV = _lean_env()
    return _LEAN_EXE, _LEAN_ENV


def check(code: str, tag: str = "probe") -> LeanResult:
    """编译一段 Lean 4 代码，返回判定结果。"""
    res = LeanResult()
    if not code or not code.strip():
        res.note = "空代码"
        res.errors = ["未抽取到 Lean 代码"]
        return res

    exe, env = _setup()
    tmpdir = tempfile.mkdtemp(prefix="leanprobe_")
    try:
        fpath = Path(tmpdir) / "Probe.lean"
        fpath.write_text(code, encoding="utf-8")
        t0 = time.time()
        try:
            proc = subprocess.run(
                [exe, str(fpath)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=config.LEAN_TIMEOUT,
                env=env,
                cwd=tmpdir,
            )
            res.stdout = (proc.stdout or "")[:4000]
            res.stderr = (proc.stderr or "")[:4000]
            res.returncode = proc.returncode  # type: ignore[attr-defined]
        except subprocess.TimeoutExpired:
            res.timeout = True
            res.note = f"编译超时（>{config.LEAN_TIMEOUT}s）"
            return res
        except FileNotFoundError:
            res.note = f"找不到 lean 可执行文件：{exe}"
            res.errors = [res.note]
            return res
        finally:
            res.elapsed = time.time() - t0

        combined = f"{res.stdout}\n{res.stderr}"
        res.errors = [
            ln.strip()
            for ln in combined.splitlines()
            if "error:" in ln
        ][:10]
        res.compiled = (res.returncode == 0) and not res.errors

        low = combined.lower()
        res.sorry = (
            "declaration uses 'sorry'" in low
            or "declaration uses 'admit'" in low
            or "unsolved goals" in low
        )
        res.ok = res.compiled and not res.sorry
        if res.compiled and res.sorry:
            res.note = "编译通过但含 sorry / 未完成目标"
        elif not res.compiled:
            res.note = "编译失败"

        # 失败样本留档，便于人工复核（这是论文里"失败模式分析"的素材）
        if not res.ok:
            try:
                _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                (_DEBUG_DIR / f"{tag}.lean").write_text(code, encoding="utf-8")
                (_DEBUG_DIR / f"{tag}.log").write_text(combined, encoding="utf-8")
            except Exception:
                pass
        return res
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def warmup() -> LeanResult:
    """预热：先编一个最小文件，把 Mathlib 闭包的加载开销前置掉。"""
    return check(
        "import Mathlib.Tactic\n\nexample : (1:ℕ) + 1 = 2 := by norm_num\n",
        tag="_warmup",
    )


def available() -> tuple[bool, str]:
    """环境自检：lean 可执行文件 + Mathlib 闭包是否就绪。"""
    exe, _ = _setup()
    if not (os.path.isabs(exe) and Path(exe).is_file()) and not shutil.which(exe):
        return False, f"lean 不可执行：{exe}"
    if not config.MATHLIB_CLOSURE.is_dir():
        return False, f"Mathlib 闭包缺失：{config.MATHLIB_CLOSURE}"
    r = warmup()
    if not r.compiled:
        return False, f"预热编译失败（{(r.errors or ['无错误详情'])[0]}）"
    return True, f"Lean 就绪（预热 {r.elapsed:.1f}s，闭包 {config.MATHLIB_CLOSURE}）"
