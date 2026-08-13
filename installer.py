#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作业追踪器 - 图形化安装向导
维护者: Assignment Dashboard 项目贡献者
7步安装流程：欢迎→环境检测→班级与学期→安装与目录→文件类型→分类大脑→安装执行
"""

import os
import sys
import json
import zipfile
import urllib.request
import urllib.error
import tempfile
import subprocess
import traceback
import uuid
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading

import installer_core
from app_meta import APP_NAME, APP_VERSION, APP_PORT

# ============================================================
# 常量配置
# ============================================================

AUTHOR = "项目贡献者"
SUPPORT_URL = "https://github.com/Trip1eY/Assignment_Dashboard/issues/new/choose"

# 嵌入版 Python 下载地址
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip"
PYTHON_EMBED_SIZE_MB = 8  # 约8MB

# 默认安装目录
DEFAULT_INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "作业追踪器")

# 文件类型分组
FILE_TYPE_GROUPS = {
    "办公文档": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"],
    "图片": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
    "压缩包": [".zip", ".rar", ".7z", ".tar", ".gz"]
}

# 需要安装到目标目录的文件列表
INSTALL_FILES = [
    "server.py",
    "app_meta.py",
    "ai_classifier.py",
    "external_ai.py",
    "classifier_features.py",
    "classifier_trainer.py",
    "installer_core.py",
    "restart_helper.py",
    "dashboard.html",
    "dashboard_modern.html",
    "pack.py",
    "repair_update.py",
    "repair_update.bat",
    "更新修复工具.bat",
]

PROTECTED_INSTALL_DIRS = {
    os.path.normcase(os.path.abspath(os.path.expanduser("~"))),
    os.path.normcase(os.path.abspath(os.path.join(os.path.expanduser("~"), "Desktop"))),
    os.path.normcase(os.path.abspath(os.path.join(os.path.expanduser("~"), "Documents"))),
    os.path.normcase(os.path.abspath(os.path.join(os.path.expanduser("~"), "Downloads"))),
    os.path.normcase(os.path.abspath(os.environ.get("ProgramFiles", r"C:\Program Files"))),
    os.path.normcase(os.path.abspath(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))),
    os.path.normcase(os.path.abspath(os.environ.get("WINDIR", r"C:\Windows"))),
}

# PyInstaller 打包时的资源路径
def get_resource_path(relative_path):
    """获取资源文件路径（兼容 PyInstaller 打包和直接运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def _is_drive_root(path):
    drive, tail = os.path.splitdrive(os.path.abspath(path))
    return bool(drive) and tail in ("\\", "/")


# ============================================================
# 安装向导 GUI
# ============================================================

class InstallerWizard:
    """7步安装向导"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION} - 安装向导")
        self.root.geometry("680x620")
        self.root.resizable(True, True)
        self.root.minsize(680, 620)
        
        # 居中窗口
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
        
        # 配色
        self.colors = {
            "bg": "#0f1117",
            "bg_card": "#1a1d2e",
            "bg_input": "#1e2030",
            "border": "#2a2d3e",
            "text": "#e1e4ed",
            "text_secondary": "#8b8fa3",
            "text_muted": "#5a5e72",
            "accent": "#22c55e",
            "accent_hover": "#16a34a",
            "danger": "#ef4444",
            "warning": "#f59e0b",
            "info": "#3b82f6",
        }
        
        self.root.configure(bg=self.colors["bg"])
        
        # 安装状态数据
        self.step = 0  # 当前步骤 0-6
        self.python_ok = False
        self.pip_ok = False
        self.class_name = "课程班级"
        self.install_dir = DEFAULT_INSTALL_DIR
        self.scan_dirs = []  # [(显示路径, 绝对路径)]
        self.data_dir = ""
        self.file_types = [".pdf", ".docx", ".doc"]
        self.create_desktop_bat = True
        self.install_mode = "auto"
        self.detected_mode = "new"
        self.active_semester = ""
        self.class_aliases = []
        self.course_names = []
        self.imported_rule_pack = None
        self.pack_profile = {"name": "", "school": "", "major": "", "grade": "", "semester": ""}
        self.apply_rules_on_upgrade = False
        self.open_brain_after_install = True
        
        # 进度
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="")
        self.install_log = []
        self.install_succeeded = False
        
        # 构建界面
        self._build_ui()
        self._show_step(0)
    
    def _build_ui(self):
        """构建UI框架"""
        # 顶部标题
        title_frame = tk.Frame(self.root, bg=self.colors["bg_card"], height=56)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        
        tk.Label(
            title_frame, 
            text=f"📋 {APP_NAME}",
            font=("Segoe UI", 18, "bold"),
            fg=self.colors["accent"],
            bg=self.colors["bg_card"]
        ).pack(side=tk.LEFT, padx=20, pady=10)
        
        tk.Label(
            title_frame,
            text=f"v{APP_VERSION}",
            font=("Segoe UI", 10),
            fg=self.colors["text_muted"],
            bg=self.colors["bg_card"]
        ).pack(side=tk.LEFT, padx=(0, 20), pady=10)
        
        # 步骤指示器
        self.step_frame = tk.Frame(self.root, bg=self.colors["bg"])
        self.step_frame.pack(fill=tk.X, padx=20, pady=(12, 0))
        
        self.step_labels = []
        self.step_names = ["欢迎", "环境检测", "班级与学期", "安装与目录", "文件类型", "分类大脑", "执行安装"]
        
        for i, name in enumerate(self.step_names):
            lbl = tk.Label(
                self.step_frame,
                text=f"{i+1}. {name}",
                font=("Segoe UI", 9),
                fg=self.colors["text_muted"],
                bg=self.colors["bg"]
            )
            lbl.pack(side=tk.LEFT, padx=4)
            self.step_labels.append(lbl)
        
        # 分隔线
        sep = tk.Frame(self.root, bg=self.colors["border"], height=1)
        sep.pack(fill=tk.X, padx=20, pady=(8, 0))
        
        # 内容区域
        self.content_frame = tk.Frame(self.root, bg=self.colors["bg"])
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)
        
        # 底部按钮
        btn_frame = tk.Frame(self.root, bg=self.colors["bg"])
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 16))
        
        self.btn_back = tk.Button(
            btn_frame, text="← 上一步", 
            command=self._prev_step,
            font=("Segoe UI", 10),
            bg=self.colors["bg_card"], fg=self.colors["text"],
            activebackground=self.colors["border"],
            relief=tk.FLAT, bd=0, padx=16, pady=8,
            cursor="hand2"
        )
        self.btn_back.pack(side=tk.LEFT)
        
        self.btn_next = tk.Button(
            btn_frame, text="下一步 →",
            command=self._next_step,
            font=("Segoe UI", 10, "bold"),
            bg=self.colors["accent"], fg="#000",
            activebackground=self.colors["accent_hover"],
            relief=tk.FLAT, bd=0, padx=20, pady=8,
            cursor="hand2"
        )
        self.btn_next.pack(side=tk.RIGHT)
    
    def _clear_content(self):
        """清空内容区域"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def _update_step_indicator(self):
        """更新步骤指示器样式"""
        for i, lbl in enumerate(self.step_labels):
            if i == self.step:
                lbl.configure(fg=self.colors["accent"], font=("Segoe UI", 9, "bold"))
            elif i < self.step:
                lbl.configure(fg=self.colors["text_secondary"])
            else:
                lbl.configure(fg=self.colors["text_muted"])
    
    def _show_step(self, step):
        """切换到指定步骤"""
        self.step = step
        self._clear_content()
        self._update_step_indicator()
        
        # 更新按钮状态
        if step in (0, 6):
            self.btn_back.configure(state=tk.DISABLED)
        else:
            self.btn_back.configure(state=tk.NORMAL)
        
        if step == 6:
            self.btn_next.configure(text="完成 ✓", state=tk.DISABLED)
        else:
            self.btn_next.configure(text="下一步 →", state=tk.NORMAL)
        
        # 渲染步骤内容
        step_methods = [
            self._step_welcome,
            self._step_env_check,
            self._step_class,
            self._step_dirs,
            self._step_file_types,
            self._step_subjects,
            self._step_install
        ]
        step_methods[step]()
    
    def _next_step(self):
        """下一步"""
        if self.step < 6:
            if not self._capture_current_step():
                return
            # 如果即将进入环境检测页，先显示加载提示
            if self.step + 1 == 1:
                self._show_loading("正在检测系统环境...")
                self.root.after(100, lambda: self._show_step(self.step + 1))
            elif self.detected_mode == "repair" and self.step == 1:
                self._show_step(6)
            else:
                self._show_step(self.step + 1)
        else:
            self.root.quit()

    def _capture_current_step(self):
        """Persist page values before Tk widgets are destroyed."""
        try:
            if self.step == 0 and hasattr(self, "install_mode_var"):
                self.install_mode = self.install_mode_var.get() or "auto"
                self.install_dir = self._ensure_safe_install_dir(
                    self.welcome_install_dir_entry.get().strip() or DEFAULT_INSTALL_DIR
                )
                self.detected_mode = installer_core.detect_install_mode(
                    self.install_dir, self.install_mode
                )
                self._load_existing_install_context(self.install_dir)
            elif self.step == 2:
                self.class_name = self.class_entry.get().strip() or "课程班级"
                self.active_semester = self.semester_entry.get().strip()[:100]
                self.class_aliases = installer_core._clean_list(
                    self.class_aliases_entry.get(), 30, 80
                )
            elif self.step == 3:
                self.install_dir = self._ensure_safe_install_dir(
                    self.install_dir_entry.get().strip() or DEFAULT_INSTALL_DIR
                )
                self.scan_dirs = [
                    value.get().strip() for value in getattr(self, "_scan_dir_vars", [])
                    if value.get().strip()
                ]
                self.create_desktop_bat = bool(self.bat_var.get())
            elif self.step == 4:
                self.file_types = [
                    ext for ext, value in self.file_type_vars.items() if value.get()
                ]
                if not self.file_types:
                    messagebox.showwarning("文件类型", "请至少选择一种文件类型", parent=self.root)
                    return False
            elif self.step == 5:
                raw_courses = self.course_names_text.get("1.0", tk.END)
                self.course_names = installer_core._clean_list(raw_courses, 100, 80)
                self.pack_profile = {
                    "name": self.pack_name_entry.get().strip()[:100],
                    "school": self.pack_school_entry.get().strip()[:100],
                    "major": self.pack_major_entry.get().strip()[:100],
                    "grade": self.pack_grade_entry.get().strip()[:100],
                    "semester": self.active_semester,
                }
                self.apply_rules_on_upgrade = bool(self.apply_rules_var.get())
                self.open_brain_after_install = bool(self.open_brain_var.get())
                if self.imported_rule_pack is not None:
                    self.imported_rule_pack = installer_core.validate_rule_pack(
                        self.imported_rule_pack, self.course_names or None
                    )
            return True
        except ValueError as exc:
            messagebox.showerror("配置无效", str(exc), parent=self.root)
            return False
        except Exception as exc:
            messagebox.showerror("无法保存当前步骤", str(exc), parent=self.root)
            return False

    def _get_class_name_value(self):
        try:
            if hasattr(self, "class_entry"):
                return self.class_entry.get().strip() or self.class_name
        except Exception:
            pass
        return self.class_name or "未命名班级"

    def _default_class_folder(self, class_name=None):
        return os.path.join(os.path.expanduser("~"), "Desktop", class_name or self._get_class_name_value())

    def _default_experiment_dir(self, class_name=None):
        return os.path.join(self._default_class_folder(class_name), "实验")

    def _default_homework_dir(self, install_dir=None):
        return os.path.join(install_dir or self.install_dir, "homework")

    def _default_scan_dirs(self, install_dir=None, class_name=None):
        dirs = [self._default_experiment_dir(class_name), self._default_homework_dir(install_dir)]
        result = []
        for d in dirs:
            if d and d not in result:
                result.append(d)
        return result

    def _ensure_safe_install_dir(self, install_dir):
        """阻止把安装目录直接选成桌面、用户根目录或系统目录。"""
        abs_dir = os.path.abspath(os.path.expandvars(os.path.expanduser(install_dir or "")))
        if not abs_dir or _is_drive_root(abs_dir):
            raise ValueError("安装目录不能是磁盘根目录，请选择一个专用文件夹。")
        if os.path.normcase(abs_dir) in PROTECTED_INSTALL_DIRS:
            raise ValueError("安装目录不能直接选择桌面、用户目录、下载目录或系统目录，请选择一个专用文件夹。")
        return abs_dir

    def _new_install_journal(self):
        return installer_core.InstallTransaction(self.install_dir)

    def _remember_dir(self, journal, path):
        journal.ensure_dir(path)

    def _write_json_file(self, journal, path, payload):
        journal.write_json(path, payload)

    def _write_text_file(self, journal, path, content):
        journal.write_text(path, content)

    def _copy_install_file(self, journal, src, dst):
        journal.copy_file(src, dst)

    def _cleanup_install_journal(self, journal):
        if journal:
            journal.close()
    
    def _show_loading(self, text="加载中..."):
        """显示加载中提示"""
        self._clear_content()
        self.btn_back.configure(state=tk.DISABLED)
        self.btn_next.configure(state=tk.DISABLED, text="请稍候...")
        
        tk.Label(
            self.content_frame,
            text="⏳",
            font=("Segoe UI", 48),
            fg=self.colors["accent"],
            bg=self.colors["bg"]
        ).pack(pady=(80, 16))
        
        tk.Label(
            self.content_frame,
            text=text,
            font=("Segoe UI", 14),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack()
        
        tk.Label(
            self.content_frame,
            text="请稍候，正在进行系统检查...",
            font=("Segoe UI", 10),
            fg=self.colors["text_muted"],
            bg=self.colors["bg"]
        ).pack(pady=(8, 0))
        
        self.root.update_idletasks()
    
    def _prev_step(self):
        """上一步"""
        if self.step > 0:
            self._show_step(self.step - 1)
    
    # ============================================================
    # Step 0: 欢迎页
    # ============================================================
    def _step_welcome(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Logo 区域
        tk.Label(
            frame,
            text="📋",
            font=("Segoe UI", 64),
            fg=self.colors["accent"],
            bg=self.colors["bg"]
        ).pack(pady=(30, 10))
        
        tk.Label(
            frame,
            text=APP_NAME,
            font=("Segoe UI", 26, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack()
        
        tk.Label(
            frame,
            text=f"版本 {APP_VERSION} · By {AUTHOR}",
            font=("Segoe UI", 11),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(4, 20))
        
        # 功能说明
        features = [
            "🔍 自动扫描微信文件夹中的作业文件",
            "🏷️ 智能关键词归类到对应科目",
            "📢 公告推送系统，随时发布更新通知",
            "🔄 在线更新模块，修复bug无需重装",
        ]
        
        for feat in features:
            tk.Label(
                frame,
                text=feat,
                font=("Segoe UI", 11),
                fg=self.colors["text_secondary"],
                bg=self.colors["bg"],
                justify=tk.LEFT
            ).pack(anchor=tk.W, padx=60, pady=2)
        
        mode_card = tk.Frame(frame, bg=self.colors["bg_card"])
        mode_card.pack(fill=tk.X, padx=60, pady=(18, 0))
        tk.Label(
            mode_card,
            text="安装方式",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg_card"],
        ).pack(anchor=tk.W, padx=12, pady=(10, 4))
        self.install_mode_var = tk.StringVar(value=self.install_mode)
        modes = [
            ("auto", "自动判断", "检测到用户配置时升级；只有程序文件时修复"),
            ("new", "全新安装", "创建新的基础配置与分类规则"),
            ("upgrade", "升级现有安装", "保留用户数据，只补充新配置项"),
            ("repair", "修复程序文件", "只替换程序，不写入 data 目录"),
        ]
        for value, title, description in modes:
            row = tk.Frame(mode_card, bg=self.colors["bg_card"])
            row.pack(fill=tk.X, padx=8, pady=2)
            tk.Radiobutton(
                row, text=title, variable=self.install_mode_var, value=value,
                font=("Segoe UI", 9, "bold"), fg=self.colors["text"],
                bg=self.colors["bg_card"], activebackground=self.colors["bg_card"],
                activeforeground=self.colors["text"], selectcolor=self.colors["bg_input"],
            ).pack(side=tk.LEFT)
            tk.Label(
                row, text=description, font=("Segoe UI", 8),
                fg=self.colors["text_muted"], bg=self.colors["bg_card"],
            ).pack(side=tk.LEFT, padx=(8, 0))
        target = tk.Frame(mode_card, bg=self.colors["bg_card"])
        target.pack(fill=tk.X, padx=12, pady=(8, 10))
        tk.Label(target, text="目标目录", font=("Segoe UI", 8), fg=self.colors["text_muted"],
                 bg=self.colors["bg_card"]).pack(anchor=tk.W)
        target_row = tk.Frame(target, bg=self.colors["bg_card"])
        target_row.pack(fill=tk.X, pady=(3, 0))
        self.welcome_install_dir_entry = tk.Entry(
            target_row, font=("Segoe UI", 9), bg=self.colors["bg_input"], fg=self.colors["text"],
            insertbackground=self.colors["accent"], relief=tk.FLAT, bd=5,
        )
        self.welcome_install_dir_entry.insert(0, self.install_dir)
        self.welcome_install_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            target_row, text="浏览", command=self._browse_welcome_install_dir,
            font=("Segoe UI", 8), bg=self.colors["bg_input"], fg=self.colors["text"],
            relief=tk.FLAT, padx=9, pady=5,
        ).pack(side=tk.LEFT, padx=(6, 0))
        tk.Label(
            frame,
            text="点击「下一步」继续",
            font=("Segoe UI", 10),
            fg=self.colors["text_muted"],
            bg=self.colors["bg"]
        ).pack(pady=(12, 0))

    def _browse_welcome_install_dir(self):
        path = filedialog.askdirectory(title="选择安装或升级目录", parent=self.root)
        if path:
            self.welcome_install_dir_entry.delete(0, tk.END)
            self.welcome_install_dir_entry.insert(0, path)

    def _load_existing_install_context(self, install_dir):
        if self.detected_mode != "upgrade":
            return
        try:
            cfg = installer_core.load_json(Path(install_dir) / "data" / "config.json", {})
        except Exception as exc:
            raise ValueError(f"现有配置无法读取，已停止升级：{exc}") from exc
        if not isinstance(cfg, dict):
            raise ValueError("现有配置不是 JSON 对象，已停止升级")
        self.class_name = str(cfg.get("class_name") or self.class_name).strip()[:80]
        ai_settings = cfg.get("ai_classifier") if isinstance(cfg.get("ai_classifier"), dict) else {}
        self.active_semester = str(ai_settings.get("active_semester") or "").strip()[:100]
        self.class_aliases = installer_core._clean_list(ai_settings.get("class_aliases"), 30, 80)
        self.file_types = installer_core._clean_list(cfg.get("file_types"), 100, 20) or self.file_types
        self.scan_dirs = installer_core._clean_list(cfg.get("scan_dirs"), 50, 500)
        self.create_desktop_bat = True
        rules_path = Path(install_dir) / "data" / "ai_rules.json"
        try:
            rules = installer_core.load_json(rules_path, {})
            profile = rules.get("profile") if isinstance(rules, dict) and isinstance(rules.get("profile"), dict) else {}
            self.pack_profile.update({key: str(profile.get(key) or "") for key in self.pack_profile})
            if isinstance(rules, dict):
                self.course_names = [
                    name for name, item in (rules.get("subjects") or {}).items()
                    if isinstance(item, dict) and item.get("active", True)
                ]
        except Exception as exc:
            if rules_path.exists():
                raise ValueError(f"现有专业包无法读取，已停止升级：{exc}") from exc
    
    # ============================================================
    # Step 1: 环境检测
    # ============================================================
    def _step_env_check(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            frame,
            text="🔧 环境检测",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(pady=(10, 6))
        
        tk.Label(
            frame,
            text="正在检测系统运行环境...",
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(0, 16))
        
        # 检测结果容器
        self.env_result_frame = tk.Frame(frame, bg=self.colors["bg"])
        self.env_result_frame.pack(fill=tk.X, padx=40)
        
        # 执行检测
        self._run_env_check()
    
    def _find_python(self):
        """查找系统可用的 Python"""
        candidates = [
            "python",
            "python3",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python313", "python.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Python313", "python.exe"),
        ]
        for cmd in candidates:
            try:
                result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return cmd, (result.stdout.strip() or result.stderr.strip())
            except Exception:
                continue
        return None, None

    def _run_env_check(self):
        """执行环境检测"""
        # 清空
        for w in self.env_result_frame.winfo_children():
            w.destroy()
        
        # 检测 Python（打包成exe后 sys.executable 不再指向系统python，改用路径查找）
        python_cmd, py_version = self._find_python()
        
        if python_cmd:
            self.python_ok = True
            self._python_cmd = python_cmd
            status_text = f"✅ Python 已安装: {py_version}"
            status_color = self.colors["accent"]
        else:
            self.python_ok = False
            status_text = f"⚠️ Python 未安装"
            status_color = self.colors["warning"]
        
        self._add_env_row("Python 运行环境", status_text, status_color)
        
        # 检测 pip
        if python_cmd:
            try:
                result = subprocess.run(
                    [python_cmd, "-m", "pip", "--version"],
                    capture_output=True, text=True, timeout=10
                )
                pip_version = result.stdout.strip().split()[1] if result.stdout else "已安装"
                self.pip_ok = True
                status_text = f"✅ pip 已安装: {pip_version}"
                status_color = self.colors["accent"]
            except Exception:
                self.pip_ok = False
                status_text = f"⚠️ pip 未安装"
                status_color = self.colors["warning"]
        else:
            self.pip_ok = False
            status_text = f"⚠️ 未检测到 Python"
            status_color = self.colors["warning"]
        
        self._add_env_row("pip 包管理器", status_text, status_color)
        
        # 如果 Python 未安装，提供下载选项
        if not self.python_ok:
            tk.Label(
                self.env_result_frame,
                text="\n💡 未检测到 Python，系统将自动下载嵌入版 Python 并安装到目标目录。",
                font=("Segoe UI", 10),
                fg=self.colors["info"],
                bg=self.colors["bg"],
                justify=tk.LEFT,
                wraplength=550
            ).pack(anchor=tk.W, pady=(12, 4))
            
            tk.Label(
                self.env_result_frame,
                text=f"下载地址: {PYTHON_EMBED_URL}\n大小: 约 {PYTHON_EMBED_SIZE_MB} MB",
                font=("Segoe UI", 9),
                fg=self.colors["text_muted"],
                bg=self.colors["bg"],
                justify=tk.LEFT
            ).pack(anchor=tk.W, pady=(0, 8))
            
            self.btn_next.configure(text="继续安装（将下载Python）→")
        else:
            tk.Label(
                self.env_result_frame,
                text="\n✅ 环境检测通过，可以继续安装。",
                font=("Segoe UI", 10),
                fg=self.colors["accent"],
                bg=self.colors["bg"]
            ).pack(anchor=tk.W, pady=(12, 0))
    
    def _add_env_row(self, label, status, color):
        """添加环境检测结果行"""
        row = tk.Frame(self.env_result_frame, bg=self.colors["bg"])
        row.pack(fill=tk.X, pady=4)
        
        tk.Label(
            row, text=label,
            font=("Segoe UI", 11),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"],
            width=16, anchor=tk.W
        ).pack(side=tk.LEFT)
        
        tk.Label(
            row, text=status,
            font=("Segoe UI", 11),
            fg=color,
            bg=self.colors["bg"]
        ).pack(side=tk.LEFT)
    
    # ============================================================
    # Step 2: 班级设置
    # ============================================================
    def _step_class(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            frame,
            text="🏫 班级设置",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(pady=(10, 6))
        
        tk.Label(
            frame,
            text="班级信息用于文件名清洗；学期用于区分当前启用课程",
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(0, 20))
        
        # 输入框
        input_frame = tk.Frame(frame, bg=self.colors["bg"])
        input_frame.pack(fill=tk.X, padx=60)
        
        tk.Label(
            input_frame,
            text="班级名称:",
            font=("Segoe UI", 11),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(anchor=tk.W)
        
        self.class_entry = tk.Entry(
            input_frame,
            font=("Segoe UI", 14),
            bg=self.colors["bg_input"],
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief=tk.FLAT,
            bd=8
        )
        self.class_entry.insert(0, self.class_name)
        self.class_entry.pack(fill=tk.X, pady=(6, 10))
        
        # 预览
        self.class_preview = tk.Label(
            input_frame,
            text=f"预览: 仪表盘将显示「{self.class_name}」",
            font=("Segoe UI", 10),
            fg=self.colors["accent"],
            bg=self.colors["bg"]
        )
        self.class_preview.pack(anchor=tk.W)
        
        # 实时预览更新
        def on_class_change(*args):
            name = self.class_entry.get().strip() or "未命名班级"
            self.class_name = name
            self.class_preview.configure(text=f"预览: 仪表盘将显示「{name}」")
        
        self.class_entry.bind("<KeyRelease>", on_class_change)

        tk.Label(
            input_frame, text="班级别名（每行或逗号分隔）:",
            font=("Segoe UI", 10), fg=self.colors["text_secondary"], bg=self.colors["bg"]
        ).pack(anchor=tk.W, pady=(12, 0))
        self.class_aliases_entry = tk.Entry(
            input_frame, font=("Segoe UI", 10), bg=self.colors["bg_input"],
            fg=self.colors["text"], insertbackground=self.colors["accent"], relief=tk.FLAT, bd=6,
        )
        self.class_aliases_entry.insert(0, "，".join(self.class_aliases))
        self.class_aliases_entry.pack(fill=tk.X, pady=(4, 8))

        tk.Label(
            input_frame, text="当前学期（可留空）:",
            font=("Segoe UI", 10), fg=self.colors["text_secondary"], bg=self.colors["bg"]
        ).pack(anchor=tk.W)
        self.semester_entry = tk.Entry(
            input_frame, font=("Segoe UI", 10), bg=self.colors["bg_input"],
            fg=self.colors["text"], insertbackground=self.colors["accent"], relief=tk.FLAT, bd=6,
        )
        self.semester_entry.insert(0, self.active_semester)
        self.semester_entry.pack(fill=tk.X, pady=(4, 0))
    
    # ============================================================
    # Step 3: 安装与目录配置
    # ============================================================
    def _step_dirs(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            frame,
            text="📁 安装与目录配置",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(pady=(10, 6))
        
        tk.Label(
            frame,
            text="配置安装目录和作业扫描目录",
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(0, 16))
        
        # 使用可滚动的 Canvas
        canvas = tk.Canvas(frame, bg=self.colors["bg"], highlightthickness=0, height=280)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.colors["bg"])
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=40)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 安装目录
        tk.Label(
            scroll_frame,
            text="安装目录:",
            font=("Segoe UI", 11, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(anchor=tk.W, pady=(0, 4))
        
        dir_row = tk.Frame(scroll_frame, bg=self.colors["bg"])
        dir_row.pack(fill=tk.X)
        
        self.install_dir_entry = tk.Entry(
            dir_row,
            font=("Segoe UI", 10),
            bg=self.colors["bg_input"],
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief=tk.FLAT,
            bd=6
        )
        self.install_dir_entry.insert(0, self.install_dir)
        self.install_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        tk.Button(
            dir_row, text="浏览...",
            command=self._browse_install_dir,
            font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["text"],
            activebackground=self.colors["border"],
            relief=tk.FLAT, bd=0, padx=10, pady=4,
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=(6, 0))
        
        # 桌面BAT脚本
        self.bat_var = tk.BooleanVar(value=self.create_desktop_bat)
        tk.Checkbutton(
            scroll_frame,
            text="在桌面创建启动脚本 (启动作业追踪器.bat)",
            variable=self.bat_var,
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"],
            selectcolor=self.colors["bg_input"],
            activebackground=self.colors["bg"],
            activeforeground=self.colors["text"]
        ).pack(anchor=tk.W, pady=(12, 6))
        
        # 分隔
        tk.Frame(scroll_frame, bg=self.colors["border"], height=1).pack(fill=tk.X, pady=(12, 12))
        
        # 扫描目录
        tk.Label(
            scroll_frame,
            text="作业扫描目录:",
            font=("Segoe UI", 11, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(anchor=tk.W, pady=(0, 4))
        
        tk.Label(
            scroll_frame,
            text="💡 微信接收文件会自动发现；这里用于“扫描已有文件”，默认包含 桌面\\班级\\公示文件夹 和安装目录 homework",
            font=("Segoe UI", 9),
            fg=self.colors["text_muted"],
            bg=self.colors["bg"]
        ).pack(anchor=tk.W, pady=(0, 8))
        
        # 扫描目录列表
        self.scan_dirs_list_frame = tk.Frame(scroll_frame, bg=self.colors["bg"])
        self.scan_dirs_list_frame.pack(fill=tk.X)
        
        # 初始添加默认扫描目录：公示/作业目录 + 本地手动投递目录
        if not self.scan_dirs:
            self.scan_dirs = self._default_scan_dirs(self.install_dir, self._get_class_name_value())
        self._render_scan_dirs()
        
        # 添加目录行
        add_frame = tk.Frame(scroll_frame, bg=self.colors["bg"])
        add_frame.pack(fill=tk.X, pady=(8, 0))
        
        self.new_scan_dir_entry = tk.Entry(
            add_frame,
            font=("Segoe UI", 10),
            bg=self.colors["bg_input"],
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief=tk.FLAT,
            bd=6
        )
        self.new_scan_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.new_scan_dir_entry.bind("<Return>", lambda e: self._add_scan_dir())
        
        tk.Button(
            add_frame, text="+ 添加",
            command=self._add_scan_dir,
            font=("Segoe UI", 9),
            bg=self.colors["accent"], fg="#000",
            activebackground=self.colors["accent_hover"],
            relief=tk.FLAT, bd=0, padx=12, pady=4,
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=(6, 0))
        
        tk.Button(
            add_frame, text="📂 浏览",
            command=self._browse_scan_dir,
            font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["text"],
            activebackground=self.colors["border"],
            relief=tk.FLAT, bd=0, padx=10, pady=4,
            cursor="hand2"
        ).pack(side=tk.LEFT, padx=(6, 0))
        
        # 数据存储目录
        tk.Frame(scroll_frame, bg=self.colors["border"], height=1).pack(fill=tk.X, pady=(12, 12))
        
        tk.Label(
            scroll_frame,
            text="数据存储目录（固定在安装目录 data/，用于配置和提交记录）:",
            font=("Segoe UI", 11, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(anchor=tk.W, pady=(0, 4))
        
        self.data_dir_entry = tk.Entry(
            scroll_frame,
            font=("Segoe UI", 10),
            bg=self.colors["bg_input"],
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief=tk.FLAT,
            bd=6
        )
        self.data_dir_entry.insert(0, os.path.join(self.install_dir, "data"))
        self.data_dir_entry.configure(state=tk.DISABLED)
        self.data_dir_entry.pack(fill=tk.X, pady=(4, 0))
    
    def _render_scan_dirs(self):
        """渲染扫描目录列表"""
        for w in self.scan_dirs_list_frame.winfo_children():
            w.destroy()
        
        self._scan_dir_vars = []
        
        for i, d in enumerate(self.scan_dirs):
            row = tk.Frame(self.scan_dirs_list_frame, bg=self.colors["bg"])
            row.pack(fill=tk.X, pady=2)
            
            var = tk.StringVar(value=d)
            self._scan_dir_vars.append(var)
            
            entry = tk.Entry(
                row,
                textvariable=var,
                font=("Segoe UI", 10),
                bg=self.colors["bg_input"],
                fg=self.colors["text"],
                insertbackground=self.colors["accent"],
                relief=tk.FLAT,
                bd=4
            )
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            tk.Button(
                row, text="×",
                command=lambda idx=i: self._remove_scan_dir(idx),
                font=("Segoe UI", 10, "bold"),
                fg=self.colors["danger"],
                bg=self.colors["bg"],
                activebackground=self.colors["bg"],
                relief=tk.FLAT,
                bd=0,
                cursor="hand2"
            ).pack(side=tk.RIGHT, padx=(6, 0))
    
    def _add_scan_dir(self):
        """添加扫描目录"""
        if not hasattr(self, 'new_scan_dir_entry'):
            return
        try:
            path = self.new_scan_dir_entry.get().strip()
        except Exception:
            return
        if not path:
            messagebox.showwarning("提示", "请输入目录路径", parent=self.root)
            return
        self.scan_dirs.append(path)
        self.new_scan_dir_entry.delete(0, tk.END)
        self._render_scan_dirs()
    
    def _remove_scan_dir(self, index):
        """移除扫描目录"""
        if len(self.scan_dirs) <= 1:
            messagebox.showwarning("提示", "至少需要保留一个扫描目录", parent=self.root)
            return
        self.scan_dirs.pop(index)
        self._render_scan_dirs()
    
    def _browse_install_dir(self):
        """浏览选择安装目录"""
        path = filedialog.askdirectory(title="选择安装目录", parent=self.root)
        if path:
            old_install = self.install_dir_entry.get().strip() or self.install_dir
            old_homework = self._default_homework_dir(old_install)
            self.install_dir_entry.delete(0, tk.END)
            self.install_dir_entry.insert(0, path)
            self.install_dir = path
            if hasattr(self, "data_dir_entry"):
                self.data_dir_entry.configure(state=tk.NORMAL)
                self.data_dir_entry.delete(0, tk.END)
                self.data_dir_entry.insert(0, os.path.join(path, "data"))
                self.data_dir_entry.configure(state=tk.DISABLED)
            new_homework = self._default_homework_dir(path)
            self.scan_dirs = [new_homework if d == old_homework else d for d in self.scan_dirs]
            if new_homework not in self.scan_dirs:
                self.scan_dirs.append(new_homework)
            if hasattr(self, "scan_dirs_list_frame"):
                self._render_scan_dirs()
    
    def _browse_scan_dir(self):
        """浏览选择扫描目录"""
        path = filedialog.askdirectory(title="选择作业扫描目录", parent=self.root)
        if path:
            self.scan_dirs.append(path)
            self._render_scan_dirs()
    
    # ============================================================
    # Step 4: 文件类型设置
    # ============================================================
    def _step_file_types(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            frame,
            text="📄 文件类型设置",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(pady=(10, 6))
        
        tk.Label(
            frame,
            text="选择需要扫描追踪的文件格式（勾选即启用）",
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(0, 16))
        
        # 文件类型复选框
        self.file_type_vars = {}
        
        for group_name, extensions in FILE_TYPE_GROUPS.items():
            group_frame = tk.Frame(frame, bg=self.colors["bg"])
            group_frame.pack(fill=tk.X, padx=60, pady=(0, 12))
            
            tk.Label(
                group_frame,
                text=f"📁 {group_name}:",
                font=("Segoe UI", 11, "bold"),
                fg=self.colors["text"],
                bg=self.colors["bg"]
            ).pack(anchor=tk.W, pady=(0, 4))
            
            ext_frame = tk.Frame(group_frame, bg=self.colors["bg"])
            ext_frame.pack(fill=tk.X)
            
            for ext in extensions:
                var = tk.BooleanVar(value=ext in self.file_types)
                self.file_type_vars[ext] = var
                
                tk.Checkbutton(
                    ext_frame,
                    text=ext,
                    variable=var,
                    font=("Segoe UI", 10),
                    fg=self.colors["text_secondary"],
                    bg=self.colors["bg"],
                    selectcolor=self.colors["bg_input"],
                    activebackground=self.colors["bg"],
                    activeforeground=self.colors["text"]
                ).pack(side=tk.LEFT, padx=(0, 16))
    
    # ============================================================
    # Step 5: 科目关键词配置
    # ============================================================
    def _step_subjects(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="分类大脑初始化",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(pady=(10, 6))

        tk.Label(
            frame,
            text="可选步骤。零样本也能使用规则分类，所有设置安装后仍可修改。",
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(0, 12))

        canvas = tk.Canvas(frame, bg=self.colors["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        body = tk.Frame(canvas, bg=self.colors["bg"])
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=body, anchor=tk.NW)
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(30, 0))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        profile = tk.Frame(body, bg=self.colors["bg_card"])
        profile.pack(fill=tk.X, padx=(0, 18), pady=(0, 10))
        tk.Label(profile, text="专业包信息", font=("Segoe UI", 10, "bold"),
                 fg=self.colors["text"], bg=self.colors["bg_card"]).pack(anchor=tk.W, padx=12, pady=(10, 4))
        grid = tk.Frame(profile, bg=self.colors["bg_card"])
        grid.pack(fill=tk.X, padx=12, pady=(0, 10))
        fields = [
            ("规则包名称（可选）", "pack_name_entry", "name"),
            ("学校（可选）", "pack_school_entry", "school"),
            ("专业（可选）", "pack_major_entry", "major"),
            ("年级（可选）", "pack_grade_entry", "grade"),
        ]
        for index, (label, attr, key) in enumerate(fields):
            box = tk.Frame(grid, bg=self.colors["bg_card"])
            box.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 5, 5 if index % 2 == 0 else 0), pady=3)
            tk.Label(box, text=label, font=("Segoe UI", 8), fg=self.colors["text_muted"],
                     bg=self.colors["bg_card"]).pack(anchor=tk.W)
            entry = tk.Entry(box, font=("Segoe UI", 9), bg=self.colors["bg_input"], fg=self.colors["text"],
                             insertbackground=self.colors["accent"], relief=tk.FLAT, bd=5)
            entry.insert(0, self.pack_profile.get(key, ""))
            entry.pack(fill=tk.X)
            setattr(self, attr, entry)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        courses_card = tk.Frame(body, bg=self.colors["bg_card"])
        courses_card.pack(fill=tk.X, padx=(0, 18), pady=(0, 10))
        tk.Label(courses_card, text="本学期正式课程", font=("Segoe UI", 10, "bold"),
                 fg=self.colors["text"], bg=self.colors["bg_card"]).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(courses_card, text="每行一门课程。课程为空时会保留纯规则冷启动。",
                 font=("Segoe UI", 8), fg=self.colors["text_muted"], bg=self.colors["bg_card"]).pack(anchor=tk.W, padx=12)
        self.course_names_text = tk.Text(
            courses_card, height=5, font=("Segoe UI", 9), bg=self.colors["bg_input"],
            fg=self.colors["text"], insertbackground=self.colors["accent"], relief=tk.FLAT, bd=6,
        )
        self.course_names_text.insert("1.0", "\n".join(self.course_names))
        self.course_names_text.pack(fill=tk.X, padx=12, pady=(6, 8))
        actions = tk.Frame(courses_card, bg=self.colors["bg_card"])
        actions.pack(fill=tk.X, padx=12, pady=(0, 10))
        for text, command in (
            ("导入 JSON", self._import_rule_pack_file),
            ("从剪贴板导入", self._import_rule_pack_clipboard),
            ("复制 AI 生成提示词", self._copy_professional_prompt),
        ):
            tk.Button(actions, text=text, command=command, font=("Segoe UI", 8),
                      bg=self.colors["bg_input"], fg=self.colors["text"], relief=tk.FLAT,
                      padx=9, pady=5, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        self.rule_pack_status = tk.Label(
            courses_card,
            text=(f"已导入专业包：{len((self.imported_rule_pack or {}).get('subjects', {}))} 门课程"
                  if self.imported_rule_pack else "未导入专业包，将使用上方课程名称初始化空规则"),
            font=("Segoe UI", 8), fg=self.colors["accent"] if self.imported_rule_pack else self.colors["text_muted"],
            bg=self.colors["bg_card"], anchor=tk.W,
        )
        self.rule_pack_status.pack(fill=tk.X, padx=12, pady=(0, 10))

        options = tk.Frame(body, bg=self.colors["bg_card"])
        options.pack(fill=tk.X, padx=(0, 18), pady=(0, 14))
        self.apply_rules_var = tk.BooleanVar(value=self.apply_rules_on_upgrade)
        self.open_brain_var = tk.BooleanVar(value=self.open_brain_after_install)
        tk.Checkbutton(
            options, text="升级时合并本页专业包（默认关闭，避免改变现有课程）",
            variable=self.apply_rules_var, font=("Segoe UI", 9), fg=self.colors["text"],
            bg=self.colors["bg_card"], activebackground=self.colors["bg_card"],
            selectcolor=self.colors["bg_input"],
        ).pack(anchor=tk.W, padx=12, pady=(9, 2))
        tk.Checkbutton(
            options, text="安装完成后启动服务并打开现代版分类大脑",
            variable=self.open_brain_var, font=("Segoe UI", 9), fg=self.colors["text"],
            bg=self.colors["bg_card"], activebackground=self.colors["bg_card"],
            selectcolor=self.colors["bg_input"],
        ).pack(anchor=tk.W, padx=12, pady=2)
        self.ollama_status_label = tk.Label(
            options, text="本地增强：正在静默检测 Ollama...",
            font=("Segoe UI", 8), fg=self.colors["text_muted"], bg=self.colors["bg_card"],
        )
        self.ollama_status_label.pack(anchor=tk.W, padx=12, pady=(4, 9))
        threading.Thread(target=self._detect_ollama_for_page, daemon=True).start()

    def _current_courses_and_profile(self):
        courses = installer_core._clean_list(self.course_names_text.get("1.0", tk.END), 100, 80)
        profile = {
            "name": self.pack_name_entry.get().strip(),
            "school": self.pack_school_entry.get().strip(),
            "major": self.pack_major_entry.get().strip(),
            "grade": self.pack_grade_entry.get().strip(),
            "semester": self.active_semester,
        }
        return courses, profile

    def _accept_rule_pack(self, payload):
        courses, _profile = self._current_courses_and_profile()
        normalized = installer_core.validate_rule_pack(payload, courses or None)
        self.imported_rule_pack = normalized
        imported_courses = list(normalized.get("subjects", {}))
        if not courses:
            self.course_names_text.delete("1.0", tk.END)
            self.course_names_text.insert("1.0", "\n".join(imported_courses))
        self.rule_pack_status.configure(
            text=f"专业包校验通过：{len(imported_courses)} 门课程，安装时等待确认合并",
            fg=self.colors["accent"],
        )

    def _import_rule_pack_file(self):
        path = filedialog.askopenfilename(
            title="选择专业包 JSON", parent=self.root,
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                self._accept_rule_pack(json.load(handle))
        except Exception as exc:
            messagebox.showerror("专业包无效", str(exc), parent=self.root)

    def _import_rule_pack_clipboard(self):
        try:
            self._accept_rule_pack(json.loads(self.root.clipboard_get()))
        except Exception as exc:
            messagebox.showerror("剪贴板专业包无效", str(exc), parent=self.root)

    def _copy_professional_prompt(self):
        courses, profile = self._current_courses_and_profile()
        prompt = installer_core.professional_pack_prompt(profile, courses)
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.rule_pack_status.configure(text="专业包生成提示词已复制，可发送给任意 AI", fg=self.colors["accent"])

    def _detect_ollama_for_page(self):
        status = installer_core.ollama_status()
        def update():
            if not hasattr(self, "ollama_status_label") or not self.ollama_status_label.winfo_exists():
                return
            if status["available"]:
                suffix = f" · {len(status['models'])} 个模型" if status["models"] else ""
                self.ollama_status_label.configure(text="本地增强：检测到 Ollama" + suffix, fg=self.colors["accent"])
            else:
                self.ollama_status_label.configure(text="本地增强：未检测到 Ollama，可跳过并在安装后配置")
        try:
            self.root.after(0, update)
        except (RuntimeError, tk.TclError):
            # The user may close the wizard while the short probe is finishing.
            pass
    
    # ============================================================
    # Step 6: 安装执行
    # ============================================================
    def _step_install(self):
        frame = tk.Frame(self.content_frame, bg=self.colors["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            frame,
            text="🚀 安装执行",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        ).pack(pady=(10, 6))
        
        tk.Label(
            frame,
            text="正在安装，请稍候...",
            font=("Segoe UI", 10),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        ).pack(pady=(0, 12))
        
        # 进度条
        self.progress_bar = ttk.Progressbar(
            frame,
            variable=self.progress_var,
            maximum=100,
            length=500
        )
        self.progress_bar.pack(pady=(8, 4))
        
        # 进度文字
        self.progress_label = tk.Label(
            frame,
            textvariable=self.progress_text,
            font=("Segoe UI", 9),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg"]
        )
        self.progress_label.pack()
        
        # 日志区域
        log_frame = tk.Frame(frame, bg=self.colors["bg_input"])
        log_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(12, 0))
        
        self.log_text = tk.Text(
            log_frame,
            font=("Consolas", 9),
            bg=self.colors["bg_input"],
            fg=self.colors["text_secondary"],
            relief=tk.FLAT,
            bd=6,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 开始安装
        self.root.after(500, self._execute_install)
    
    def _log(self, message, level="INFO"):
        """写入安装日志（线程安全，通过 root.after 调度到主线程）"""
        self.install_log.append((level, message))
        
        def _write():
            try:
                self.log_text.configure(state=tk.NORMAL)
                color = self.colors["text_secondary"]
                if level == "ERROR":
                    color = self.colors["danger"]
                elif level == "SUCCESS":
                    color = self.colors["accent"]
                elif level == "WARN":
                    color = self.colors["warning"]
                
                self.log_text.insert(tk.END, f"[{level}] {message}\n")
                line_start = self.log_text.index("end-2c linestart")
                self.log_text.tag_add(level, line_start, "end-1c")
                self.log_text.tag_configure(level, foreground=color)
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
            except Exception:
                pass  # widget 可能已被销毁
        
        self.root.after(0, _write)
    
    def _set_progress(self, value, text):
        """设置进度（线程安全）"""
        def _update():
            try:
                self.progress_var.set(value)
                self.progress_text.set(text)
            except Exception:
                pass
        
        self.root.after(0, _update)
    
    def _execute_install(self):
        """执行安装"""
        install_dir = self._ensure_safe_install_dir(self.install_dir or DEFAULT_INSTALL_DIR)
        class_name = self.class_name or "课程班级"
        create_desktop_bat = self.create_desktop_bat
        file_types = self.file_types or [".pdf", ".docx", ".doc"]
        scan_dirs = list(self.scan_dirs)
        for default_dir in self._default_scan_dirs(install_dir, class_name):
            if default_dir not in scan_dirs:
                scan_dirs.append(default_dir)
        mode = installer_core.detect_install_mode(install_dir, self.install_mode)
        profile = dict(self.pack_profile)
        profile["semester"] = self.active_semester
        rules = self.imported_rule_pack or installer_core.build_course_rule_pack(
            self.course_names, profile
        )
        python_ok = self.python_ok or os.path.isfile(
            os.path.join(install_dir, "python", "python.exe")
        )
        
        # 先显示开始日志
        self._log("安装准备就绪，开始执行...", "INFO")
        self._set_progress(2, "准备中...")
        
        # 启动后台线程
        def install_thread():
            self._do_install(
                install_dir, class_name, create_desktop_bat, file_types, scan_dirs,
                rules, python_ok, mode, self.apply_rules_on_upgrade,
            )
        
        threading.Thread(target=install_thread, daemon=True).start()
    
    def _do_install(self, install_dir, class_name, create_desktop_bat, file_types, scan_dirs,
                    rules, python_ok, mode="auto", apply_rules_on_upgrade=False):
        """在后台线程中执行实际安装操作"""
        journal = None
        try:
            install_dir = self._ensure_safe_install_dir(install_dir)
            data_dir = os.path.join(install_dir, "data")
            scan_dirs = [os.path.abspath(d) for d in scan_dirs if d]
            mode = installer_core.detect_install_mode(install_dir, mode)
            journal = self._new_install_journal()
            total_steps = 5
            if not python_ok:
                total_steps = 6
            
            # ====== 步骤1: 创建目录 ======
            self._set_progress(5, "正在创建安装目录...")
            self._log("创建安装目录...")
            class_folder = os.path.join(os.path.expanduser("~"), "Desktop", class_name)
            organized_dir = os.path.join(class_folder, "已收作业")
            experiment_dir = os.path.join(class_folder, "实验")
            desired_config = installer_core.build_default_config(
                class_name=class_name,
                class_folder=class_folder,
                organized_dir=organized_dir,
                experiment_dir=experiment_dir,
                scan_dirs=scan_dirs,
                file_types=file_types,
                version=APP_VERSION,
                active_semester=self.active_semester,
                class_aliases=self.class_aliases,
            )
            data_plan = installer_core.build_data_plan(
                data_dir, mode, desired_config, rules,
                apply_rules=bool(apply_rules_on_upgrade),
            )
            missing_resources = [
                name for name in INSTALL_FILES
                if not os.path.isfile(get_resource_path(name))
            ]
            if missing_resources:
                raise FileNotFoundError(
                    "安装资源缺失：" + "、".join(missing_resources[:5])
                )
            python_dir = os.path.join(install_dir, "python")
            if not python_ok and os.path.exists(python_dir):
                raise RuntimeError(
                    "检测到不完整的内置 Python 目录。为避免覆盖未知文件，安装已停止；"
                    "请先备份并移除安装目录中的 python 文件夹后重试。"
                )
            # Finish every read-only validation before stopping an old service.
            # Invalid user data must leave the currently running install alone.
            if mode in ("upgrade", "repair"):
                self._set_progress(3, "正在安全停止旧服务...")
                stop_result = installer_core.stop_running_install(install_dir)
                if stop_result.get("running"):
                    self._log("旧服务已正常停止，可以开始更新程序文件", "SUCCESS")

            self._remember_dir(journal, install_dir)
            effective_config = data_plan.get("config") or {}
            if mode != "repair":
                self._remember_dir(journal, data_dir)
                class_folder = effective_config.get("class_folder", class_folder)
                organized_dir = effective_config.get("organized_dir", organized_dir)
                experiment_dir = effective_config.get("experiment_dir", experiment_dir)
                for directory in [class_folder, organized_dir, experiment_dir]:
                    if directory:
                        self._remember_dir(journal, directory)
                for directory in effective_config.get("scan_dirs", []):
                    if directory:
                        self._remember_dir(journal, directory)
            
            self._log(f"安装目录: {install_dir}", "SUCCESS")
            self._log(f"安装模式: {mode}", "SUCCESS")
            if mode == "repair":
                self._log("修复模式：data/ 中的配置与用户数据不会写入", "SUCCESS")
            else:
                self._log(f"数据目录: {data_dir}", "SUCCESS")
                self._log(f"已收作业目录: {organized_dir}", "SUCCESS")
                self._log(f"公示/作业目录: {experiment_dir}", "SUCCESS")
                self._log(f"已保护运行数据: {len(data_plan.get('preserved', []))} 项", "SUCCESS")
            
            # ====== 步骤2: 下载Python（如果需要） ======
            step = 1
            if not python_ok:
                step = 2
                self._set_progress(20, "正在下载嵌入版 Python...")
                self._log("检测到未安装 Python，正在下载嵌入版...")

                self._remember_dir(journal, python_dir)

                zip_path = os.path.join(
                    tempfile.gettempdir(),
                    f"assignment-dashboard-python-{uuid.uuid4().hex}.zip",
                )
                
                try:
                    self._log(f"从 {PYTHON_EMBED_URL} 下载...")
                    
                    def report_progress(block_num, block_size, total_size):
                        if total_size > 0:
                            downloaded = block_num * block_size
                            percent = min(int(downloaded * 100 / total_size), 100)
                            self._set_progress(20 + percent * 10 // 100, f"下载 Python... {percent}%")
                    
                    urllib.request.urlretrieve(PYTHON_EMBED_URL, zip_path, report_progress)
                    self._log("下载完成", "SUCCESS")
                    
                    # 解压
                    self._set_progress(35, "正在解压 Python...")
                    self._log("解压 Python 嵌入版...")
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(python_dir)
                    self._log("Python 嵌入版安装完成", "SUCCESS")
                    
                    # 清理
                    os.remove(zip_path)
                    
                except urllib.error.URLError as e:
                    self._log(f"下载 Python 失败: {e}", "ERROR")
                    self._log("请手动安装 Python 3.8+ 后重试", "WARN")
                    self._log("下载地址: https://www.python.org/downloads/", "WARN")
                    self._log("正在回滚安装...", "WARN")
                    self._rollback(install_dir, journal)
                    self.root.after(0, lambda: self._install_failed(
                        "Python 下载失败",
                        f"无法从 {PYTHON_EMBED_URL} 下载\n\n请检查网络连接或手动安装 Python 3.8+\n下载地址: https://www.python.org/downloads/"
                    ))
                    return
                except Exception as e:
                    self._log(f"安装 Python 失败: {e}", "ERROR")
                    self._log("正在回滚安装...", "WARN")
                    self._rollback(install_dir, journal)
                    self.root.after(0, lambda: self._install_failed(
                        "Python 安装失败",
                        f"解压或安装 Python 时出错: {str(e)}\n\n请手动安装 Python 3.8+"
                    ))
                    return
            
            # ====== 步骤3: 写入配置 ======
            step += 1
            progress_pct = step * 100 // total_steps
            self._set_progress(progress_pct - 5, "正在写入配置文件...")
            self._log("生成配置文件...")
            
            if mode != "repair":
                self._write_json_file(journal, os.path.join(data_dir, "config.json"), data_plan["config"])
                if data_plan.get("rules") is not None:
                    self._write_json_file(journal, os.path.join(data_dir, "ai_rules.json"), data_plan["rules"])
                for name, payload in data_plan.get("initialize", {}).items():
                    self._write_json_file(journal, os.path.join(data_dir, name), payload)
                self._log("配置与分类规则已安全写入", "SUCCESS")
            
            # ====== 步骤4: 复制文件 ======
            step += 1
            progress_pct = step * 100 // total_steps
            self._set_progress(progress_pct - 5, "正在复制程序文件...")
            self._log("复制程序文件...")
            
            for fname in INSTALL_FILES:
                src = get_resource_path(fname)
                dst = os.path.join(install_dir, fname)
                if not os.path.isfile(src):
                    raise FileNotFoundError(f"安装资源缺失：{fname}")
                self._copy_install_file(journal, src, dst)
                self._log(f"  ✓ {fname}", "SUCCESS")
            
            # ====== 步骤5: 创建BAT脚本 ======
            step += 1
            progress_pct = step * 100 // total_steps
            self._set_progress(progress_pct - 5, "正在创建启动脚本...")
            
            def make_bat_content(cd_dir, python_cmd):
                return (
                '@echo off\r\n'
                'setlocal EnableExtensions\r\n'
                'chcp 65001 >nul\r\n'
                f'title Assignment Dashboard - By {AUTHOR}\r\n'
                f'cd /d "{cd_dir}"\r\n'
                f'set "PORT={APP_PORT}"\r\n'
                f'set "PREFERRED_PYTHON={python_cmd}"\r\n'
                'set "PYTHON_CMD="\r\n'
                'set "PYTHON_ARGS=-B -u"\r\n'
                'if exist "%PREFERRED_PYTHON%" goto use_preferred_python\r\n'
                'goto find_py_launcher\r\n'
                '\r\n'
                ':use_preferred_python\r\n'
                'set "PYTHON_CMD=%PREFERRED_PYTHON%"\r\n'
                'goto python_ready\r\n'
                '\r\n'
                ':find_py_launcher\r\n'
                'where py >nul 2>nul\r\n'
                'if errorlevel 1 goto find_python_cmd\r\n'
                'set "PYTHON_CMD=py"\r\n'
                'set "PYTHON_ARGS=-3 -B -u"\r\n'
                'goto python_ready\r\n'
                '\r\n'
                ':find_python_cmd\r\n'
                'where python >nul 2>nul\r\n'
                'if errorlevel 1 goto python_missing\r\n'
                'set "PYTHON_CMD=python"\r\n'
                'goto python_ready\r\n'
                '\r\n'
                ':python_ready\r\n'
                'echo ============================================\r\n'
                'echo    Assignment Dashboard\r\n'
                f'echo    By {AUTHOR}\r\n'
                'echo    URL: http://localhost:%PORT%\r\n'
                'echo ============================================\r\n'
                'echo.\r\n'
                'if not exist "server.py" goto server_missing\r\n'
                'if /I "%~1"=="--check" goto check_ok\r\n'
                'set /a restarts=0\r\n'
                '\r\n'
                ':loop\r\n'
                'echo Starting server with: %PYTHON_CMD% %PYTHON_ARGS%\r\n'
                'echo Press Ctrl+C to stop.\r\n'
                'echo.\r\n'
                '"%PYTHON_CMD%" %PYTHON_ARGS% server.py\r\n'
                'set "EXIT_CODE=%ERRORLEVEL%"\r\n'
                'if "%EXIT_CODE%"=="0" goto normal_exit\r\n'
                'set /a restarts+=1\r\n'
                'echo.\r\n'
                'echo ============================================\r\n'
                'echo Server exited. Exit code: %EXIT_CODE%\r\n'
                'echo Restarting in 5 seconds... Attempt %restarts%\r\n'
                'echo Press Ctrl+C to quit completely.\r\n'
                'echo ============================================\r\n'
                'timeout /t 5 /nobreak >nul\r\n'
                'if %restarts% GEQ 3 goto offer_repair\r\n'
                'goto loop\r\n'
                '\r\n'
                ':offer_repair\r\n'
                'echo.\r\n'
                'echo ============================================\r\n'
                'echo Server failed to start several times.\r\n'
                'echo If you have an update package, use the offline repair tool.\r\n'
                'echo ============================================\r\n'
                'echo.\r\n'
                'if not exist "repair_update.bat" goto repair_missing\r\n'
                'choice /C YN /M "Open offline update repair tool now"\r\n'
                'if errorlevel 2 goto loop\r\n'
                'call "repair_update.bat"\r\n'
                'exit /b %ERRORLEVEL%\r\n'
                '\r\n'
                ':normal_exit\r\n'
                'echo.\r\n'
                'echo ============================================\r\n'
                'echo Server is already running or stopped normally.\r\n'
                'echo Open: http://localhost:%PORT%\r\n'
                'echo No restart is needed.\r\n'
                'echo ============================================\r\n'
                'echo.\r\n'
                'pause\r\n'
                'exit /b 0\r\n'
                '\r\n'
                ':check_ok\r\n'
                'echo Startup script check OK.\r\n'
                'exit /b 0\r\n'
                '\r\n'
                ':server_missing\r\n'
                'echo [ERROR] server.py was not found in:\r\n'
                'echo %CD%\r\n'
                'echo.\r\n'
                'pause\r\n'
                'exit /b 1\r\n'
                '\r\n'
                ':python_missing\r\n'
                'echo [ERROR] Python was not found.\r\n'
                'echo Install Python 3.8+ or put embedded Python in .\\python\\python.exe\r\n'
                'echo.\r\n'
                'pause\r\n'
                'exit /b 1\r\n'
                '\r\n'
                ':repair_missing\r\n'
                'echo [WARN] repair_update.bat was not found.\r\n'
                'echo Please ask the administrator for a full installer or repair package.\r\n'
                'echo.\r\n'
                'pause\r\n'
                'goto loop\r\n'
                )

            install_python_cmd = 'python'
            desktop_python_cmd = 'python'
            embedded_python = os.path.join(install_dir, "python", "python.exe")
            if os.path.exists(embedded_python):
                install_python_cmd = "%~dp0python\\python.exe"
                desktop_python_cmd = embedded_python

            bat_content = make_bat_content("%~dp0", install_python_cmd)
            
            bat_path = os.path.join(install_dir, "启动作业追踪器.bat")
            self._write_text_file(journal, bat_path, bat_content)
            self._log("启动脚本已创建", "SUCCESS")
            
            # 桌面BAT
            if create_desktop_bat:
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                desktop_bat = os.path.join(desktop, "启动作业追踪器.bat")
                try:
                    desktop_bat_content = make_bat_content(install_dir, desktop_python_cmd)
                    self._write_text_file(journal, desktop_bat, desktop_bat_content)
                    self._log(f"桌面快捷方式已创建: {desktop_bat}", "SUCCESS")
                except Exception as e:
                    self._log(f"桌面快捷方式创建失败: {e}", "WARN")
                    self._log("请手动将安装目录中的「启动作业追踪器.bat」复制到桌面", "WARN")
            
            # ====== 完成 ======
            self._set_progress(100, "安装完成！")
            self._log("=" * 40, "INFO")
            self._log("安装完成！", "SUCCESS")
            self._log(f"服务地址: http://localhost:{APP_PORT}", "SUCCESS")
            self._log(f"模式: {mode}", "SUCCESS")
            if mode != "repair":
                self._log(f"班级: {effective_config.get('class_name', class_name)}", "SUCCESS")
                self._log(f"扫描目录: {len(effective_config.get('scan_dirs', []))} 个", "SUCCESS")
                self._log(f"当前课程: {len((data_plan.get('rules') or rules or {}).get('subjects', {}))} 门", "SUCCESS")
            self._log(f"文件类型: {len(file_types)} 种", "SUCCESS")
            self._log("=" * 40, "INFO")
            self._log("双击「启动作业追踪器.bat」启动服务", "INFO")
            
            # 启用完成按钮
            self.install_succeeded = True
            self.root.after(0, lambda: self.btn_next.configure(
                state=tk.NORMAL, text="启动并打开" if self.open_brain_after_install else "完成 ✓",
                command=self._finish_install,
            ))
            if self.open_brain_after_install:
                self._log("首次启动后可在现代版“分类大脑”继续配置", "INFO")
            self._cleanup_install_journal(journal)
            
        except Exception as e:
            tb = traceback.format_exc()
            self._log(f"安装过程发生异常: {e}", "ERROR")
            self._log(tb, "ERROR")
            
            # 回滚
            self._log("正在回滚安装...", "WARN")
            self._rollback(install_dir, journal)
            
            self.root.after(0, lambda: self._install_failed(
                "安装失败",
                f"安装过程发生错误:\n\n{str(e)}\n\n系统已自动回滚，请检查后重试。"
            ))

    def _finish_install(self):
        if self.install_succeeded and self.open_brain_after_install:
            bat_path = os.path.join(self.install_dir, "启动作业追踪器.bat")
            try:
                if os.name == "nt" and os.path.exists(bat_path):
                    subprocess.Popen(
                        ["cmd", "/c", "start", "", bat_path],
                        cwd=self.install_dir,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    self.root.after(
                        1200,
                        lambda: webbrowser.open(f"http://localhost:{APP_PORT}/modern#brain"),
                    )
                else:
                    webbrowser.open(f"http://localhost:{APP_PORT}/modern#brain")
            except Exception as exc:
                messagebox.showwarning(
                    "安装已完成",
                    f"程序已安装，但自动启动失败：{exc}\n请双击安装目录中的启动脚本。",
                    parent=self.root,
                )
        self.root.after(1400 if self.open_brain_after_install else 0, self.root.quit)
    
    def _rollback(self, install_dir=None, journal=None):
        """回滚安装，只恢复/删除本次安装记录过的文件和目录。"""
        if install_dir is None:
            install_dir = getattr(self, 'install_dir', None)
            if not install_dir:
                return
        try:
            if not journal:
                self._log("没有可用的安装记录，已跳过自动删除以保护已有文件。", "WARN")
                return

            journal.rollback()
            self._log("回滚完成", "SUCCESS")
        except Exception as e:
            self._log(f"回滚失败: {e}", "ERROR")
            self._log("请手动检查安装目录和桌面快捷方式", "WARN")
        finally:
            self._cleanup_install_journal(journal)
    
    def _install_failed(self, title, message):
        """安装失败弹窗"""
        full_msg = f"{message}\n\n如问题持续，请前往 GitHub Issues 反馈：\n{SUPPORT_URL}"
        messagebox.showerror(title, full_msg, parent=self.root)
    
    def run(self):
        """启动向导"""
        self.root.mainloop()


# ============================================================
# 主入口
# ============================================================

def main():
    if "--self-test-output" in sys.argv:
        try:
            index = sys.argv.index("--self-test-output")
            output = sys.argv[index + 1]
            resources = {
                name: os.path.isfile(get_resource_path(name))
                for name in INSTALL_FILES
            }
            sample_pack = installer_core.build_course_rule_pack(
                ["数字电子技术"], {"name": "安装器自检", "semester": "test"}
            )
            normalized = installer_core.validate_rule_pack(
                sample_pack, ["数字电子技术"]
            )
            payload = {
                "ok": all(resources.values()),
                "version": APP_VERSION,
                "resources": resources,
                "rule_pack_subjects": list(normalized.get("subjects", {})),
                "install_modes": sorted(installer_core.INSTALL_MODES),
            }
            installer_core.atomic_write_json(output, payload)
            return 0 if payload["ok"] else 1
        except Exception as exc:
            try:
                output = sys.argv[sys.argv.index("--self-test-output") + 1]
                installer_core.atomic_write_json(output, {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
            except Exception:
                pass
            return 1
    wizard = InstallerWizard()
    wizard.run()
    print("安装向导已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
