"""
数学智能体评测器 – GUI 启动器
支持拖入或选择 PDF / Word / JSON / CSV 文件，一键评测。
支持题库管理：创建题库、导入题目、随机选题评测。

用法:
    python 测试工具/launcher.py
    pythonw 测试工具/launcher.py    （无控制台窗口）
"""
import asyncio
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "测试工具"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "转化工具"))

from config import has_config, load_config, save_config, reset_config, ConfigError, validate_config


# ==================== 题库管理面板 ====================

class QuestionBankPanel(ttk.Frame):
    """题库管理选项卡"""

    def __init__(self, parent, launcher):
        super().__init__(parent)
        self.launcher = launcher
        self._db = None
        self._eval_running = False
        self._audit_running = False

        # 第一行：题库选择 + 新建
        row1 = ttk.Frame(self)
        row1.pack(fill="x", padx=15, pady=(15, 8))

        ttk.Label(row1, text="当前题库:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.bank_var = tk.StringVar()
        self.bank_combo = ttk.Combobox(row1, textvariable=self.bank_var, state="readonly",
                                        font=("Microsoft YaHei", 10), width=18)
        self.bank_combo.pack(side="left", padx=(6, 12))
        self.bank_combo.bind("<<ComboboxSelected>>", self._on_bank_selected)

        ttk.Button(row1, text="🔄 刷新", command=self._refresh_banks,
                   width=8).pack(side="left", padx=(0, 15))

        ttk.Label(row1, text="新建:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.new_bank_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.new_bank_var, font=("Microsoft YaHei", 10),
                  width=14).pack(side="left", padx=(4, 6))
        ttk.Button(row1, text="创建", command=self._create_bank, width=6).pack(side="left")
        ttk.Button(row1, text="删除", command=self._delete_bank, width=6).pack(side="left", padx=(4, 0))

        # 第二行：统计信息
        row2 = ttk.Frame(self)
        row2.pack(fill="x", padx=15, pady=(0, 8))
        self.stats_var = tk.StringVar(value="题库统计: —")
        ttk.Label(row2, textvariable=self.stats_var, font=("Microsoft YaHei", 9),
                  foreground="#4a5568").pack(anchor="w")

        # 第三行：导入 & 添加
        row3 = ttk.Frame(self)
        row3.pack(fill="x", padx=15, pady=(0, 8))

        ttk.Button(row3, text="📂 从文件导入题目", command=self._import_from_file,
                   width=18).pack(side="left", padx=(0, 8))
        ttk.Button(row3, text="✏️ 手动添加题目", command=self._manual_add,
                   width=18).pack(side="left", padx=(0, 8))
        self.audit_btn = ttk.Button(row3, text="🔍 AI质量审核", command=self._start_audit_quality,
                                     width=14)
        self.audit_btn.pack(side="left")

        # 第四行：随机选题评测
        eval_frame = ttk.LabelFrame(self, text="随机选题评测", padding=(10, 8))
        eval_frame.pack(fill="x", padx=15, pady=(5, 10))

        eval_inner = ttk.Frame(eval_frame)
        eval_inner.pack(fill="x")

        ttk.Label(eval_inner, text="选题数量:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.count_var = tk.IntVar(value=5)
        ttk.Spinbox(eval_inner, from_=1, to=999, width=5, textvariable=self.count_var,
                    font=("Microsoft YaHei", 10)).pack(side="left", padx=(4, 15))

        ttk.Label(eval_inner, text="领域筛选:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.domain_var = tk.StringVar(value="全部")
        self.domain_combo = ttk.Combobox(eval_inner, textvariable=self.domain_var,
                                          state="readonly", font=("Microsoft YaHei", 10), width=12)
        self.domain_combo.pack(side="left", padx=(4, 15))

        self.bank_eval_btn = ttk.Button(eval_inner, text="🎯 从题库随机评测",
                                         command=self._start_bank_eval, width=18)
        self.bank_eval_btn.pack(side="left")

        # 题目列表（Treeview 表格）
        list_frame = ttk.LabelFrame(self, text="题库题目列表", padding=(8, 5))
        list_frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # Treeview
        columns = ("ID", "domain", "question_preview")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                                  selectmode="browse", height=8)
        self.tree.heading("ID", text="ID", anchor="w")
        self.tree.heading("domain", text="领域", anchor="w")
        self.tree.heading("question_preview", text="题干（预览）", anchor="w")
        self.tree.column("ID", width=70, minwidth=50)
        self.tree.column("domain", width=90, minwidth=60)
        self.tree.column("question_preview", width=320, minwidth=150)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 右键菜单
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="删除此题目", command=self._delete_selected_problem)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # 底部状态栏
        self.bank_status_var = tk.StringVar(value="就绪 — 请选择一个题库")
        ttk.Label(self, textvariable=self.bank_status_var, font=("Microsoft YaHei", 9),
                  foreground="#718096").pack(anchor="w", padx=15, pady=(0, 5))

        self._refresh_banks()

    @property
    def db(self):
        if self._db is None:
            from question_bank import get_db
            self._db = get_db()
        return self._db

    def _refresh_banks(self):
        """刷新题库下拉列表和统计"""
        banks = self.db.list_banks()
        names = [b["name"] for b in banks]
        self.bank_combo["values"] = names

        if names:
            if self.bank_var.get() not in names:
                self.bank_var.set(names[0])
            self._update_stats_and_list()
        else:
            self.bank_var.set("")
            self.stats_var.set("题库统计: 暂无题库，请新建")
            self._clear_tree()
            self.domain_combo["values"] = ["全部"]
            self.domain_var.set("全部")

    def _on_bank_selected(self, event=None):
        self._update_stats_and_list()

    def _update_stats_and_list(self):
        bank = self.bank_var.get()
        if not bank:
            self.stats_var.set("题库统计: —")
            self._clear_tree()
            return

        total = self.db.get_problem_count(bank)
        domains = self.db.get_domains(bank)
        domain_str = ", ".join(domains[:5])
        if len(domains) > 5:
            domain_str += f" …共{len(domains)}个"

        self.stats_var.set(f"题库「{bank}」: 共 {total} 题 | 领域: {domain_str or '无'}")

        # 更新领域筛选下拉
        self.domain_combo["values"] = ["全部"] + domains
        if self.domain_var.get() not in ("全部", *domains):
            self.domain_var.set("全部")

        # 更新题目列表
        self._refresh_tree(bank)

    def _refresh_tree(self, bank_name: str):
        self._clear_tree()
        problems = self.db.get_all_problems(bank_name)
        seen_iids = set()
        for idx, p in enumerate(problems):
            preview = p.question[:60] + ("…" if len(p.question) > 60 else "")
            # 用题目 id 作为 iid，若为空或重复则用索引兜底
            iid = p.id if p.id else f"_auto_{idx}"
            if iid in seen_iids:
                iid = f"{p.id}_{idx}" if p.id else f"_auto_{idx}"
            seen_iids.add(iid)
            self.tree.insert("", "end", iid=iid, values=(p.id, p.domain or "", preview))

    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _on_tree_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)

    def _delete_selected_problem(self):
        sel = self.tree.selection()
        if not sel:
            return
        bank = self.bank_var.get()
        # 从 values[0] 取真正的 problem_id（iid 可能是自动生成的）
        values = self.tree.item(sel[0], "values")
        pid = values[0] if values else sel[0]
        if messagebox.askyesno("确认删除", f"确定要从题库「{bank}」中删除题目 {pid} 吗？"):
            self.db.remove_problem(pid, bank)
            self._update_stats_and_list()
            self.bank_status_var.set(f"已删除题目: {pid}")

    def _create_bank(self):
        name = self.new_bank_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入题库名称")
            return
        ok = self.db.create_bank(name)
        if ok:
            self.new_bank_var.set("")
            self._refresh_banks()
            self.bank_var.set(name)
            self._update_stats_and_list()
            self.bank_status_var.set(f"题库「{name}」创建成功")
        else:
            messagebox.showinfo("提示", f"题库「{name}」已存在")

    def _delete_bank(self):
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择要删除的题库")
            return
        if messagebox.askyesno("确认删除", f"确定要删除题库「{bank}」及其所有题目吗？\n此操作不可恢复！"):
            self.db.delete_bank(bank)
            self._refresh_banks()
            self.bank_status_var.set(f"题库「{bank}」已删除")

    def _import_from_file(self):
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择或创建一个题库")
            return

        path = filedialog.askopenfilename(
            title="选择题目文件导入到题库",
            filetypes=[
                ("所有支持格式", "*.json;*.csv;*.docx;*.pdf"),
                ("JSON 文件", "*.json"),
                ("CSV 文件", "*.csv"),
                ("Word 文档", "*.docx"),
                ("PDF 文件", "*.pdf"),
            ]
        )
        if not path:
            return

        try:
            result = self.db.import_from_file(path, bank)
            self._update_stats_and_list()
            self.bank_status_var.set(
                f"导入完成: 新增 {result['added']} 题, 跳过重复 {result['skipped']} 题"
            )
            messagebox.showinfo("导入完成",
                                f"从文件导入到题库「{bank}」\n"
                                f"新增: {result['added']} 题\n"
                                f"跳过(重复): {result['skipped']} 题\n"
                                f"总计处理: {result['total']} 题")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _manual_add(self):
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择或创建一个题库")
            return

        dialog = tk.Toplevel(self)
        dialog.title("手动添加题目")
        dialog.geometry("500x400")
        dialog.resizable(False, False)
        dialog.configure(bg="#f0f4f8")
        dialog.transient(self)
        dialog.grab_set()

        # 居中
        dialog.update_idletasks()
        x = dialog.winfo_screenwidth() // 2 - 250
        y = dialog.winfo_screenheight() // 2 - 200
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="添加题目到题库: " + bank,
                 font=("Microsoft YaHei", 12, "bold"), fg="#1a365d", bg="#f0f4f8").pack(pady=(12, 8))

        fields = [
            ("题目 ID *:", "id"),
            ("题干 *:", "question"),
            ("领域:", "domain"),
            ("参考答案:", "answer"),
        ]

        entries = {}
        for label_text, key in fields:
            frm = ttk.Frame(dialog)
            frm.pack(fill="x", padx=20, pady=3)
            ttk.Label(frm, text=label_text, font=("Microsoft YaHei", 10), width=12).pack(side="left")
            if key == "question":
                entry = tk.Text(frm, font=("Microsoft YaHei", 10), height=4, width=40,
                                wrap="word", bd=1, relief="solid")
                entry.pack(side="left", fill="x", expand=True)
            else:
                entry = ttk.Entry(frm, font=("Microsoft YaHei", 10), width=42)
                entry.pack(side="left", fill="x", expand=True)
            entries[key] = entry

        def do_add():
            pid = entries["id"].get().strip() if isinstance(entries["id"], ttk.Entry) else entries["id"].get("1.0", "end-1c").strip()
            q = entries["question"].get("1.0", "end-1c").strip()
            domain = entries["domain"].get().strip() if isinstance(entries["domain"], ttk.Entry) else entries["domain"].get("1.0", "end-1c").strip()
            ans = entries["answer"].get().strip() if isinstance(entries["answer"], ttk.Entry) else entries["answer"].get("1.0", "end-1c").strip()

            if not pid or not q:
                messagebox.showwarning("提示", "题目 ID 和题干为必填项", parent=dialog)
                return

            from models import Problem
            p = Problem(id=pid, question=q, domain=domain or None, reference_answer=ans or None)

            ok = self.db.add_problem(p, bank)
            if ok:
                self._update_stats_and_list()
                self.bank_status_var.set(f"题目 {pid} 已添加到题库「{bank}」")
                dialog.destroy()
            else:
                messagebox.showwarning("提示", f"题目 {pid} 在题库「{bank}」中已存在", parent=dialog)

        btn_f = ttk.Frame(dialog)
        btn_f.pack(pady=(10, 12))
        ttk.Button(btn_f, text="确认添加", command=do_add, width=12).pack(side="left", padx=(0, 10))
        ttk.Button(btn_f, text="取消", command=dialog.destroy, width=12).pack(side="left")

    def _start_bank_eval(self):
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择题库")
            return

        count = self.count_var.get()
        if count <= 0:
            messagebox.showwarning("提示", "选题数量必须大于 0")
            return

        domain = self.domain_var.get()
        if domain == "全部":
            domain = None

        # 检查题库是否有足够题目
        available = self.db.get_problem_count(bank, domain=domain)
        if available == 0:
            messagebox.showwarning("提示", f"题库「{bank}」中没有符合条件的题目")
            return
        if count > available:
            count = available
            self.count_var.set(count)

        # 检查 API 配置
        try:
            validate_config(load_config())
        except ConfigError as e:
            messagebox.showerror("配置错误", str(e))
            return

        if self._eval_running:
            messagebox.showinfo("提示", "评测正在进行中，请稍候")
            return

        self._eval_running = True
        self.bank_eval_btn.configure(state="disabled", text="评测中...")
        self.bank_status_var.set(f"正在从题库「{bank}」随机选取 {count} 道题目评测...")

        thread = threading.Thread(target=self._run_bank_eval_async,
                                  args=(bank, count, domain), daemon=True)
        thread.start()

    def _run_bank_eval_async(self, bank_name, count, domain):
        try:
            from main import run_evaluation_from_bank

            self.launcher.root.after(0, lambda: self.launcher.status_var.set(
                f"[题库评测] 从「{bank_name}」随机选题 {count} 道，正在评测..."))

            html_path = asyncio.run(
                run_evaluation_from_bank(bank_name, count, concurrency=10, domain=domain)
            )

            if html_path and os.path.exists(html_path):
                self.launcher.root.after(0, lambda: webbrowser.open(
                    f"file:///{html_path.replace(os.sep, '/')}"))
                self.launcher.root.after(0, lambda: self.bank_status_var.set(
                    f"评测完成！报告已打开（题库: {bank_name}, 选题: {count}）"))
                self.launcher.root.after(0, lambda: self.launcher.status_var.set(
                    "题库评测完成！报告已打开。"))
            else:
                self.launcher.root.after(0, lambda: self.bank_status_var.set("评测完成，但未生成报告"))
        except Exception as e:
            self.launcher.root.after(0, lambda: self.bank_status_var.set(f"评测失败: {e}"))
            self.launcher.root.after(0, lambda: messagebox.showerror("评测失败", str(e)))
        finally:
            self.launcher.root.after(0, lambda: self.bank_eval_btn.configure(
                state="normal", text="🎯 从题库随机评测"))
            self._eval_running = False

    def _start_audit_quality(self):
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择题库")
            return

        total = self.db.get_problem_count(bank)
        if total == 0:
            messagebox.showwarning("提示", f"题库「{bank}」中没有题目")
            return

        # 检查 API 配置（至少需要 DeepSeek）
        try:
            cfg = load_config()
            validate_config(cfg)
        except ConfigError as e:
            messagebox.showerror("配置错误", str(e))
            return
        except Exception as e:
            # 如果只有 DeepSeek key 也可以工作，Intern-S1 不是必须的
            if not (cfg and hasattr(cfg, 'deepseek') and cfg.deepseek.api_key):
                messagebox.showerror("配置错误", "请先在设置中配置 DeepSeek API Key")
                return

        # 确认对话框
        msg = (
            f"即将对题库「{bank}」中的 {total} 道题目进行 AI 质量审核：\n\n"
            f"• 调用 DeepSeek 判断每道题目是否为有效数学题\n"
            f"• 自动删除无效/残缺/无意义的题目\n"
            f"• 同时补全高质量新题目到题库\n\n"
            f"此过程需要一定时间（约 {max(1, total // 10)} 批次 API 调用），是否继续？"
        )
        if not messagebox.askyesno("AI 质量审核确认", msg):
            return

        self._audit_running = True
        self.audit_btn.configure(state="disabled", text="审核中...")
        self.bank_eval_btn.configure(state="disabled")
        self.bank_status_var.set(f"正在对题库「{bank}」进行 AI 质量审核...")

        thread = threading.Thread(target=self._run_audit_async, args=(bank,), daemon=True)
        thread.start()

    def _run_audit_async(self, bank_name):
        try:
            def on_progress(current, total, message):
                self.launcher.root.after(0, lambda: self.bank_status_var.set(
                    f"质量审核: {message} ({current}/{total})"))

            result = self.db.audit_quality(
                bank_name,
                batch_size=10,
                progress_callback=on_progress,
            )

            self.launcher.root.after(0, lambda: self.bank_status_var.set(
                f"质量审核完成！有效: {result['valid_count']}, "
                f"删除无效: {result['deleted_count']}, "
                f"补全新题: {result['added_count']}"))

            summary = (
                f"题库「{bank_name}」AI 质量审核完成！\n\n"
                f"总审核: {result['total_audited']} 题\n"
                f"保留有效: {result['valid_count']} 题\n"
                f"删除无效: {result['deleted_count']} 题\n"
                f"补全新题: {result['added_count']} 题"
            )
            if result["errors"]:
                summary += f"\n\n错误 ({len(result['errors'])}):\n" + "\n".join(result["errors"][:5])

            self.launcher.root.after(0, lambda: self._update_stats_and_list())
            self.launcher.root.after(0, lambda: messagebox.showinfo("审核完成", summary))

        except Exception as e:
            self.launcher.root.after(0, lambda: self.bank_status_var.set(f"审核失败: {e}"))
            self.launcher.root.after(0, lambda: messagebox.showerror("审核失败", str(e)))
        finally:
            self.launcher.root.after(0, lambda: self.audit_btn.configure(
                state="normal", text="🔍 AI质量审核"))
            self.launcher.root.after(0, lambda: self.bank_eval_btn.configure(state="normal"))
            self._audit_running = False


# ==================== 主启动器 ====================

class EvalLauncher:
    def __init__(self):
        try:
            from tkinterdnd2 import TkinterDnD
            self.root = TkinterDnD.Tk()
            self._dnd_available = True
        except ImportError:
            self.root = tk.Tk()
            self._dnd_available = False
        self.root.title("数学智能体评测器")
        self.root.geometry("620x650")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f4f8")
        self.root.minsize(520, 500)

        title_frame = tk.Frame(self.root, bg="#f0f4f8")
        title_frame.pack(pady=(15, 5))
        tk.Label(
            title_frame, text="数学智能体评测器",
            font=("Microsoft YaHei", 18, "bold"), fg="#1a365d", bg="#f0f4f8"
        ).pack()
        tk.Label(
            title_frame, text="Intern-S1 + DeepSeek 自动评测流水线",
            font=("Microsoft YaHei", 9), fg="#718096", bg="#f0f4f8"
        ).pack()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(5, 0))

        self.file_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.file_tab, text="📄 文件评测")

        self.drop_frame = tk.Frame(
            self.file_tab, bg="white", bd=2, relief="groove",
            highlightbackground="#cbd5e0", highlightthickness=1
        )
        self.drop_frame.pack(padx=15, pady=(10, 5), fill="both", expand=True)

        self.drop_label = tk.Label(
            self.drop_frame,
            text="拖放文件到此处\n或点击下方按钮选择",
            font=("Microsoft YaHei", 11), fg="#a0aec0", bg="white",
            justify="center"
        )
        self.drop_label.pack(expand=True)

        self.drop_frame.bind("<Enter>", self._on_drag_enter)
        self.drop_frame.bind("<Leave>", self._on_drag_leave)
        self.drop_label.bind("<Enter>", self._on_drag_enter)
        self.drop_label.bind("<Leave>", self._on_drag_leave)

        self.path_var = tk.StringVar(value="未选择文件")
        path_label = tk.Label(
            self.file_tab, textvariable=self.path_var,
            font=("Consolas", 9), fg="#4a5568", bg="#f0f4f8",
            anchor="w", wraplength=500
        )
        path_label.pack(padx=15, pady=(2, 8), fill="x")

        settings_frame = tk.Frame(self.file_tab, bg="#f0f4f8")
        settings_frame.pack(padx=15, pady=(0, 5), fill="x")

        tk.Label(
            settings_frame, text="并发数:", font=("Microsoft YaHei", 10),
            bg="#f0f4f8", fg="#4a5568"
        ).pack(side="left")
        self.concurrency_var = tk.IntVar(value=10)
        tk.Spinbox(
            settings_frame, from_=1, to=10, width=4,
            textvariable=self.concurrency_var, font=("Microsoft YaHei", 10),
            justify="center"
        ).pack(side="left", padx=(5, 15))

        tk.Label(
            settings_frame, text="题目上限:", font=("Microsoft YaHei", 10),
            bg="#f0f4f8", fg="#4a5568"
        ).pack(side="left")
        self.max_var = tk.IntVar(value=0)
        tk.Spinbox(
            settings_frame, from_=0, to=9999, width=5,
            textvariable=self.max_var, font=("Microsoft YaHei", 10),
            justify="center"
        ).pack(side="left", padx=(5, 5))
        tk.Label(
            settings_frame, text="(0=全部)", font=("Microsoft YaHei", 8),
            bg="#f0f4f8", fg="#a0aec0"
        ).pack(side="left")

        btn_frame = tk.Frame(self.file_tab, bg="#f0f4f8")
        btn_frame.pack(padx=15, pady=(5, 10), fill="x")

        self.select_btn = tk.Button(
            btn_frame, text="选择文件", command=self._select_file,
            font=("Microsoft YaHei", 10), bg="#edf2f7", fg="#2d3748",
            activebackground="#e2e8f0", relief="flat", padx=16, pady=4,
            cursor="hand2"
        )
        self.select_btn.pack(side="left", padx=(0, 10))

        self.run_btn = tk.Button(
            btn_frame, text="开始评测", command=self._start_eval,
            font=("Microsoft YaHei", 10, "bold"), bg="#3182ce", fg="white",
            activebackground="#2b6cb0", relief="flat", padx=20, pady=4,
            cursor="hand2", state="disabled"
        )
        self.run_btn.pack(side="left", padx=(0, 10))

        self.settings_btn = tk.Button(
            btn_frame, text="设置", command=self._show_api_dialog,
            font=("Microsoft YaHei", 10), bg="#edf2f7", fg="#2d3748",
            activebackground="#e2e8f0", relief="flat", padx=12, pady=4,
            cursor="hand2"
        )
        self.settings_btn.pack(side="left", padx=(0, 10))

        self.clear_btn = tk.Button(
            btn_frame, text="清理结果", command=self._clear_results,
            font=("Microsoft YaHei", 10), bg="#fee2e2", fg="#991b1b",
            activebackground="#fecaca", relief="flat", padx=12, pady=4,
            cursor="hand2"
        )
        self.clear_btn.pack(side="left")

        self.bank_panel = QuestionBankPanel(self.notebook, launcher=self)
        self.notebook.add(self.bank_panel, text="📚 题库评测")

        self.status_var = tk.StringVar(value="就绪 - 请选择题目文件或切换到题库评测")
        status_label = tk.Label(
            self.root, textvariable=self.status_var,
            font=("Microsoft YaHei", 9), fg="#718096", bg="#edf2f7",
            anchor="w", padx=10, pady=4
        )
        status_label.pack(fill="x", side="bottom")

        self.progress = ttk.Progressbar(
            self.root, mode="determinate", length=200, maximum=100
        )

        self.file_path = None

    def _on_drag_enter(self, event):
        self.drop_frame.configure(bg="#ebf8ff")
        self.drop_label.configure(bg="#ebf8ff")

    def _on_drag_leave(self, event):
        self.drop_frame.configure(bg="white")
        self.drop_label.configure(bg="white")

    def _select_file(self):
        path = filedialog.askopenfilename(
            title="选择题目文件",
            filetypes=[
                ("所有支持格式", "*.pdf;*.docx;*.json;*.csv"),
                ("PDF 文件", "*.pdf"),
                ("Word 文档", "*.docx"),
                ("JSON 文件", "*.json"),
                ("CSV 文件", "*.csv"),
            ]
        )
        if path:
            self._set_file(path)

    def _set_file(self, path):
        self.file_path = path
        basename = os.path.basename(path)
        self.path_var.set(basename)
        self.drop_label.configure(
            text=f"已选择: {basename}", fg="#2d3748"
        )
        self.run_btn.configure(state="normal")
        self.status_var.set(f"已选择: {basename} - 点击「开始评测」运行")

    def _clear_results(self):
        """清理所有评测结果（HTML/JSON/临时文件）"""
        if not messagebox.askyesno(
            "确认清理",
            "即将清除以下目录中的所有文件：\n\n"
            "• 测试结果/测试结果展示/（HTML 报告）\n"
            "• 测试结果/原始输出和推理过程/（JSON 数据）\n"
            "• 测试结果/原始问题/（临时题目文件）\n\n"
            "此操作不可恢复，是否继续？"
        ):
            return

        from main import clear_all_results
        counts = clear_all_results()

        parts = [f"{k}: {v} 个文件" for k, v in counts.items()]
        total = sum(counts.values())
        self.status_var.set(f"清理完成 - 共删除 {total} 个文件")
        messagebox.showinfo("清理完成", f"已清除以下文件：\n\n" + "\n".join(parts))

    def _show_api_dialog(self):
        """弹窗输入/修改 API Key"""
        existing_s1 = ""
        existing_ds = ""
        if has_config():
            try:
                cfg = load_config()
                existing_s1 = cfg.intern_s1.api_key
                existing_ds = cfg.deepseek.api_key
            except Exception:
                pass

        dialog = tk.Toplevel(self.root)
        dialog.title("API 配置")
        dialog.geometry("480x360")
        dialog.resizable(False, False)
        dialog.configure(bg="#f0f4f8")
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 480) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 360) // 2
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="API 配置",
                 font=("Microsoft YaHei", 13, "bold"), fg="#1a365d", bg="#f0f4f8").pack(pady=(15, 5))
        tk.Label(dialog, text="密钥将保存在 ~/.math_evaluator/.env",
                 font=("Microsoft YaHei", 8), fg="#a0aec0", bg="#f0f4f8").pack()

        # Intern-S1 推理模型配置
        f1 = tk.LabelFrame(dialog, text="Intern-S1 (推理模型)", bg="#f0f4f8",
                           font=("Microsoft YaHei", 10, "bold"), fg="#2d3748")
        f1.pack(padx=20, pady=(10, 5), fill="x")
        tk.Label(f1, text="API Key:", bg="#f0f4f8", font=("Microsoft YaHei", 9)).pack(anchor="w", padx=10, pady=(5, 0))
        s1_var = tk.StringVar(value=existing_s1)
        tk.Entry(f1, textvariable=s1_var, width=50, show="*",
                 font=("Consolas", 9)).pack(padx=10, pady=(2, 8), fill="x")

        # DeepSeek 评判模型配置
        f2 = tk.LabelFrame(dialog, text="DeepSeek (评判模型)", bg="#f0f4f8",
                           font=("Microsoft YaHei", 10, "bold"), fg="#2d3748")
        f2.pack(padx=20, pady=(0, 5), fill="x")
        tk.Label(f2, text="API Key:", bg="#f0f4f8", font=("Microsoft YaHei", 9)).pack(anchor="w", padx=10, pady=(5, 0))
        ds_var = tk.StringVar(value=existing_ds)
        tk.Entry(f2, textvariable=ds_var, width=50, show="*",
                 font=("Consolas", 9)).pack(padx=10, pady=(2, 8), fill="x")

        btn_f = tk.Frame(dialog, bg="#f0f4f8")
        btn_f.pack(pady=(10, 15))

        result = {"confirmed": False}

        def on_confirm():
            s1 = s1_var.get().strip()
            ds = ds_var.get().strip()
            if not s1 or not ds:
                messagebox.showwarning("提示", "请填写两个 API Key", parent=dialog)
                return
            try:
                p = save_config(s1, ds)
                result["confirmed"] = True
                self.status_var.set("API Key 已保存。点击「开始评测」运行")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}", parent=dialog)

        def on_skip():
            dialog.destroy()

        tk.Button(btn_f, text="确认保存", command=on_confirm,
                  font=("Microsoft YaHei", 10, "bold"), bg="#3182ce", fg="white",
                  activebackground="#2b6cb0", relief="flat", padx=20, pady=4,
                  cursor="hand2").pack(side="left", padx=(0, 10))
        tk.Button(btn_f, text="取消", command=on_skip,
                  font=("Microsoft YaHei", 10), bg="#edf2f7", fg="#2d3748",
                  relief="flat", padx=16, pady=4, cursor="hand2").pack(side="left")

        self.root.wait_window(dialog)
        return result["confirmed"]

    def _start_eval(self):
        if not self.file_path:
            messagebox.showwarning("提示", "请先选择题目文件")
            return

        self.run_btn.configure(state="disabled", text="评测中...")
        self.select_btn.configure(state="disabled")
        self.settings_btn.configure(state="disabled")
        self.progress.pack(pady=(0, 8))
        self.progress["value"] = 0
        self.status_var.set("正在评测，请稍候...")

        thread = threading.Thread(target=self._run_async, daemon=True)
        thread.start()

    def _run_async(self):
        """在后台线程中执行评测流水线（线程 + asyncio 嵌套模式）
        
        工作流程：
        1. 验证 API 配置
        2. 自动转化文件（PDF/Word -> JSON）
        3. 执行 asyncio.run() 运行异步评测
        4. 打开 HTML 报告
        """
        try:
            from main import auto_convert, run_evaluation

            validate_config(load_config())

            self._update_status("[1/3] 正在转化文件...")
            json_path = auto_convert(self.file_path, max_problems=self.max_var.get())

            self._update_status("[2/3] 正在评测题目...")
            def _on_progress(current, total):
                    pct = int(current / total * 100) if total > 0 else 0
                    self.root.after(0, lambda p=pct: self.progress.configure(value=p))

            html_path = asyncio.run(run_evaluation(json_path, self.concurrency_var.get(), progress_callback=_on_progress))

            self._update_status("[3/3] 评测完成！正在打开报告...")
            if html_path and os.path.exists(html_path):
                webbrowser.open(f"file:///{html_path.replace(os.sep, '/')}")

            self.root.after(0, lambda: self._on_done(True, "评测完成！报告已打开。"))

        except ConfigError as e:
            self.root.after(0, lambda: self._on_done(False, str(e)))
            return
        except Exception as e:
            self.root.after(0, lambda: self._on_done(False, str(e)))

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def _on_done(self, success, msg):
        self.progress["value"] = 0
        self.progress.pack_forget()
        self.run_btn.configure(state="normal", text="开始评测")
        self.select_btn.configure(state="normal")
        self.settings_btn.configure(state="normal")
        if success:
            self.status_var.set(msg)
            messagebox.showinfo("完成", "评测完成！\n\nHTML 报告已在浏览器中打开。")
        else:
            self.status_var.set(f"失败: {msg}")
            messagebox.showerror("错误", f"评测失败:\n{msg}")

    def run(self):
        try:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except ImportError:
            self.status_var.set('就绪 - 拖放功能未启用 (pip install tkinterdnd2)')

        self.root.mainloop()

    def _on_drop(self, event):
        path = event.data.strip()
        path = path.strip("{}").strip('"').strip("'")
        if os.path.isfile(path):
            self._set_file(path)


def main():
    launcher = EvalLauncher()
    launcher.run()


if __name__ == "__main__":
    main()
