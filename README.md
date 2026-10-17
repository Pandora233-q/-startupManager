# Startup Manager - Windows 启动项管理软件

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)](https://www.microsoft.com/windows/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

一款基于 Python + tkinter 开发的 Windows 启动项管理工具，支持对 **注册表启动项**、**系统服务**、**计划任务** 三大启动渠道进行统一的查看、启用、禁用和删除操作，附带图形化界面，无需命令行基础即可上手。

---

## 目录

- [功能特性](#功能特性)
- [运行环境](#运行环境)
- [快速开始](#快速开始)
- [界面说明](#界面说明)
- [核心功能详解](#核心功能详解)
  - [注册表启动项管理](#注册表启动项管理)
  - [系统服务管理](#系统服务管理)
  - [计划任务管理](#计划任务管理)
- [程序架构](#程序架构)
- [关键技术实现](#关键技术实现)
- [注意事项](#注意事项)
- [版本更新](#版本更新)

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 注册表启动项管理 | 扫描 HKCU / HKLM 下的 Run / RunOnce 键值，支持启用、禁用（永久）、删除 |
| 系统服务管理 | 通过 PowerShell CIM 接口管理 Win32_Service，支持启动/停止/禁用/启用/删除 |
| 计划任务管理 | 通过 schtasks 命令管理系统计划任务，支持启用、禁用、删除 |
| 程序图标提取 | 利用 Windows API 从 exe/dll 文件中提取图标，在树形列表中展示 |
| 文件描述读取 | 通过版本信息接口获取程序文件的 FileDescription（中文软件名） |
| 搜索与筛选 | 支持关键词搜索 + 来源类型筛选（注册表/服务/计划任务） |
| 右键菜单 | 右键快捷操作：禁用、启用、删除、复制命令 |
| 权限检测与提权 | 自动检测管理员权限，无权限时弹窗提示并以管理员身份重启 |
| 核心服务保护 | 内置安全名单，防止误删 rpcss、lsass 等关键系统服务 |

---

## 运行环境

- **操作系统**：Windows 7 及以上（推荐 Windows 10/11）
- **Python 版本**：Python 3.8 或以上
- **权限要求**：普通权限可运行查看；管理员权限可完全生效（禁用/删除操作需要）
- **外部依赖**：无（仅使用 Python 标准库）

> 程序仅依赖 Python 标准库（`tkinter`、`winreg`、`ctypes`、`subprocess` 等），无需 `pip install` 任何第三方包。

---

## 快速开始

```
# 1. 确保 Python 3.8+ 已安装并加入 PATH

# 2. 直接运行脚本
python startup_manager.py

# 3. 首次运行时弹窗询问是否以管理员身份运行，点击"是"即可获得完整功能
```

---

## 界面说明

程序启动后呈现以下界面布局：

```
┌─────────────────────────────────────────────────────────┐
│ ⚡ 启动项管理                              共 XX 项 | 已禁用 X 项 │
├─────────────────────────────────────────────────────────┤
│ [🔄 刷新] [⛔ 永久禁用] [✅ 恢复启用] [🗑 删除] [📂 打开文件位置] │
│ 搜索: [____________]  来源: [全部 ▼]                      │
├─────────────────────────────────────────────────────────┤
│ 名称 │ 中文名称 │ 来源 │ 状态 │ 启动命令/路径 │ 位置      │
│ ─────────────────────────────────────────────────────── │
│ 🟦 xxx  │ xxx    │ 注册表│ ✔已启用│ cmd...     │ HKCU\...  │
│ 🟩 xxx  │ xxx    │ 服务  │ ✖已禁用│ cmd...     │ ServiceName│
│ ...                                                                │
├─────────────────────────────────────────────────────────┤
│ 提示：右键菜单可快速操作｜禁用服务会同时停止其当前运行实例...   │
└─────────────────────────────────────────────────────────┘
```

**按钮说明：**

| 按钮 | 功能 |
|------|------|
| 🔄 刷新 | 重新扫描所有启动项 |
| ⛔ 永久禁用 | 将选中项设为禁用状态（重启后不会自动启动） |
| ✅ 恢复启用 | 恢复选中项的启用状态 |
| 🗑 删除 | 删除选中项（不可恢复，需二次确认） |
| 📂 打开文件位置 | 打开选中项对应 exe 文件所在的文件夹 |

---

## 核心功能详解

### 注册表启动项管理

程序扫描以下注册表路径中的启动项：

| 注册表路径 | 作用范围 |
|-----------|---------|
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | 当前用户 |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce` | 当前用户（一次性） |
| `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` | 所有用户 |
| `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce` | 所有用户（一次性） |
| `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run` | 所有用户（32位程序） |
| `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce` | 所有用户（32位，一次性） |

**禁用原理**：在注册表值名前添加 `_disabled_` 前缀标记，而非直接删除，以便可随时恢复。

### 系统服务管理

通过 PowerShell 的 CIM (Common Information Model) 接口管理 Windows 服务：

- **获取服务列表**：`Get-CimInstance Win32_Service` 一次性获取 Name、DisplayName、State、StartMode、PathName
- **禁用服务**：`Set-Service -StartupType Disabled` + `Stop-Service -Force`（同时停止运行中的实例）
- **启用服务**：`Set-Service -StartupType Manual`（恢复为手动启动，避免开机自启）
- **删除服务**：通过 `sc delete` 命令删除（需二次确认）

**安全防护**：内置核心服务黑名单（rpcss、rpc、samss、winlogon、lsass、csrss、smss、wininit、services），防止误操作导致系统无法启动。

### 计划任务管理

通过 Windows 任务计划程序（schtasks）管理计划任务：

- **获取任务列表**：`schtasks /Query /FO CSV /V` 获取详细任务信息
- **禁用任务**：`schtasks /Change /TN <任务名> /Disable`
- **启用任务**：`schtasks /Change /TN <任务名> /Enable`
- **删除任务**：`schtasks /Delete /TN <任务名> /F`（需二次确认）

---

## 程序架构

```
startup_manager.py
├── 数据结构
│   └── StartupItem          # 启动项数据模型
├── 权限检测
│   ├── is_admin()           # 检测是否管理员
│   └── run_as_admin()       # 以管理员身份重启
├── Windows API 工具
│   ├── _get_file_description()  # 读取 exe 文件描述
│   ├── get_exe_icon()           # 从 exe 提取图标
│   ├── get_fallback_icon()      # 生成默认图标
│   └── extract_exe_path()       # 解析 exe 路径
├── 注册表启动项管理
│   ├── reg_get_all()          # 获取所有注册表启动项
│   ├── reg_disable()          # 禁用启动项
│   ├── reg_enable()           # 启用启动项
│   └── reg_delete()           # 删除启动项
├── 系统服务管理
│   ├── svc_get_all()          # 获取所有服务
│   ├── svc_disable()          # 禁用服务
│   ├── svc_enable()           # 启用服务
│   └── svc_delete()           # 删除服务
├── 计划任务管理
│   ├── task_get_all()         # 获取所有计划任务
│   ├── task_disable()         # 禁用任务
│   ├── task_enable()          # 启用任务
│   └── task_delete()          # 删除任务
├── 统一调度
│   ├── OPERATIONS             # 操作映射字典
│   └── get_all_items()        # 获取全部启动项
└── 图形界面
    └── StartupManagerGUI      # tkinter GUI 主类
```

---

## 关键技术实现

### 纯 ctypes 图标提取

程序不依赖 PIL/Pillow 等第三方图像处理库，而是通过 Windows API 直接提取 exe 文件图标：

1. 调用 `Shell32.ExtractIconExW` 获取图标句柄
2. 使用 `Gdi32.CreateDIBSection` + `Gdi32.SelectObject` 创建兼容 DC
3. 调用 `User32.DrawIconEx` 绘制图标到内存位图
4. 读取像素数据并转换为 PNG 格式（手动构造 PNG 二进制流）
5. 通过 `tk.PhotoImage(data=base64)` 嵌入 tkinter 界面

### 权限提升机制

```
程序启动 → 检测管理员权限 → 有权限 → 启动GUI
                    ↓ 无权限
              弹窗询问是否提权 → 是 → ShellExecuteW(runas) → 新进程以管理员身份运行 → 旧进程退出
                                          → 否 → 退出程序
```

---

## 注意事项

1. **管理员权限**：普通权限下程序可正常运行和查看，但禁用/删除操作可能因权限不足而失败。建议始终以管理员身份运行。

2. **系统安全**：程序已内置核心服务保护机制，但删除计划任务和注册表启动项的操作**不可恢复**，操作前请确认目标项的安全性。

3. **服务禁用行为**：禁用服务时，程序会同时执行 `Set-Service -StartupType Disabled` 和 `Stop-Service -Force`，即不仅阻止开机自启，还会立即停止当前正在运行的服务实例。

4. **编码处理**：PowerShell 命令执行前设置 `[Console]::OutputEncoding=[System.Text.Encoding]::UTF8` 以解决中文输出乱码问题；schtasks 输出使用 GBK 编码解析以兼容 Windows 中文版。

5. **兼容性**：程序使用 `ctypes.windll` 调用 Windows API，仅适用于 32/64 位 Windows 系统，不支持 Windows Server 的非桌面版本（部分 GUI 组件可能不可用）。

---

## 版本更新

### v1.2（当前版本）

- 修复图标显示问题（改用树列 #0 显示）
- 服务管理改用 PowerShell CIM 接口（修复禁用失效问题）
- 优化程序图标提取逻辑，增加缓存机制

---

## 免责声明

本软件仅供学习和个人使用。使用本工具修改系统启动项、服务或计划任务可能影响系统稳定性，请谨慎操作。建议在操作前创建系统还原点。
