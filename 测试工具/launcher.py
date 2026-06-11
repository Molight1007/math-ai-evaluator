"""
数学智能体评测器 — GUI 启动器
支持拖入或选择 PDF / Word / JSON / CSV 文件，一键评测。

用法:
    python 测试工具/launcher.py
    pythonw 测试工具/launcher.py   （无控制台窗口）
"""
import asyncio
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

# 确保项目根目录在 path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "测试工具"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "转化工具"))


class EvalLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("数学智能体评测器")
        self.root.geometry("520x420")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f4f8")

        # 图标 / 最小尺寸
        self.root.minsize(460, 380)

        # === 标题 ===
        title_frame = tk.Frame(self.root, bg="#f0f4f8")
        title_frame.pack(pady=(20, 5))
        tk.Label(
            title_frame, text="数学智能体评测器",
            font=("Microsoft YaHei", 18, "bold"), fg="#1a365d", bg="#f0f4f8"
        ).pack()
        tk.Label(
            title_frame, text="Intern-S1 + DeepSeek 自动评测流水线",
            font=("Microsoft YaHei", 9), fg="#718096", bg="#f0f4f8"
        ).pack()

        # === 拖放区域 ===
        self.drop_frame = tk.Frame(
            self.root, bg="white", bd=2, relief="groove",
            highlightbackground="#cbd5e0", highlightthickness=1
        )
        self.drop_frame.pack(padx=30, pady=(15, 5), fill="both", expand=True)

        self.drop_label = tk.Label(
            self.drop_frame,
            text="拖放文件到此处\n或点击下方按钮选择",
            font=("Microsoft YaHei", 11), fg="#a0aec0", bg="white",
            justify="center"
        )
        self.drop_label.pack(expand=True)

        # 拖放绑定
        self.drop_frame.bind("<Enter>", self._on_drag_enter)
        self.drop_frame.bind("<Leave>", self._on_drag_leave)
        self.drop_label.bind("<Enter>", self._on_drag_enter)
        self.drop_label.bind("<Leave>", self._on_drag_leave)

        # === 文件路径显示 ===
        self.path_var = tk.StringVar(value="未选择文件")
        path_label = tk.Label(
            self.root, textvariable=self.path_var,
            font=("Consolas", 9), fg="#4a5568", bg="#f0f4f8",
            anchor="w", wraplength=460
        )
        path_label.pack(padx=30, pady=(2, 8), fill="x")

        # === 设置区 ===
        settings_frame = tk.Frame(self.root, bg="#f0f4f8")
        settings_frame.pack(padx=30, pady=(0, 5), fill="x")

        tk.Label(
            settings_frame, text="并发数:", font=("Microsoft YaHei", 10),
            bg="#f0f4f8", fg="#4a5568"
        ).pack(side="left")
        self.concurrency_var = tk.IntVar(value=3)
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

        # === 按钮区 ===
        btn_frame = tk.Frame(self.root, bg="#f0f4f8")
        btn_frame.pack(padx=30, pady=(5, 15), fill="x")

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
        self.run_btn.pack(side="left")

        # === 状态栏 ===
        self.status_var = tk.StringVar(value="就绪 — 请选择题目文件")
        status_label = tk.Label(
            self.root, textvariable=self.status_var,
            font=("Microsoft YaHei", 9), fg="#718096", bg="#edf2f7",
            anchor="w", padx=10, pady=4
        )
        status_label.pack(fill="x", side="bottom")

        # === 进度条 ===
        self.progress = ttk.Progressbar(
            self.root, mode="indeterminate", length=200
        )

        self.file_path = None

    # ---- 拖放 ----
    def _on_drag_enter(self, event):
        self.drop_frame.configure(bg="#ebf8ff")
        self.drop_label.configure(bg="#ebf8ff")

    def _on_drag_leave(self, event):
        self.drop_frame.configure(bg="white")
        self.drop_label.configure(bg="white")

    # ---- 文件选择 ----
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
        self.status_var.set(f"已选择: {basename} — 点击「开始评测」运行")

    # ---- 评测 ----
    def _start_eval(self):
        if not self.file_path:
            messagebox.showwarning("提示", "请先选择题目文件")
            return

        # 禁用按钮
        self.run_btn.configure(state="disabled", text="评测中...")
        self.select_btn.configure(state="disabled")
        self.progress.pack(pady=(0, 8))
        self.progress.start()
        self.status_var.set("正在评测，请稍候...")

        # 后台线程运行
        thread = threading.Thread(target=self._run_async, daemon=True)
        thread.start()

    def _run_async(self):
        """在后台线程中运行 asyncio 评测"""
        try:
            from main import auto_convert, run_evaluation
            from config import load_config

            load_config()

            # Step 1: 转化
            self._update_status("[1/3] 正在转化文件...")
            json_path = auto_convert(self.file_path, max_problems=self.max_var.get())

            # Step 2: 评测
            self._update_status("[2/3] 正在评测题目...")
            html_path = asyncio.run(run_evaluation(json_path, self.concurrency_var.get()))

            # Step 3: 打开报告
            self._update_status("[3/3] 评测完成！正在打开报告...")
            if html_path and os.path.exists(html_path):
                webbrowser.open(f"file:///{html_path.replace(os.sep, '/')}")

            self.root.after(0, lambda: self._on_done(True, "评测完成！报告已打开。"))

        except Exception as e:
            self.root.after(0, lambda: self._on_done(False, str(e)))

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def _on_done(self, success, msg):
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.configure(state="normal", text="开始评测")
        self.select_btn.configure(state="normal")
        if success:
            self.status_var.set(msg)
            messagebox.showinfo("完成", "评测完成！\n\nHTML 报告已在浏览器中打开。")
        else:
            self.status_var.set(f"失败: {msg}")
            messagebox.showerror("错误", f"评测失败:\n{msg}")

    def run(self):
        # Windows 拖放支持
        try:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except ImportError:
            # tkinterdnd2 未安装，不影响基本使用
            pass

        self.root.mainloop()

    def _on_drop(self, event):
        """拖放文件处理"""
        path = event.data.strip()
        # 去掉可能的 {} 包裹和引号
        path = path.strip("{}").strip('"').strip("'")
        if os.path.isfile(path):
            self._set_file(path)


def main():
    launcher = EvalLauncher()
    launcher.run()


if __name__ == "__main__":
    main()
