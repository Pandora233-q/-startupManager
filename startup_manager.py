# -*- coding: utf-8 -*-
"""
Startup Manager - Windows 启动项管理软件
功能：管理注册表启动项 / 系统服务 / 计划任务，支持启用、禁用（永久）、删除
新增：中文名称栏（读取 exe FileDescription）、图标显示
运行环境：Windows + Python 3.8+ （管理员权限可完全生效）
"""

import os
import re
import sys
import zlib
import base64
import struct
import ctypes
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import winreg

# ============================================================
#  数据结构
# ============================================================
class StartupItem:
    """统一的启动项数据结构"""
    def __init__(self, name, command, source, location, enabled=True, raw=None,
                 chinese_name="", exe_path=None):
        self.name = name            # 名称（键名/服务名/任务名）
        self.command = command      # 启动命令/路径
        self.source = source        # 来源类别: 注册表 / 服务 / 计划任务
        self.location = location    # 具体位置
        self.enabled = enabled      # 是否启用
        self.raw = raw              # 原始对象
        self.chinese_name = chinese_name  # 中文名称
        self.exe_path = exe_path    # 解析出的 exe 绝对路径（用于图标）

    def __repr__(self):
        return f"<{self.source}> {self.name} enabled={self.enabled}"


# ============================================================
#  权限检测
# ============================================================
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_as_admin():
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit(0)


# ============================================================
#  Windows API 初始化（读取文件信息 + 图标提取，纯 ctypes 无依赖）
# ============================================================
_version = ctypes.windll.version
_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32
_shell32 = ctypes.windll.shell32
_user32 = ctypes.windll.user32

_version.GetFileVersionInfoSizeW.restype = ctypes.c_uint
_version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
_version.GetFileVersionInfoW.restype = ctypes.c_bool
_version.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint,
                                         ctypes.c_uint, ctypes.c_void_p]
_version.VerQueryValueW.restype = ctypes.c_bool
_version.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint), ("biWidth", ctypes.c_int), ("biHeight", ctypes.c_int),
        ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint), ("biSizeImage", ctypes.c_uint),
        ("biXPelsPerMeter", ctypes.c_int), ("biYPelsPerMeter", ctypes.c_int),
        ("biClrUsed", ctypes.c_uint), ("biClrImportant", ctypes.c_uint),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint * 3)]


def _rgba_to_png(rgba, w, h):
    """将 RGBA 字节流编码为 PNG（纯标准库）"""
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ---------- 缓存 ----------
_desc_cache = {}   # exe路径 -> 中文描述
_icon_cache = {}   # exe路径/类别 -> PhotoImage


def _get_file_description(path):
    """读取 exe 的版本信息 FileDescription（通常即中文名）"""
    if path in _desc_cache:
        return _desc_cache[path]
    result = None
    try:
        size = _version.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if _version.GetFileVersionInfoW(path, 0, size, buf):
                p = ctypes.c_void_p()
                ulen = ctypes.c_uint()
                if _version.VerQueryValueW(buf, "\\VarFileInfo\\Translation",
                                           ctypes.byref(p), ctypes.byref(ulen)) and p:
                    trans = ctypes.cast(p, ctypes.POINTER(ctypes.c_ushort))
                    lang, codepage = trans[0], trans[1]
                    sub = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
                    if _version.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(ulen)) and p:
                        text = ctypes.cast(p, ctypes.c_wchar_p).value
                        if text:
                            result = text.strip()
    except Exception:
        pass
    _desc_cache[path] = result
    return result


def _png_to_photo(png_bytes):
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return tk.PhotoImage(data=b64, format="png")


def get_exe_icon(path, size=20):
    """从 exe/dll 提取图标，返回 tk.PhotoImage，失败返回 None"""
    if path in _icon_cache:
        return _icon_cache[path]
    img = None
    hicon = None
    hdc = None
    hbmp = None
    try:
        big = ctypes.c_void_p()
        small = ctypes.c_void_p()
        n = _shell32.ExtractIconExW(path, 0, ctypes.byref(big), ctypes.byref(small), 1)
        if n > 0:
            hicon = small.value or big.value
            if big.value and big.value != hicon:
                _user32.DestroyIcon(big.value)
            hdc = _gdi32.CreateCompatibleDC(None)
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = size
            bmi.bmiHeader.biHeight = -size   # 负值 = 自上而下
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0  # BI_RGB
            bits = ctypes.c_void_p()
            hbmp = _gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0,
                                           ctypes.byref(bits), None, 0)
            if hbmp and bits:
                old = _gdi32.SelectObject(hdc, hbmp)
                _user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, 3)  # DI_NORMAL
                _gdi32.SelectObject(hdc, old)
                buf = ctypes.string_at(bits.value, size * size * 4)
                # BGRA -> RGBA
                rgba = bytearray(size * size * 4)
                rgba[0::4] = buf[2::4]
                rgba[1::4] = buf[1::4]
                rgba[2::4] = buf[0::4]
                rgba[3::4] = buf[3::4]
                if max(rgba[3::4]) == 0:        # 部分图标 alpha 全 0，视为不透明
                    rgba[3::4] = b"\xff" * (size * size)
                img = _png_to_photo(_rgba_to_png(bytes(rgba), size, size))
    except Exception:
        img = None
    finally:
        if hbmp:
            _gdi32.DeleteObject(hbmp)
        if hdc:
            _gdi32.DeleteDC(hdc)
        if hicon:
            _user32.DestroyIcon(hicon)
    _icon_cache[path] = img
    return img


def _make_shape_icon(color, shape="circle", size=20):
    """程序生成的默认图标（服务/任务/未知项）"""
    rgba = bytearray(size * size * 4)
    r, g, b = color
    c = size / 2
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3] = r, g, b, 255
            if shape == "circle":
                if (x - c + .5) ** 2 + (y - c + .5) ** 2 > (c - 1) ** 2:
                    rgba[i + 3] = 0
            else:  # rounded square
                m = 2
                if (x < m or x >= size - m) and (y < m or y >= size - m):
                    rgba[i + 3] = 0
    return _png_to_photo(_rgba_to_png(bytes(rgba), size, size))


def get_fallback_icon(kind):
    """kind: service / task / unknown"""
    colors = {"service": (74, 108, 247), "task": (39, 174, 96), "unknown": (149, 165, 166)}
    shapes = {"service": "square", "task": "circle", "unknown": "circle"}
    key = f"__fb_{kind}"
    if key not in _icon_cache:
        _icon_cache[key] = _make_shape_icon(colors[kind], shapes[kind])
    return _icon_cache[key]


# ---------- 命令解析：提取 exe 路径 ----------
def extract_exe_path(command):
    """从启动命令中解析出 exe 绝对路径（用于图标和中文名）"""
    if not command:
        return None
    cmd = command.strip()
    m = re.match(r'^"([^"]+)"', cmd)
    if m:
        candidate = m.group(1)
    else:
        m = re.search(r"([^\s\"]+\.exe)\b", cmd, re.IGNORECASE)
        candidate = m.group(1) if m else None
    if not candidate:
        return None
    candidate = os.path.expandvars(candidate)
    if not os.path.isabs(candidate):
        for base in [os.environ.get("SystemRoot", r"C:\Windows"),
                     os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
                     os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]:
            p = os.path.join(base, candidate)
            if os.path.exists(p):
                candidate = p
                break
        else:
            return None
    return candidate if os.path.exists(candidate) else None


# ============================================================
#  一、注册表启动项管理
# ============================================================
REG_KEYS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce"),
]
DISABLED_MARK = "_disabled_"


def _reg_list(key_handle, root_name):
    items = []
    try:
        with winreg.OpenKey(key_handle[0], key_handle[1], 0, winreg.KEY_READ) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    i += 1
                    enabled = not name.startswith(DISABLED_MARK)
                    show_name = name[len(DISABLED_MARK):] if not enabled else name
                    exe = extract_exe_path(value)
                    desc = _get_file_description(exe) if exe else None
                    if not desc and exe:
                        desc = os.path.splitext(os.path.basename(exe))[0]
                    items.append(StartupItem(
                        show_name, value, "注册表",
                        f"{root_name}\\{key_handle[1]}", enabled=enabled,
                        chinese_name=desc or "", exe_path=exe))
                except OSError:
                    break
    except OSError:
        pass
    return items


def reg_get_all():
    items = []
    for hk, path in REG_KEYS:
        root_name = "HKCU" if hk == winreg.HKEY_CURRENT_USER else "HKLM"
        items += _reg_list((hk, path), root_name)
    return items


def _reg_split_location(location):
    root = winreg.HKEY_CURRENT_USER if location.startswith("HKCU") else winreg.HKEY_LOCAL_MACHINE
    return root, location.split("\\", 1)[1]


def reg_disable(item):
    root, path = _reg_split_location(item.location)
    with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
        value, vtype = winreg.QueryValueEx(key, item.name)
        winreg.SetValueEx(key, DISABLED_MARK + item.name, 0, vtype, value)
        winreg.DeleteValue(key, item.name)


def reg_enable(item):
    root, path = _reg_split_location(item.location)
    with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
        value, vtype = winreg.QueryValueEx(key, DISABLED_MARK + item.name)
        winreg.SetValueEx(key, item.name, 0, vtype, value)
        winreg.DeleteValue(key, DISABLED_MARK + item.name)


def reg_delete(item):
    root, path = _reg_split_location(item.location)
    with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
        winreg.DeleteValue(key, item.name)


# ============================================================
#  二、系统服务管理
# ============================================================
def _sc_output(args):
    r = subprocess.run(["sc"] + args, capture_output=True, text=True,
                       encoding="gbk", errors="ignore")
    return r.stdout + r.stderr


def svc_get_all():
    items = []
    out = _sc_output(["query", "type=", "service", "state=", "all"])
    for block in re.split(r"\n\s*\n", out):
        name_m = re.search(r"SERVICE_NAME:\s*(\S+)", block)
        disp_m = re.search(r"DISPLAY_NAME:\s*(.+)", block)
        start_m = re.search(r"\bSTART_TYPE\s+:\s+\d+\s+(\S+)", block)
        if not name_m:
            continue
        name = name_m.group(1)
        display = disp_m.group(1).strip() if disp_m else name
        start_state = start_m.group(1).strip() if start_m else "UNKNOWN"
        if name.lower() in ("rpcss", "rpc", "samss", "winlogon", "lsass",
                            "csrss", "smss", "wininit", "services"):
            continue
        items.append(StartupItem(
            name, f"服务名: {name}", "服务", name,
            enabled=(start_state != "DISABLED"),
            chinese_name=display,
            raw={"service_name": name, "start": start_state}))
    return items


def svc_disable(item):
    out = _sc_output(["config", item.raw["service_name"], "start=", "disabled"])
    if "失败" in out or "FAILED" in out:
        raise RuntimeError(f"禁用服务失败: {item.name}\n{out}")


def svc_enable(item):
    out = _sc_output(["config", item.raw["service_name"], "start=", "demand"])
    if "失败" in out or "FAILED" in out:
        raise RuntimeError(f"启用服务失败: {item.name}\n{out}")


def svc_delete(item):
    if not messagebox.askyesno("警告", f"确定要删除服务 [{item.name}] 吗？\n此操作不可恢复！"):
        return
    out = _sc_output(["delete", item.raw["service_name"]])
    if "失败" in out or "FAILED" in out:
        raise RuntimeError(f"删除服务失败: {item.name}\n{out}")


# ============================================================
#  三、计划任务管理
# ============================================================
def _schtasks(args):
    r = subprocess.run(["schtasks"] + args, capture_output=True, text=True,
                       encoding="gbk", errors="ignore")
    return r.stdout + r.stderr


def task_get_all():
    items = []
    out = _schtasks(["/Query", "/FO", "CSV", "/V"])
    if not out.strip():
        return items
    try:
        import csv, io
        reader = csv.reader(io.StringIO(out))
        header = next(reader, None)
        if not header:
            return items
        h = [x.strip().strip('"') for x in header]
        idx_task = h.index("TaskName") if "TaskName" in h else 1
        idx_status = h.index("Status") if "Status" in h else 2
        idx_cmd = h.index("Task To Run") if "Task To Run" in h else None
        idx_author = h.index("Author") if "Author" in h else None
        for row in reader:
            if len(row) <= max(idx_task, idx_status):
                continue
            name = row[idx_task].strip('"')
            status = row[idx_status].strip('"')
            cmd = row[idx_cmd].strip('"') if idx_cmd is not None and len(row) > idx_cmd else ""
            author = row[idx_author].strip('"') if idx_author is not None and len(row) > idx_author else ""
            if not name:
                continue
            friendly = name.rstrip("\\").split("\\")[-1] or name
            exe = extract_exe_path(cmd)
            desc = _get_file_description(exe) if exe else None
            items.append(StartupItem(
                name, cmd, "计划任务", name,
                enabled=(status.upper() != "DISABLED"),
                chinese_name=desc or author or friendly,
                exe_path=exe,
                raw={"status": status, "author": author}))
    except Exception:
        pass
    return items


def task_disable(item):
    out = _schtasks(["/Change", "/TN", item.location, "/Disable"])
    if "错误" in out or "ERROR" in out.upper():
        raise RuntimeError(f"禁用任务失败: {item.name}\n{out}")


def task_enable(item):
    out = _schtasks(["/Change", "/TN", item.location, "/Enable"])
    if "错误" in out or "ERROR" in out.upper():
        raise RuntimeError(f"启用任务失败: {item.name}\n{out}")


def task_delete(item):
    if not messagebox.askyesno("警告", f"确定要删除计划任务 [{item.name}] 吗？"):
        return
    out = _schtasks(["/Delete", "/TN", item.location, "/F"])
    if "错误" in out or "ERROR" in out.upper():
        raise RuntimeError(f"删除任务失败: {item.name}\n{out}")


# ============================================================
#  四、统一调度
# ============================================================
OPERATIONS = {
    "注册表":  {"list": reg_get_all,  "disable": reg_disable,  "enable": reg_enable,  "delete": reg_delete},
    "服务":    {"list": svc_get_all,  "disable": svc_disable,  "enable": svc_enable,  "delete": svc_delete},
    "计划任务": {"list": task_get_all, "disable": task_disable, "enable": task_enable, "delete": task_delete},
}


def get_all_items():
    all_items = []
    for src, ops in OPERATIONS.items():
        try:
            all_items += ops["list"]()
        except Exception as e:
            print(f"[警告] 获取 {src} 启动项失败: {e}")
    return all_items


# ============================================================
#  五、图形界面
# ============================================================
class StartupManagerGUI(tk.Tk):
    BG = "#f5f6fa"
    CARD = "#ffffff"
    ACCENT = "#4a6cf7"

    def __init__(self):
        super().__init__()
        self.title("启动项管理软件  v1.1")
        self.geometry("1080x640")
        self.configure(bg=self.BG)
        self.items = []
        self._img_refs = set()      # 防止 PhotoImage 被 GC
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        top = tk.Frame(self, bg=self.CARD, height=64)
        top.pack(fill="x")
        tk.Label(top, text="⚡ 启动项管理", font=("微软雅黑", 16, "bold"),
                 bg=self.CARD, fg="#2d3436").pack(side="left", padx=20, pady=12)
        self.lbl_status = tk.Label(top, text="", font=("微软雅黑", 9),
                                   bg=self.CARD, fg="#636e72")
        self.lbl_status.pack(side="right", padx=20)

        bar = tk.Frame(self, bg=self.BG)
        bar.pack(fill="x", padx=12, pady=8)
        btn_cfg = [("🔄 刷新", self.refresh), ("⛔ 永久禁用", self.disable_selected),
                   ("✅ 恢复启用", self.enable_selected), ("🗑 删除", self.delete_selected),
                   ("📂 打开文件位置", self.locate_file)]
        for text, cmd in btn_cfg:
            tk.Button(bar, text=text, command=cmd, font=("微软雅黑", 10),
                      bg=self.ACCENT, fg="white", relief="flat", padx=14, pady=4,
                      cursor="hand2", activebackground="#3a5be0").pack(side="left", padx=4)

        tk.Label(bar, text="搜索:", bg=self.BG, font=("微软雅黑", 10)).pack(side="left", padx=(20, 4))
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_: self._apply_filter())
        tk.Entry(bar, textvariable=self.var_search, font=("微软雅黑", 10),
                 width=24, relief="solid", bd=1).pack(side="left", ipady=2)

        tk.Label(bar, text="来源:", bg=self.BG, font=("微软雅黑", 10)).pack(side="left", padx=(16, 4))
        self.var_src = tk.StringVar(value="全部")
        cb = ttk.Combobox(bar, textvariable=self.var_src, values=["全部", "注册表", "服务", "计划任务"],
                          width=10, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda *_: self._apply_filter())

        frame = tk.Frame(self, bg=self.BG)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        cols = ("icon", "name", "chinese", "source", "status", "command", "location")
        heads = ["", "名称", "中文名称", "来源", "状态", "启动命令 / 路径", "位置"]
        widths = [36, 200, 180, 90, 80, 300, 230]
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=30, font=("微软雅黑", 9))
        style.configure("Treeview.Heading", font=("微软雅黑", 10, "bold"))
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w")
        self.tree.column("icon", width=36, anchor="center", stretch=False)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("enabled", foreground="#2d3436")
        self.tree.tag_configure("disabled", foreground="#b2bec3")
        self.tree.bind("<Button-3>", self._context_menu)

        tip = ("提示：右键菜单可快速操作｜中文名称取自 exe 版本信息（FileDescription）｜"
               "图标提取自程序文件，服务/任务使用默认标识｜禁用后重启不恢复，可随时重新启用")
        tk.Label(self, text=tip, bg=self.BG, fg="#95a5a6", font=("微软雅黑", 9),
                 wraplength=1020, justify="left").pack(fill="x", padx=14, pady=(0, 8))

    # ---------- 图标 ----------
    def _icon_for(self, item):
        if item.exe_path:
            img = get_exe_icon(item.exe_path)
            if img:
                self._img_refs.add(img)
                return img
        kind = {"服务": "service", "计划任务": "task"}.get(item.source, "unknown")
        img = get_fallback_icon(kind)
        self._img_refs.add(img)
        return img

    # ---------- 数据 ----------
    def refresh(self):
        self.lbl_status.config(text="正在扫描…")
        self.update()
        try:
            self.items = get_all_items()
        except Exception as e:
            messagebox.showerror("错误", f"扫描启动项失败:\n{e}")
        self._apply_filter()
        n_dis = sum(1 for i in self.items if not i.enabled)
        self.lbl_status.config(text=f"共 {len(self.items)} 项 ｜ 已禁用 {n_dis} 项")

    def _apply_filter(self):
        kw = self.var_search.get().strip().lower()
        src = self.var_src.get()
        self.tree.delete(*self.tree.get_children())
        for idx, it in enumerate(self.items):
            if src != "全部" and it.source != src:
                continue
            if kw and (kw not in it.name.lower()
                       and kw not in it.command.lower()
                       and kw not in it.chinese_name.lower()):
                continue
            status = "✔ 已启用" if it.enabled else "✖ 已禁用"
            tag = "enabled" if it.enabled else "disabled"
            self.tree.insert("", "end", iid=str(idx), image=self._icon_for(it),
                             values=("", it.name, it.chinese_name, it.source,
                                     status, it.command, it.location), tags=(tag,))

    def _selected_items(self):
        return [self.items[int(i)] for i in self.tree.selection()]

    # ---------- 操作 ----------
    def _do(self, action):
        selected = self._selected_items()
        if not selected:
            messagebox.showinfo("提示", "请先在列表中选择启动项")
            return
        ops_done, errors = 0, []
        for it in selected:
            try:
                OPERATIONS[it.source][action](it)
                ops_done += 1
            except Exception as e:
                errors.append(str(e))
        self.refresh()
        if errors:
            messagebox.showwarning("部分操作失败", f"成功 {ops_done} 项，失败 {len(errors)} 项：\n\n" + "\n".join(errors[:5]))
        else:
            action_cn = {"disable": "永久禁用", "enable": "恢复启用", "delete": "删除"}[action]
            messagebox.showinfo("完成", f"成功{action_cn} {ops_done} 个启动项")

    def disable_selected(self):
        if messagebox.askyesno("确认", "永久禁用选中的启动项？\n禁用后重启系统也不会自动恢复。"):
            self._do("disable")

    def enable_selected(self):
        self._do("enable")

    def delete_selected(self):
        self._do("delete")

    def locate_file(self):
        selected = self._selected_items()
        if not selected:
            return
        target = selected[0].exe_path or selected[0].command.strip('"')
        m = re.search(r'([A-Za-z]:[^"]+\.exe)', target)
        full = selected[0].exe_path or (m.group(1) if m else None)
        if full and os.path.exists(full):
            subprocess.run(["explorer", "/select,", full])
        else:
            messagebox.showinfo("提示", f"文件不存在或该项不是可执行文件路径")

    def _context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=0, font=("微软雅黑", 10))
        menu.add_command(label="永久禁用", command=self.disable_selected)
        menu.add_command(label="恢复启用", command=self.enable_selected)
        menu.add_command(label="删除", command=self.delete_selected)
        menu.add_separator()
        menu.add_command(label="复制命令", command=self._copy_cmd)
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_cmd(self):
        selected = self._selected_items()
        if selected:
            self.clipboard_clear()
            self.clipboard_append(selected[0].command)


# ============================================================
#  程序入口
# ============================================================
if __name__ == "__main__":
    if not is_admin():
        ans = messagebox.askyesno(
            "权限提示",
            "本程序涉及注册表 / 服务 / 计划任务的修改，需要管理员权限。\n\n是否以管理员身份重新启动？")
        if ans:
            run_as_admin()
        else:
            sys.exit(0)
    app = StartupManagerGUI()
    app.mainloop()
