"""
数学智能体评测器 – GUI 启动器
===============================
功能概述：
- 支持拖入或选择 PDF / Word / JSON / CSV 文件，一键评测
- 题库管理：创建题库、导入题目、随机选题、AI 质量审核、答案文档导入匹配

使用方式：
    python 测试工具/launcher.py       # 带控制台窗口启动
    pythonw 测试工具/launcher.py      # 无控制台窗口（推荐）
"""

# ===== 标准库导入 =====
import asyncio       # 异步编程支持（用于评测流水线）
import json          # JSON 数据处理
import os            # 文件路径操作
import sys           # 系统路径与参数
import threading     # 多线程（GUI 后台任务不卡界面）
import tkinter as tk # GUI 框架
from tkinter import filedialog, messagebox, ttk  # GUI 组件
import webbrowser    # 自动打开浏览器查看报告

# ===== 项目路径配置 =====
# 将项目根目录和各子目录加入 Python 搜索路径，确保模块导入正常
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "测试工具"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "转化工具"))

# ===== Lean 4 环境配置 =====
# 确保 elan bin 目录在 PATH 中，以便 lake/lean 命令可用
ELAN_BIN = os.path.join(os.path.expanduser("~"), ".elan", "bin")
if os.path.isdir(ELAN_BIN) and ELAN_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = ELAN_BIN + os.pathsep + os.environ.get("PATH", "")

# ===== 项目模块导入 =====
from config import has_config, load_config, save_config, reset_config, ConfigError, validate_config
from question_bank import QuestionBankDB, get_db
from models import Problem


# ==================== 题库管理面板 ====================
# 功能：创建/删除题库、导入题目、手动添加、AI 质量审核、导入答案文档、随机选题评测

class QuestionBankPanel(ttk.Frame):
    """题库管理选项卡 — 提供题库 CRUD + 评测入口的完整 GUI"""

    def __init__(self, parent, launcher):
        """初始化题库管理面板：构建所有 UI 控件并绑定事件"""
        super().__init__(parent)
        self.launcher = launcher          # 引用主启动器（用于访问根窗口和状态栏）
        self._db = None                   # 延迟加载的数据库单例
        self._eval_running = False        # 评测运行标志（防止重复点击）
        self._audit_running = False       # AI 审核运行标志
        self._import_running = False      # 答案导入运行标志

        # 第一行：题库选择下拉框 + 刷新 + 新建/删除按钮
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

        # 第二行：统计信息标签（显示题目数量、领域分布、答案覆盖率）
        row2 = ttk.Frame(self)
        row2.pack(fill="x", padx=15, pady=(0, 8))
        self.stats_var = tk.StringVar(value="题库统计: —")
        ttk.Label(row2, textvariable=self.stats_var, font=("Microsoft YaHei", 9),
                  foreground="#4a5568").pack(anchor="w")

        # 第三行：操作按钮组（导入题目、手动添加、AI 审核、导入答案）
        row3 = ttk.Frame(self)
        row3.pack(fill="x", padx=15, pady=(0, 8))

        ttk.Button(row3, text="📂 从文件导入题目", command=self._import_from_file,
                   width=18).pack(side="left", padx=(0, 8))
        ttk.Button(row3, text="✏️ 手动添加题目", command=self._manual_add,
                   width=18).pack(side="left", padx=(0, 8))
        self.audit_btn = ttk.Button(row3, text="🔍 AI质量审核", command=self._start_audit_quality,
                                     width=14)
        self.audit_btn.pack(side="left", padx=(0, 8))

        self.import_answer_btn = ttk.Button(row3, text="📥 导入答案", command=self._import_answers,
                                            width=14)
        self.import_answer_btn.pack(side="left")

        # 第四行：随机选题评测区域（选题数量 + 领域筛选 + 评测按钮）
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

        # 题目列表（Treeview 表格 — 显示 ID/领域/题干预览，支持右键删除）
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

        # 右键菜单（选中题目后可删除）
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="删除此题目", command=self._delete_selected_problem)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # 底部状态栏（显示操作反馈信息）
        self.bank_status_var = tk.StringVar(value="就绪 — 请选择一个题库")
        ttk.Label(self, textvariable=self.bank_status_var, font=("Microsoft YaHei", 9),
                  foreground="#718096").pack(anchor="w", padx=15, pady=(0, 5))

        self._refresh_banks()

    @property
    def db(self):
        """延迟加载数据库单例（首次访问时才创建连接）"""
        if self._db is None:
            from question_bank import get_db
            self._db = get_db()
        return self._db

    def _refresh_banks(self):
        """刷新题库下拉列表：重新从数据库读取题库名称，并更新统计信息"""
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
        """题库下拉框切换事件：重新加载统计和题目列表"""
        self._update_stats_and_list()

    def _update_stats_and_list(self):
        """更新题库统计栏 + 题目列表 + 答案覆盖率（核心刷新方法）"""
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

        # 获取答案映射覆盖率
        stats = self.db.get_answer_mapping_stats(bank)
        coverage_rate = stats.get("coverage_rate", 0) if stats else 0

        self.stats_var.set(
            f"题库「{bank}」: 共 {total} 题 | 领域: {domain_str or '无'} | "
            f"答案覆盖率: {coverage_rate:.1f}%"
        )

        # 更新领域筛选下拉
        self.domain_combo["values"] = ["全部"] + domains
        if self.domain_var.get() not in ("全部", *domains):
            self.domain_var.set("全部")

        # 更新题目列表
        self._refresh_tree(bank)

    def _refresh_tree(self, bank_name: str):
        """从数据库加载指定题库的所有题目，填充到 Treeview 表格中"""
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
        """清空 Treeview 表格所有行"""
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _on_tree_right_click(self, event):
        """Treeview 右键事件：选中当前行并弹出上下文菜单"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)

    def _delete_selected_problem(self):
        """删除 Treeview 中选中的题目（需二次确认）"""
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
        """根据输入框内容创建新题库（名称不能为空且不能重复）"""
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
        """删除当前选中的题库及其所有题目（不可恢复，需二次确认）"""
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择要删除的题库")
            return
        if messagebox.askyesno("确认删除", f"确定要删除题库「{bank}」及其所有题目吗？\n此操作不可恢复！"):
            self.db.delete_bank(bank)
            self._refresh_banks()
            self.bank_status_var.set(f"题库「{bank}」已删除")

    def _import_from_file(self):
        """从 JSON/CSV/Word/PDF/PPT/Markdown/Excel 文件批量导入题目到当前题库"""
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择或创建一个题库")
            return

        path = filedialog.askopenfilename(
            title="选择题目文件导入到题库",
            filetypes=[
                ("所有支持格式", "*.json;*.csv;*.docx;*.pdf;*.pptx;*.ppt;*.md;*.xlsx"),
                ("JSON 文件", "*.json"),
                ("CSV 文件", "*.csv"),
                ("Word 文档", "*.docx"),
                ("PDF 文件", "*.pdf"),
                ("PowerPoint 演示文稿", "*.pptx;*.ppt"),
                ("Markdown 文件", "*.md"),
                ("Excel 工作簿", "*.xlsx"),
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
        """打开手动添加题目对话框（弹窗表单：ID/题干/领域/答案）"""
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
        """启动题库随机选题评测：校验参数 → 检查 API → 启动后台线程"""
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
        """后台线程：调用 main.run_evaluation_from_bank 执行完整评测流水线"""
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
        """启动 AI 质量审核：校验配置 → 确认对话框 → 启动后台线程调用 DeepSeek 审核"""
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
        """后台线程：分批调用 DeepSeek 审核题目质量（删除无效/优化题干/补全新题）"""
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
                f"优化题干: {result.get('optimized_count', 0)}, "
                f"删除无效: {result['deleted_count']}, "
                f"补全新题: {result['added_count']}"))

            summary = (
                f"题库「{bank_name}」AI 质量审核完成！\n\n"
                f"总审核: {result['total_audited']} 题\n"
                f"保留有效: {result['valid_count']} 题\n"
                f"优化题干: {result.get('optimized_count', 0)} 题\n"
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

    # ---------- 答案导入 ----------

    def _import_answers(self):
        """选择答案文档（PPT/Word/TXT/PDF/Markdown/CSV/Excel/JSON）→ 提取+匹配+入库"""
        bank = self.bank_var.get()
        if not bank:
            messagebox.showwarning("提示", "请先选择或创建一个题库")
            return

        if self._import_running:
            messagebox.showinfo("提示", "答案导入正在进行中，请稍候")
            return

        path = filedialog.askopenfilename(
            title=f"选择答案文档导入到题库「{bank}」",
            filetypes=[
                ("所有支持格式",
                 "*.pptx;*.ppt;*.docx;*.txt;*.md;*.pdf;*.csv;*.xlsx;*.json"),
                ("PowerPoint 演示文稿", "*.pptx;*.ppt"),
                ("Word 文档", "*.docx"),
                ("文本文件", "*.txt"),
                ("Markdown 文件", "*.md"),
                ("PDF 文件", "*.pdf"),
                ("CSV 文件", "*.csv"),
                ("Excel 工作簿", "*.xlsx"),
                ("JSON 文件", "*.json"),
            ]
        )
        if not path:
            return

        self._import_running = True
        self.import_answer_btn.configure(state="disabled", text="导入中...")
        self.bank_status_var.set(f"正在导入答案文档并智能匹配到题库「{bank}」...")

        thread = threading.Thread(target=self._run_import_answers_async,
                                  args=(bank, path), daemon=True)
        thread.start()

    def _run_import_answers_async(self, bank_name, file_path):
        """后台线程：调用 db.import_answers_from_file 完成完整答案导入流程"""
        try:
            def on_progress(current, total, message):
                self.launcher.root.after(0, lambda: self.bank_status_var.set(
                    f"答案导入: {message} ({current}/{total})"))

            result = self.db.import_answers_from_file(
                file_path, bank_name,
                batch_size=15,
                progress_callback=on_progress,
            )

            self.launcher.root.after(0, lambda: self._on_import_done(bank_name, result))
        except Exception as e:
            self.launcher.root.after(0, lambda: self.bank_status_var.set(f"答案导入失败: {e}"))
            self.launcher.root.after(0, lambda: messagebox.showerror("导入失败", str(e)))
            self.launcher.root.after(0, lambda: self.import_answer_btn.configure(
                state="normal", text="📥 导入答案"))
            self._import_running = False

    def _on_import_done(self, bank_name, result):
        """导入完成后：恢复按钮状态 → 刷新统计 → 弹窗展示结果摘要"""
        self._import_running = False
        self.import_answer_btn.configure(state="normal", text="📥 导入答案")

        self._update_stats_and_list()

        self.bank_status_var.set(
            f"答案导入完成！提取 {result.get('extracted_count', 0)} 条, "
            f"匹配 {result.get('matched_count', 0)} 条, "
            f"入库 {result.get('imported_count', 0)} 条, "
            f"覆盖率 {result.get('coverage_rate', 0):.1f}%")

        # 构建摘要信息
        errors = result.get("errors", [])
        summary = (
            f"答案文档导入完成 — 题库「{bank_name}」\n\n"
            f"提取答案对: {result.get('extracted_count', 0)} 条\n"
            f"语义匹配成功: {result.get('matched_count', 0)} 条\n"
            f"已写入映射表: {result.get('imported_count', 0)} 条\n"
            f"题库覆盖率: {result.get('coverage_rate', 0):.1f}%\n"
            f"耗时: {result.get('latency', 0):.1f} 秒\n"
            f"Token 消耗: {result.get('tokens_used', 0)}"
        )
        if errors:
            summary += f"\n\n⚠ 警告 ({len(errors)} 条):\n" + "\n".join(errors[:5])

        messagebox.showinfo("答案导入完成", summary)


# ==================== 题库浏览器面板 ====================
# 功能：浏览题库题目详情，支持搜索、分页、查看/编辑/删除

class BankBrowserPanel(ttk.Frame):
    """题库浏览器 — 直接浏览数据库中各题库的题目，支持搜索、分页、查看详情"""

    def __init__(self, parent, launcher):
        """初始化浏览器面板：构建搜索栏、分页控件、Treeview 表格"""
        super().__init__(parent)
        self.launcher = launcher
        self._current_bank = None   # 当前选中的题库名称
        self._all_problems = []     # 当前搜索结果的全量数据（用于分页）
        self._page = 0              # 当前页码（从 0 开始）

        # 第一行：题库选择 + 刷新 + 统计信息
        row1 = ttk.Frame(self)
        row1.pack(fill="x", padx=15, pady=(12, 8))

        ttk.Label(row1, text="选择题库:", font=("Microsoft YaHei", 11, "bold")).pack(side="left")
        self.bank_combo = ttk.Combobox(row1, state="readonly", font=("Microsoft YaHei", 11), width=16)
        self.bank_combo.pack(side="left", padx=(6, 12))
        self.bank_combo.bind("<<ComboboxSelected>>", self._on_bank_changed)
        ttk.Button(row1, text="🔄 刷新", command=self._refresh_banks, width=7).pack(side="left")

        # 统计信息标签（显示在题库选择右侧）
        self.stats_var = tk.StringVar(value="")
        ttk.Label(row1, textvariable=self.stats_var, font=("Microsoft YaHei", 9),
                  foreground="#4a5568").pack(side="left", padx=(12, 0))

        # 第二行：搜索框 + 分页控制（每页数量、上页/下页按钮）
        search_row = ttk.Frame(self)
        search_row.pack(fill="x", padx=15, pady=(0, 6))

        ttk.Label(search_row, text="搜索:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, font=("Microsoft YaHei", 10), width=22)
        self.search_entry.pack(side="left", padx=(4, 6))
        ttk.Button(search_row, text="搜索", command=self._do_search, width=6).pack(side="left", padx=(0, 4))
        ttk.Button(search_row, text="清除", command=self._clear_search, width=6).pack(side="left", padx=(0, 16))
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        ttk.Label(search_row, text="每页:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.page_size_var = tk.IntVar(value=30)
        ttk.Spinbox(search_row, from_=10, to=200, width=4, textvariable=self.page_size_var,
                    font=("Microsoft YaHei", 10), command=self._reload_list).pack(side="left", padx=(4, 12))

        ttk.Button(search_row, text="◀ 上页", command=self._prev_page, width=7).pack(side="left")
        ttk.Button(search_row, text="下页 ▶", command=self._next_page, width=7).pack(side="left", padx=(0, 8))
        self.page_label_var = tk.StringVar(value="—")
        ttk.Label(search_row, textvariable=self.page_label_var, font=("Consolas", 9),
                  foreground="#666").pack(side="left")

        # 第三行：领域筛选下拉框
        filter_row = ttk.Frame(self)
        filter_row.pack(fill="x", padx=15, pady=(0, 6))

        ttk.Label(filter_row, text="领域:", font=("Microsoft YaHei", 10)).pack(side="left")
        self.domain_var = tk.StringVar(value="(全部)")
        self.domain_combo = ttk.Combobox(filter_row, textvariable=self.domain_var, state="readonly",
                                          font=("Microsoft YaHei", 10), width=14)
        self.domain_combo.pack(side="left", padx=(4, 12))
        self.domain_combo.bind("<<ComboboxSelected>>", lambda e: self._reload_list())

        # ---- 题目表格（双击查看详情，右键操作菜单）----
        list_frame = ttk.LabelFrame(self, text="题目列表（双击查看详情 / 右键操作）", padding=(5, 3))
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        columns = ("#", "ID", "domain", "question_preview")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                                  selectmode="browse", height=12)
        self.tree.heading("#", text="#", anchor="center")
        self.tree.heading("ID", text="ID", anchor="w")
        self.tree.heading("domain", text="领域", anchor="w")
        self.tree.heading("question_preview", text="题干内容", anchor="w")
        self.tree.column("#", width=45, stretch=False)
        self.tree.column("ID", width=110, minwidth=70)
        self.tree.column("domain", width=80, minwidth=60)
        self.tree.column("question_preview", width=400, minwidth=150)

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self.tree.bind("<Double-Button-1>", lambda e: self._view_detail())
        self.tree.bind("<Button-3>", self._on_right_click)

        # 右键菜单（查看详情 / 编辑 / 删除）
        self.ctx_menu = tk.Menu(self.tree, tearoff=0)
        self.ctx_menu.add_command(label="📋 查看详情", command=self._view_detail)
        self.ctx_menu.add_command(label="📝 编辑题目", command=self._edit_problem)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="🗑 删除此题目", command=self._delete_problem)

        # 状态栏（显示操作反馈）
        self.status_var = tk.StringVar(value="就绪 — 请选择题库开始浏览")
        ttk.Label(self, textvariable=self.status_var, font=("Microsoft YaHei", 9),
                  foreground="#718096").pack(anchor="w", padx=15, pady=(0, 8))

        self._init_banks()

    @property
    def db(self):
        """延迟加载数据库单例"""
        from question_bank import get_db
        return get_db()

    # ===== 题库切换 =====

    def _init_banks(self):
        """初始化题库下拉列表：启动时调用，自动加载第一个题库"""
        banks = self.db.list_banks()
        names = [b["name"] for b in banks]
        self.bank_combo["values"] = names
        if names:
            self.bank_combo.set(names[0])
            self._load_bank(names[0])
        else:
            self.stats_var.set("(暂无题库)")
            self.status_var.set("暂无题库 — 请在「题库评测」选项卡中创建或导入")

    def _refresh_banks(self):
        """刷新题库列表（保持当前选中项不变）"""
        old = self.bank_combo.get().strip()
        banks = self.db.list_banks()
        names = [b["name"] for b in banks]
        self.bank_combo["values"] = names
        if names:
            if old and old in names:
                self.bank_combo.set(old)
            else:
                self.bank_combo.set(names[0])
            self._on_bank_changed()
        else:
            self.bank_combo.set("")
            self.stats_var.set("(暂无题库)")
            self._clear_tree()
            self.status_var.set("暂无题库")

    def _on_bank_changed(self, event=None):
        """切换题库事件：加载新题库的题目数据"""
        bank = self.bank_combo.get()
        if bank:
            self._load_bank(bank)

    def _load_bank(self, bank_name: str):
        """加载指定题库：重置搜索和分页 → 更新统计 → 刷新题目列表"""
        self._current_bank = bank_name
        self._page = 0
        self.search_var.set("")
        self.domain_var.set("(全部)")

        total = self.db.get_problem_count(bank_name)
        domains = self.db.get_domains(bank_name)
        self.domain_combo["values"] = ["(全部)"] + domains

        d_str = ", ".join(domains[:6])
        if len(domains) > 6:
            d_str += f"…共{len(domains)}"

        self.stats_var.set(f"共 {total} 题 | 领域: {d_str or '未分类'}")
        self._reload_list()
        self.status_var.set(f"已加载: 「{bank_name}」({total} 题)")

    # ===== 题目列表加载与分页 =====

    def _fetch_problems(self) -> list[Problem]:
        """根据搜索关键词和领域筛选获取题目列表"""
        if not self._current_bank:
            return []

        keyword = self.search_var.get().strip()
        domain = self.domain_var.get()
        domain = None if domain == "(全部)" else domain

        if keyword:
            results = self.db.search_problems(self._current_bank, keyword)
            if domain:
                results = [p for p in results if p.domain == domain]
            return results
        else:
            return self.db.get_all_problems(self._current_bank, domain=domain)

    def _reload_list(self):
        """重新加载数据并按当前页码分页显示到 Treeview 中"""
        self._clear_tree()
        self._all_problems = self._fetch_problems()
        total = len(self._all_problems)
        ps = self.page_size_var.get()
        tp = max(1, (total + ps - 1) // ps) if total > 0 else 1
        self._page = max(0, min(self._page, tp - 1))

        start = self._page * ps
        items = self._all_problems[start:start + ps]

        seen = set()
        for i, p in enumerate(items):
            iid = p.id if p.id else f"_auto_{i}"
            if iid in seen:
                iid = f"{iid}_{i}"
            seen.add(iid)
            row_no = start + i + 1
            self.tree.insert("", "end", iid=iid,
                             values=(row_no, p.id, p.domain or "",
                                     p.question[:80] + ("…" if len(p.question) > 80 else "")))

        kw_info = ""
        if self.search_var.get().strip():
            kw_info = f" | 搜索: 「{self.search_var.get().strip()}」"
        dom_info = ""
        if self.domain_var.get() != "(全部)":
            dom_info = f" | 领域: {self.domain_var.get()}"

        self.page_label_var.set(f"第 {self._page + 1}/{tp} 页 ({total} 题{kw_info}{dom_info})")
        self.status_var.set(f"「{self._current_bank}」— 显示第 {start+1}-{min(start+ps, total)} 题，共 {total} 题")

    def _clear_tree(self):
        for c in self.tree.get_children():
            self.tree.delete(c)

    # ===== 搜索 & 分页操作 =====

    def _do_search(self):
        """执行搜索（重置页码为 0 后刷新）"""
        self._page = 0
        self._reload_list()

    def _clear_search(self):
        """清空搜索框并重置页码"""
        self.search_var.set("")
        self._page = 0
        self._reload_list()

    def _prev_page(self):
        """上一页（若不在首页）"""
        if self._page > 0:
            self._page -= 1
            self._reload_list()

    def _next_page(self):
        """下一页（若不在末页）"""
        ps = self.page_size_var.get()
        tp = max(1, (len(self._all_problems) + ps - 1) // ps) if self._all_problems else 1
        if self._page < tp - 1:
            self._page += 1
            self._reload_list()

    # ===== 操作（查看/编辑/删除） =====

    def _get_sel_problem(self) -> Problem | None:
        """获取 Treeview 当前选中的题目对象（返回 None 表示无选中）"""
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        pid = vals[1] if len(vals) >= 2 else sel[0]
        for p in self._all_problems:
            if p.id == pid:
                return p
        return None

    def _on_right_click(self, event):
        """Treeview 右键事件：选中行并弹出上下文菜单"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.ctx_menu.post(event.x_root, event.y_root)

    def _view_detail(self):
        """打开题目详情弹窗（显示题干 + 参考答案的只读视图）"""
        p = self._get_sel_problem()
        if not p:
            return

        dlg = tk.Toplevel(self)
        dlg.title(f"题目详情 — {p.id}")
        dlg.geometry("720x550")
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.configure(bg="#f0f4f8")
        dlg.update_idletasks()
        w, h = 360, 275
        dlg.geometry(f"+{dlg.winfo_screenwidth()//2-w}+{dlg.winfo_screenheight()//2-h}")

        # 标题栏
        hdr = ttk.Frame(dlg); hdr.pack(fill="x", padx=15, pady=(12, 6))
        ttk.Label(hdr, text=f"题目 ID: {p.id}", font=("Microsoft YaHei", 12, "bold"),
                  foreground="#1a365d").pack(side="left")
        if p.domain:
            ttk.Label(hdr, text=f"  [{p.domain}]", font=("Microsoft YaHei", 10),
                      foreground="#2b6cb0").pack(side="left")

        # 题干
        qf = ttk.LabelFrame(dlg, text="题干", padding=(8, 5))
        qf.pack(fill="both", expand=True, padx=12, pady=(0, 5))
        qt = tk.Text(qf, font=("Microsoft YaHei UI", 10), wrap="word", bd=0, bg="#fffaf0", padx=10, pady=8)
        qt.insert("1.0", p.question); qt.configure(state="disabled")
        qs = ttk.Scrollbar(qf, orient="vertical", command=qt.yview); qt.configure(yscrollcommand=qs.set)
        qt.pack(side="left", fill="both", expand=True); qs.pack(side="right", fill="y")

        # 参考答案
        if p.reference_answer:
            af = ttk.LabelFrame(dlg, text="参考答案", padding=(8, 5)); af.pack(fill="both", expand=True, padx=12, pady=(0, 6))
            at = tk.Text(af, font=("Microsoft YaHei UI", 10), wrap="word", bd=0, bg="#f0fff0", padx=10, pady=8)
            at.insert("1.0", p.reference_answer); at.configure(state="disabled")
            asc = ttk.Scrollbar(af, orient="vertical", command=at.yview); at.configure(yscrollcommand=asc.set)
            at.pack(side="left", fill="both", expand=True); asc.pack(side="right", fill="y")

        btns = ttk.Frame(dlg)
        btns.pack(pady=(0, 10))
        ttk.Button(btns, text="编辑此题目", command=lambda: [dlg.destroy(), self._edit_problem()], width=14).pack(side="left", padx=4)
        ttk.Button(btns, text="关闭", command=dlg.destroy, width=10).pack(side="left", padx=4)

    def _edit_problem(self):
        """打开编辑题目对话框（修改题干/答案/领域后保存到数据库）"""
        p = self._get_sel_problem()
        if not p:
            return

        dlg = tk.Toplevel(self); dlg.title(f"编辑题目 — {p.id}")
        dlg.geometry("600x480"); dlg.resizable(True, True); dlg.transient(self); dlg.grab_set()
        dlg.configure(bg="#f0f4f8"); dlg.update_idletasks()
        x = dlg.winfo_screenwidth() // 2 - 300; y = dlg.winfo_screenheight() // 2 - 240
        dlg.geometry(f"+{x}+{y}")

        entries = {}
        fields = [
            ("题目 ID:", "id", False, p.id),
            ("领域:", "domain", False, p.domain or ""),
            ("题干:", "question", True, p.question),
            ("参考答案:", "answer", True, p.reference_answer or ""),
        ]
        for label_text, key, multiline, default in fields:
            frm = ttk.Frame(dlg); frm.pack(fill="x", padx=15, pady=4)
            ttk.Label(frm, text=label_text, font=("Microsoft YaHei", 10), width=10).pack(side="left")
            if multiline:
                ent = tk.Text(frm, font=("Microsoft YaHei", 10), height=6 if key == "question" else 4,
                              wrap="word", bd=1, relief="solid")
                ent.insert("1.0", default)
                ent.pack(side="left", fill="both", expand=True)
            else:
                ent = ttk.Entry(frm, font=("Microsoft YaHei", 10), width=40)
                ent.insert(0, default)
                ent.pack(side="left", fill="x", expand=True)
            entries[key] = ent
            # 题目 ID 不允许修改，禁用输入
            if key == "id":
                ent.configure(state="disabled")  # type: ignore[attr-defined]

        def do_save():
            new_q = entries["question"].get("1.0", "end-1c").strip()
            new_a = entries["answer"].get("1.0", "end-1c").strip()
            new_d = entries["domain"].get().strip()
            if not new_q:
                messagebox.showwarning("提示", "题干不能为空", parent=dlg); return
            try:
                self.db.update_problem(
                    p.id, self._current_bank,
                    question=new_q,
                    reference_answer=new_a or None,
                    domain=new_d or None,
                )
                self._reload_list()
                self.status_var.set(f"题目 {p.id} 已更新")
                dlg.destroy()
            except Exception as ex:
                messagebox.showerror("保存失败", str(ex), parent=dlg)

        btn_f = ttk.Frame(dlg); btn_f.pack(pady=(10, 12))
        ttk.Button(btn_f, text="💾 保存修改", command=do_save, width=14).pack(side="left", padx=4)
        ttk.Button(btn_f, text="取消", command=dlg.destroy, width=10).pack(side="left", padx=4)

    def _delete_problem(self):
        """删除选中的题目（需二次确认，删除后自动刷新列表和统计）"""
        p = self._get_sel_problem()
        if not p: return
        if not self._current_bank: return
        if messagebox.askyesno("确认删除", f"确定要从题库「{self._current_bank}」中删除题目\n\n  {p.id}\n\n吗？"):
            self.db.remove_problem(p.id, self._current_bank)
            self._reload_list()
            self._init_banks()  # 可能需要刷新统计
            self.status_var.set(f"已删除题目: {p.id}")


# ==================== 主启动器 ====================
# 功能：构建整个 GUI 应用窗口，管理三个选项卡（文件评测/题库评测/题库浏览器）

class EvalLauncher:
    """主应用类：创建根窗口、构建选项卡界面、管理全局状态"""

    def __init__(self):
        """初始化主窗口：尝试加载拖放支持 → 构建所有 UI 组件"""
        try:
            # 尝试加载 tkinterdnd2 拖放库（可选依赖，没有则降级为普通 Tk）
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

        # ---- 标题栏 ----

        title_frame = tk.Frame(self.root, bg="#f0f4f8")
        title_frame.pack(pady=(15, 5))

        # ---- Notebook 选项卡（三个标签页） ----
        tk.Label(
            title_frame, text="数学智能体评测器",
            font=("Microsoft YaHei", 18, "bold"), fg="#1a365d", bg="#f0f4f8"
        ).pack()
        tk.Label(
            title_frame, text="Intern-S1 + DeepSeek 自动评测流水线",
            font=("Microsoft YaHei", 9), fg="#718096", bg="#f0f4f8"
        ).pack()

        # ---- Tab 1: 文件评测（拖放/选择文件 → 一键评测） ----
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(5, 0))

        self.file_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.file_tab, text="📄 文件评测")

        # 拖放区域（支持拖入文件或点击按钮选择）
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

        # 文件路径显示 + 设置行（并发数/题目上限）
        self.path_var = tk.StringVar(value="未选择文件")
        path_label = tk.Label(
            self.file_tab, textvariable=self.path_var,
            font=("Consolas", 9), fg="#4a5568", bg="#f0f4f8",
            anchor="w", wraplength=500
        )
        path_label.pack(padx=15, pady=(2, 8), fill="x")

        # 评测参数设置行（并发数、题目上限）
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

        # 操作按钮行（选择文件 / 开始评测 / 设置 API Key / 清理结果）
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

        # ---- Tab 2: 题库评测 ----
        self.bank_panel = QuestionBankPanel(self.notebook, launcher=self)
        self.notebook.add(self.bank_panel, text="📚 题库评测")

        # ---- Tab 3: 题库浏览器 ----
        self.browser_panel = BankBrowserPanel(self.notebook, launcher=self)
        self.notebook.add(self.browser_panel, text="📂 题库浏览器")

        # 底部全局状态栏
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
        """拖拽进入：高亮拖放区域"""
        self.drop_frame.configure(bg="#ebf8ff")
        self.drop_label.configure(bg="#ebf8ff")

    def _on_drag_leave(self, event):
        """拖拽离开：恢复拖放区域默认颜色"""
        self.drop_frame.configure(bg="white")
        self.drop_label.configure(bg="white")

    def _select_file(self):
        """弹出文件选择对话框（支持 PDF/Word/JSON/CSV）"""
        path = filedialog.askopenfilename(
            title="选择题目文件",
            filetypes=[
                ("所有支持格式",
                 "*.pdf;*.docx;*.json;*.csv;*.pptx;*.ppt;*.md;*.xlsx"),
                ("PDF 文件", "*.pdf"),
                ("Word 文档", "*.docx"),
                ("JSON 文件", "*.json"),
                ("CSV 文件", "*.csv"),
                ("PowerPoint 演示文稿", "*.pptx;*.ppt"),
                ("Markdown 文件", "*.md"),
                ("Excel 工作簿", "*.xlsx"),
            ]
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        """设置待评测文件路径并更新 UI 状态"""
        self.file_path = path
        basename = os.path.basename(path)
        self.path_var.set(basename)
        self.drop_label.configure(
            text=f"已选择: {basename}", fg="#2d3748"
        )
        self.run_btn.configure(state="normal")
        self.status_var.set(f"已选择: {basename} - 点击「开始评测」运行")

    def _clear_results(self):
        """清理所有评测结果（HTML 报告 / JSON 数据 / 临时题目文件）"""
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
        """弹窗配置 API Key（支持 Intern-S1 + DeepSeek 两个服务）"""
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
        # 对话框关闭后返回，result 字典仅用于内部回调

    def _start_eval(self):
        """开始文件评测：禁用按钮 → 启动后台评测线程"""
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
        """
        后台线程执行完整评测流水线：
        1. 验证 API 配置是否完整
        2. 自动转化文件格式（PDF/Word → JSON）
        3. 调用 asyncio.run() 执行并发异步评测
        4. 自动打开生成的 HTML 报告
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

    def _update_status(self, text: str):
        """线程安全的状态更新（通过 root.after 回到主线程）"""
        self.root.after(0, lambda: self.status_var.set(text))

    def _on_done(self, success, msg):
        """评测完成回调：恢复按钮状态 → 显示结果或错误信息"""
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
        """启动应用主循环：注册拖放事件（若可用）→ 进入 tkinter mainloop"""
        if getattr(self, "_dnd_available", False):
            try:
                from tkinterdnd2 import DND_FILES
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind("<<Drop>>", self._on_drop)
            except (AttributeError, ImportError, tk.TclError):
                # 部分环境下TkinterDnD的root窗口不支持drop_target_register
                self._dnd_available = False

        if not getattr(self, "_dnd_available", False):
            self.status_var.set('就绪 - 拖放功能未启用')

        self.root.mainloop()

    def _on_drop(self, event):
        """处理文件拖放事件：解析路径 → 调用 _set_file"""
        path = event.data.strip()
        path = path.strip("{}").strip('"').strip("'")
        if os.path.isfile(path):
            self._set_file(path)


def main():
    """应用入口：创建主启动器实例并运行"""
    launcher = EvalLauncher()
    launcher.run()


if __name__ == "__main__":
    main()
