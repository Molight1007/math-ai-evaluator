# -*- coding: utf-8 -*-
"""LEAP 复现评测面板（GUI 标签页）

在 GUI 评测器中加入 LEAP 三阶段（论文复现）评测入口：
- 从 lean_proof_bench.csv 选题（多选）
- 选择后端模型（书生 / DeepSeek）与模式（框架 / 裸模型 / 两者对照）
- 后台线程跑三阶段（Blueprint DAG → 整树搭桥 → 迭代精炼），实时日志
- 结果汇总 + 保存 JSON

复用 tools/leap_eval.py 的评测逻辑（load_bench / run_single / run_bare）。
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

# ---- 路径：项目根 + tools ----
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from user_agent import AgentConfig  # noqa: E402
from tools.leap_eval import (  # noqa: E402
    load_bench, make_client, run_single, run_bare,
)

BENCH_HINT = os.path.join(PROJECT_ROOT, "superhuman", "imobench",
                          "lean_proof_bench.csv")


class LeapPanel(ttk.Frame):
    """LEAP 复现评测标签页。"""

    def __init__(self, parent, launcher=None):
        super().__init__(parent, padding=(12, 10))
        self.launcher = launcher
        self._items = []
        self._q = queue.Queue()
        self._worker = None
        self._stop_flag = threading.Event()

        self._build_ui()
        self.after(120, self._poll_queue)
        self._load_bench()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        # 左：选题
        left = ttk.LabelFrame(self, text="选题（Lean-IMO-Bench Basic）", padding=(8, 6))
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.listbox = tk.Listbox(left, selectmode="extended",
                                  font=("Consolas", 9), height=16,
                                  exportselection=False)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="全选", width=6,
                   command=lambda: self.listbox.selection_set(0, "end")).pack(side="left")
        ttk.Button(btn_row, text="清空", width=6,
                   command=lambda: self.listbox.selection_clear(0, "end")).pack(side="left", padx=(4, 0))
        ttk.Button(btn_row, text="刷新题库", width=8,
                   command=self._load_bench).pack(side="left", padx=(12, 0))

        # 右：参数 + 日志
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)

        param = ttk.LabelFrame(right, text="评测参数", padding=(8, 6))
        param.pack(fill="x")

        row1 = ttk.Frame(param)
        row1.pack(fill="x")
        ttk.Label(row1, text="后端模型:").pack(side="left")
        self.backend_var = tk.StringVar(value="intern")
        ttk.Radiobutton(row1, text="书生 Intern-S2", value="intern",
                        variable=self.backend_var).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(row1, text="DeepSeek", value="deepseek",
                        variable=self.backend_var).pack(side="left", padx=(6, 0))
        ttk.Label(row1, text="(DeepSeek 按团队决定暂停对照)",
                  foreground="#a0aec0").pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(param)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Label(row2, text="评测模式:").pack(side="left")
        self.mode_var = tk.StringVar(value="framework")
        ttk.Radiobutton(row2, text="框架（LEAP 三阶段）", value="framework",
                        variable=self.mode_var).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(row2, text="裸模型（对照）", value="bare",
                        variable=self.mode_var).pack(side="left", padx=(6, 0))

        self.run_btn = ttk.Button(param, text="▶ 开始 LEAP 复现评测",
                                  command=self._start)
        self.run_btn.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(param, mode="determinate")
        self.progress.pack(fill="x", pady=(6, 0))

        # 日志区
        log_frame = ttk.LabelFrame(right, text="运行日志 / 结果", padding=(8, 6))
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(log_frame, height=14, font=("Consolas", 9),
                                state="disabled", wrap="word")
        log_sb = ttk.Scrollbar(log_frame, orient="vertical",
                               command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _load_bench(self):
        try:
            self._items = load_bench("")
        except FileNotFoundError as e:
            self._log(f"[警告] 基准文件未找到：{e}\n请在 {BENCH_HINT} 准备题目\n")
            return
        self.listbox.delete(0, "end")
        for it in self._items:
            self.listbox.insert("end",
                                f"{it['id']}  |  {it['problem'][:42]}")
        self._log(f"题库加载 {len(self._items)} 题（{BENCH_HINT}）\n")

    def _selected_items(self):
        idxs = self.listbox.curselection()
        return [self._items[i] for i in idxs]

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    self.run_btn.configure(state="normal")
                    self.progress["value"] = 100
                    self._log("\n========== 评测完成 ==========\n")
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    # ------------------------------------------------------------------
    # 评测
    # ------------------------------------------------------------------
    def _start(self):
        items = self._selected_items()
        if not items:
            self._log("[提示] 请先在左侧选择题目\n")
            return
        if self._worker and self._worker.is_alive():
            self._log("[提示] 评测进行中\n")
            return
        backend = self.backend_var.get()
        mode = self.mode_var.get()
        try:
            client = make_client(backend)
        except RuntimeError as e:
            self._log(f"[错误] {e}\n")
            return
        cfg = AgentConfig(use_blueprint=True, enable_sketch_audit=True,
                          use_refiner=True)
        self.run_btn.configure(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = len(items)
        self._worker = threading.Thread(
            target=self._worker_run, args=(client, cfg, items, mode),
            daemon=True)
        self._worker.start()

    def _worker_run(self, client, cfg, items, mode):
        self._q.put(("log", f"后端: {client.model} | 模式: {mode} | {len(items)} 题\n\n"))
        results = []
        for i, item in enumerate(items, 1):
            self._q.put(("log", f"\n=== [{i}/{len(items)}] {item['id']} ===\n"))
            try:
                if mode == "bare":
                    r = run_bare(client, cfg, item)
                    self._q.put(("log",
                                 f"  编译通过: {r.get('compiled')} | "
                                 f"sorry: {r.get('sorries')} | "
                                 f"耗时: {r.get('elapsed_s')}s\n"))
                else:
                    r = run_single(client, cfg, item)
                    st = r.get("steps", {})
                    line = (
                        f"  形式化: {st.get('preverify', {}).get('verdict')} | "
                        f"Blueprint: {st.get('blueprint', {}).get('ok')} | "
                        f"Stage2: {st.get('stage2', {}).get('verdict')} | "
                        f"Stage3: {st.get('stage3', {}).get('verdict')} | "
                        f"耗时: {r.get('elapsed_s')}s")
                    self._q.put(("log", "  " + line + "\n"))
                results.append(r)
            except Exception as e:  # noqa: BLE001
                self._q.put(("log", f"  [异常] {str(e)[:150]}\n"))
            self._q.put(("progress", i))

        # 汇总
        ok_n = sum(1 for r in results if _is_ok(r, mode))
        self._q.put(("log",
                     f"\n---- 汇总：通过 {ok_n}/{len(results)} ----\n"))
        out_dir = os.path.join(PROJECT_ROOT, "eval_gui_out")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir,
                                f"leap_gui_{mode}_{int(__import__('time').time())}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"mode": mode, "backend": client.model,
                       "results": results}, f, ensure_ascii=False, indent=1)
        self._q.put(("log", f"结果已保存: {out_path}\n"))
        self._q.put(("done", None))


def _is_ok(r, mode):
    """判定单题通过：bare=编译通过；framework=Stage3 ok。"""
    if mode == "bare":
        return bool(r.get("compiled"))
    return (r.get("steps", {}).get("stage3", {}) or {}).get("verdict") == "ok"
