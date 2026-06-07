from __future__ import annotations

import json
import os
import queue
import re
import shutil
import smtplib
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .launcher import _python_command
from .modes import ModeSpec, PROJECT_ROOT, get_mode


RESEARCH_ROOT = PROJECT_ROOT / "modes" / "research"
CULTURE_ROOT = PROJECT_ROOT / "modes" / "culture"
WORKBENCH_SETTINGS = PROJECT_ROOT / "quanlan_dual_assistant_settings.json"
MODEL_DEFAULTS = PROJECT_ROOT / "quanlan_model_defaults.json"
RUNTIME_ROOT = PROJECT_ROOT / ".workbench_runtime"
RELEASE_STATE = PROJECT_ROOT / "release_channel_state.json"
RELEASE_UPDATES = PROJECT_ROOT / ".release_updates"


def _runtime_project_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    env_root = os.environ.get("XGN_ASSISTANT_PROJECT_ROOT")
    if env_root:
        roots.append(Path(env_root))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.append(exe_dir)
        if exe_dir.name.lower() == "xgn-assistant" and exe_dir.parent.name.lower() == "dist":
            roots.append(exe_dir.parent.parent)
    roots.append(PROJECT_ROOT)
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return tuple(unique)


RUNTIME_PROJECT_ROOTS = _runtime_project_roots()
SELF_OPTIMIZER_BOOK_CANDIDATE_FILES = (
    *(
        path
        for root in RUNTIME_PROJECT_ROOTS
        for path in (
            root / "modes" / "culture" / "outputs" / "self_optimizer" / "self_optimizer_book_candidates.json",
            root / ".workbench_runtime" / "self_optimizer" / "self_optimizer_book_candidates.json",
        )
    ),
    Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "xgn-assistant" / "self_optimizer" / "self_optimizer_book_candidates.json",
)

TEXT_ENGINE_OPTIONS = [
    "GPT-5.5",
    "GPT-5.4",
    "GPT-5.4 mini（快速）",
    "DeepSeek Chat（官方润色）",
    "Gemini 3 Flash Preview（推荐）",
    "Gemini 2.5 Flash（稳定）",
]
IMAGE_ENGINE_OPTIONS = [
    "生图专用｜GPT Image 2",
    "生图专用｜Gemini 3 Pro Image Preview",
    "生图专用｜Gemini 3.1 Flash Image Preview",
]
DEFAULT_RESEARCH_JOURNALS = (
    "Nature Neuroscience, Neuron, Nature, Science, Cell, Nature Methods, "
    "Nature Medicine, Brain, Journal of Neuroscience, PNAS, eLife"
)
CULTURE_STAGES = ("outline", "split_pdf", "episode_prompt", "script", "polish", "images", "postprocess", "split_assets")
KEY_FILES = {
    "openai": "openai_api_key.txt",
    "image": "image_api_key.txt",
    "gemini": "gemini_api_key.txt",
    "deepseek": "deepseek_api_key.txt",
}

KEY_LABELS = {
    "openai": "OpenAI/GPT Key",
    "image": "生图专用 Key",
    "gemini": "Gemini Key",
    "deepseek": "DeepSeek Key",
}

RESEARCH_ISSUE_DIR_RE = re.compile(r"^\d{8}(?:[（(]\d+[）)])?$")
RESEARCH_ISSUE_MARKERS = (
    "00_文献信息.json",
    "00_候选文献清单.json",
    "01_栏目素材.json",
    "02_口播台词.txt",
)
RESEARCH_ISSUE_OUTPUT_DIRS = ("visual_summaries", "cards", "platform_cards")
LOG_BUFFER_LIMIT = 600
LOG_QUEUE_LIMIT = 2000
LOG_POLL_BUSY_MS = 250
LOG_POLL_IDLE_MS = 900
LOG_POLL_BATCH_LIMIT = 80
SETTINGS_SAVE_DELAY_MS = 1000
ARTICLE_PREVIEW_LIMIT = 120
AUTO_CLIP_ASSET_PREVIEW_LIMIT = 160
AUTO_CLIP_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUTO_CLIP_LRC_EXTENSIONS = {".lrc"}
AUTO_CLIP_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac"}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def _write_text(path: Path, value: str) -> None:
    path.write_text(str(value or "").strip(), encoding="utf-8")


def _extract_chat_content(response) -> str:
    try:
        return str((response.choices[0].message.content or "")).strip()
    except Exception:
        pass
    if isinstance(response, dict):
        try:
            return str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
        except Exception:
            return ""
    if isinstance(response, str):
        text = response.strip()
        if not text:
            return ""
        if "chat.completion.chunk" not in text and '"choices"' not in text and not text.startswith("data:"):
            return text
        parts: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                content = delta.get("content") or message.get("content") or choice.get("text") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip()
    return ""


def _extract_response_content(response) -> str:
    direct = getattr(response, "output_text", "") or ""
    if str(direct).strip():
        return str(direct).strip()
    try:
        data = response.model_dump()
    except Exception:
        try:
            data = response if isinstance(response, dict) else json.loads(response.model_dump_json())
        except Exception:
            data = {}
    if isinstance(data, dict):
        output = data.get("output") or []
        parts: list[str] = []
        for item in output if isinstance(output, list) else []:
            for part in (item.get("content") or []) if isinstance(item, dict) else []:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("content") or ""))
        if parts:
            return "".join(parts).strip()
    return _extract_chat_content(response)


def _research_text_model_id(engine: str) -> str:
    value = str(engine or "").strip()
    lower = value.lower()
    if "gpt-5.5" in lower:
        return "gpt-5.5"
    if "gpt-5.4 mini" in lower:
        return "gpt-5.4-mini"
    if "gpt-5.4" in lower:
        return "gpt-5.4"
    if "deepseek" in lower:
        return "deepseek-chat"
    if "gemini 3" in lower:
        return "gemini-3.5-flash"
    if "gemini 2.5" in lower:
        return "gemini-2.5-flash"
    return value or "gpt-5.5"


def _provider_for_engine(engine: str) -> str:
    lower = str(engine or "").lower()
    if "deepseek" in lower:
        return "deepseek"
    if "gemini" in lower:
        return "gemini"
    return "openai"


def _image_model_id_for_choice(engine: str) -> str:
    value = str(engine or "").strip()
    lower = value.lower()
    if "gpt image 2" in lower or value == "GPT Image 2":
        return "gpt-image-2"
    if "gemini 3 pro" in lower:
        return "gemini-3-pro-image-preview"
    if "gemini 3.1" in lower:
        return "gemini-3.1-flash-image-preview"
    return "gpt-image-2"


def _normalize_research_image_choice(engine: str) -> str:
    value = str(engine or "").strip()
    lower = value.lower()
    if not value or "gpt image 2" in lower or value == "gpt-image-2":
        return "生图专用｜GPT Image 2"
    if "gemini 3 pro" in lower or value == "gemini-3-pro-image-preview":
        return "生图专用｜Gemini 3 Pro Image Preview"
    if "gemini 3.1" in lower or value == "gemini-3.1-flash-image-preview":
        return "生图专用｜Gemini 3.1 Flash Image Preview"
    if "imagen" in lower:
        return "生图专用｜Gemini 3 Pro Image Preview"
    return "生图专用｜GPT Image 2"


def _key_hint(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "未填写"
    return f"已填写({len(text)}位)"


class WindowsTrayIcon:
    """Small Windows notification-area icon for background running."""

    WM_TRAY = 0x8001
    ID_SHOW = 1001
    ID_EXIT = 1002

    def __init__(self, app: "UnifiedWorkbench") -> None:
        self.app = app
        self.enabled = sys.platform.startswith("win")
        self.installed = False
        self.hwnd = None
        self._nid = None
        self._class_name = "QuanlanPigletTrayWindow"
        self._wndproc = None
        self._ctypes = None
        self._wt = None
        self.last_error = ""
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._last_menu_at = 0.0
        self._icon_path = PROJECT_ROOT / "quanlan_dual_assistant" / "assets" / "app.ico"
        self._pystray_icon = None

    def _ensure_icon_file(self) -> str:
        icon_path = self._icon_path
        if icon_path.exists():
            return str(icon_path)
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        logo_path = RESEARCH_ROOT / "assets" / "logos" / "zh" / "logo_zh_tight.png"
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageOps

            base = Image.new("RGBA", (256, 256), (19, 64, 116, 255))
            draw = ImageDraw.Draw(base)
            draw.ellipse((20, 20, 236, 236), fill=(248, 252, 255, 255))
            draw.ellipse((34, 34, 222, 222), outline=(30, 104, 166, 255), width=10)
            if logo_path.exists():
                logo = Image.open(logo_path).convert("RGBA")
                logo = ImageOps.contain(logo, (176, 92), method=Image.Resampling.LANCZOS)
                base.alpha_composite(logo, ((256 - logo.width) // 2, 64))
            try:
                font = ImageFont.truetype("msyh.ttc", 84)
            except Exception:
                font = ImageFont.load_default()
            text = "脑"
            bbox = draw.textbbox((0, 0), text, font=font)
            tx = (256 - (bbox[2] - bbox[0])) // 2
            ty = 126
            draw.text((tx, ty), text, fill=(16, 57, 101, 255), font=font)
            base.save(icon_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            return str(icon_path)
        except Exception:
            return ""

    def install(self) -> bool:
        if not self.enabled or self.installed:
            return self.installed
        if self._install_pystray():
            return True
        if self._thread is not None and self._thread.is_alive():
            return self.installed
        self.last_error = ""
        self._ready.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_message_loop, daemon=True)
        self._thread.start()
        self._ready.wait(3.0)
        if not self.installed and not self.last_error:
            self._set_error("托盘线程启动超时，Shell 通知区未返回初始化结果")
        return self.installed

    def _install_pystray(self) -> bool:
        if getattr(sys, "frozen", False) and os.environ.get("XGN_ASSISTANT_USE_PYSTRAY") != "1":
            self.last_error = "frozen exe uses native Windows tray"
            return False
        try:
            import pystray
            from PIL import Image
        except Exception as exc:
            self.last_error = f"pystray not available: {exc}"
            return False
        if self._thread is not None and self._thread.is_alive():
            return self.installed
        try:
            icon_path = self._ensure_icon_file()
            image = Image.open(icon_path) if icon_path else Image.new("RGBA", (64, 64), (19, 64, 116, 255))
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", lambda icon, item: self.app._post_tray_action("show"), default=True),
                pystray.MenuItem("退出程序", lambda icon, item: self.app._post_tray_action("exit_force")),
            )
            self._pystray_icon = pystray.Icon("quanlan_piglet", image, "很有脑子的小猪理", menu)
            self._thread = threading.Thread(target=self._pystray_icon.run, daemon=True)
            self._thread.start()
            self.installed = True
            self.last_error = ""
            return True
        except Exception as exc:
            self._pystray_icon = None
            self.installed = False
            self.last_error = f"pystray failed: {type(exc).__name__}: {exc}"
            return False

    def _set_error(self, message: str) -> None:
        self.last_error = str(message or "").strip()

    def _run_message_loop(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes as wt

            self._ctypes = ctypes
            self._wt = wt
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32
            LRESULT = getattr(wt, "LRESULT", ctypes.c_longlong)
            HICON = getattr(wt, "HICON", wt.HANDLE)
            HCURSOR = getattr(wt, "HCURSOR", wt.HANDLE)
            HBRUSH = getattr(wt, "HBRUSH", wt.HANDLE)
            HINSTANCE = getattr(wt, "HINSTANCE", wt.HANDLE)
            UINT_PTR = getattr(wt, "UINT_PTR", wt.WPARAM)
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
            hmenu_type = getattr(wt, "HMENU", wt.HWND)
            WM_CLOSE = 0x0010
            WM_DESTROY = 0x0002
            WM_LBUTTONUP = 0x0202
            WM_LBUTTONDBLCLK = 0x0203
            WM_RBUTTONDOWN = 0x0204
            WM_RBUTTONUP = 0x0205
            WM_CONTEXTMENU = 0x007B
            WM_NULL = 0x0000
            NIN_SELECT = 0x0400
            NIN_KEYSELECT = 0x0401
            NIM_ADD = 0x00000000
            NIM_DELETE = 0x00000002
            NIM_SETVERSION = 0x00000004
            NOTIFYICON_VERSION_4 = 4
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x00000010
            TPM_RIGHTBUTTON = 0x0002
            TPM_RETURNCMD = 0x0100
            TPM_NONOTIFY = 0x0080

            def win_error() -> int:
                try:
                    return int(kernel32.GetLastError())
                except Exception:
                    return 0

            kernel32.GetModuleHandleW.restype = HINSTANCE
            kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
            user32.DefWindowProcW.restype = LRESULT
            user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            user32.RegisterClassW.restype = wt.ATOM if hasattr(wt, "ATOM") else ctypes.c_ushort
            user32.CreateWindowExW.restype = wt.HWND
            user32.CreateWindowExW.argtypes = [
                wt.DWORD,
                wt.LPCWSTR,
                wt.LPCWSTR,
                wt.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wt.HWND,
                hmenu_type,
                HINSTANCE,
                wt.LPVOID,
            ]
            user32.LoadIconW.restype = HICON
            user32.LoadImageW.restype = HICON
            user32.LoadImageW.argtypes = [HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
            user32.DestroyWindow.restype = wt.BOOL
            user32.DestroyWindow.argtypes = [wt.HWND]
            user32.PostQuitMessage.restype = None
            user32.PostQuitMessage.argtypes = [ctypes.c_int]
            user32.PostMessageW.restype = wt.BOOL
            user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wt.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", HINSTANCE),
                    ("hIcon", HICON),
                    ("hCursor", HCURSOR),
                    ("hbrBackground", HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR),
                ]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.DWORD),
                    ("hWnd", wt.HWND),
                    ("uID", wt.UINT),
                    ("uFlags", wt.UINT),
                    ("uCallbackMessage", wt.UINT),
                    ("hIcon", HICON),
                    ("szTip", wt.WCHAR * 128),
                    ("dwState", wt.DWORD),
                    ("dwStateMask", wt.DWORD),
                    ("szInfo", wt.WCHAR * 256),
                    ("uVersion", wt.UINT),
                    ("szInfoTitle", wt.WCHAR * 64),
                    ("dwInfoFlags", wt.DWORD),
                    ("guidItem", ctypes.c_byte * 16),
                    ("hBalloonIcon", HICON),
                ]

            shell32.Shell_NotifyIconW.restype = wt.BOOL
            shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wt.HWND),
                    ("message", wt.UINT),
                    ("wParam", wt.WPARAM),
                    ("lParam", wt.LPARAM),
                    ("time", wt.DWORD),
                    ("pt", wt.POINT),
                ]

            user32.GetMessageW.restype = ctypes.c_int
            user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT]
            user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
            user32.CreatePopupMenu.restype = hmenu_type
            user32.AppendMenuW.restype = wt.BOOL
            user32.AppendMenuW.argtypes = [hmenu_type, wt.UINT, UINT_PTR, wt.LPCWSTR]
            user32.TrackPopupMenu.restype = wt.UINT
            user32.TrackPopupMenu.argtypes = [hmenu_type, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
            user32.DestroyMenu.restype = wt.BOOL
            user32.DestroyMenu.argtypes = [hmenu_type]
            user32.GetCursorPos.restype = wt.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
            user32.SetForegroundWindow.restype = wt.BOOL
            user32.SetForegroundWindow.argtypes = [wt.HWND]

            def delete_icon() -> None:
                if self._nid is None:
                    return
                try:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                except Exception:
                    pass

            def wndproc(hwnd, msg, wparam, lparam):
                try:
                    if msg == self.WM_TRAY:
                        event = int(lparam)
                        if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK, NIN_SELECT, NIN_KEYSELECT):
                            self.app._post_tray_action("show")
                            return 0
                        if event in (WM_RBUTTONDOWN, WM_RBUTTONUP, WM_CONTEXTMENU):
                            self._show_menu(hwnd)
                            return 0
                    if msg == WM_CLOSE:
                        user32.DestroyWindow(hwnd)
                        return 0
                    if msg == WM_DESTROY:
                        delete_icon()
                        self.installed = False
                        user32.PostQuitMessage(0)
                        return 0
                except Exception:
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc = WNDPROC(wndproc)
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                err = win_error()
                if err not in (0, 1410):  # ERROR_CLASS_ALREADY_EXISTS is harmless here.
                    self._set_error(f"RegisterClassW failed，Win32错误码={err}")
            self.hwnd = user32.CreateWindowExW(0, self._class_name, self._class_name, 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                self._set_error(f"CreateWindowExW failed，Win32错误码={win_error()}")
                self._ready.set()
                return

            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = 0x0001 | 0x0002 | 0x0004  # NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = self.WM_TRAY
            icon_path = self._ensure_icon_file()
            icon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE) if icon_path else None
            nid.hIcon = icon or user32.LoadIconW(None, ctypes.c_void_p(32512))  # fallback: IDI_APPLICATION
            nid.szTip = "很有脑子的小猪理"
            self._nid = nid
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self._set_error(f"Shell_NotifyIconW(NIM_ADD) failed，Win32错误码={win_error()}")
                user32.DestroyWindow(self.hwnd)
                self._ready.set()
                return
            nid.uVersion = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
            self.installed = True
            self.last_error = ""
            self._ready.set()

            msg = MSG()
            while not self._stop.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._set_error(f"{type(exc).__name__}: {exc}")
            self.enabled = False
            self._ready.set()
        finally:
            if self.installed and self._ctypes is not None and self._nid is not None:
                try:
                    self._ctypes.windll.shell32.Shell_NotifyIconW(0x00000002, self._ctypes.byref(self._nid))
                except Exception:
                    pass
            self.installed = False

    def _show_menu(self, hwnd) -> None:
        ctypes = self._ctypes
        wt = self._wt
        if ctypes is None or wt is None:
            return
        now = time.monotonic()
        if now - self._last_menu_at < 0.35:
            return
        self._last_menu_at = now
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0x0000, self.ID_SHOW, "显示主窗口")
        user32.AppendMenuW(menu, 0x0800, 0, None)
        user32.AppendMenuW(menu, 0x0000, self.ID_EXIT, "退出程序")
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(menu, 0x0100 | 0x0002, pt.x, pt.y, 0, hwnd, None)
        try:
            user32.PostMessageW(hwnd, 0x0000, 0, 0)  # WM_NULL closes the transient popup menu cleanly.
        except Exception:
            pass
        user32.DestroyMenu(menu)
        if cmd == self.ID_SHOW:
            self.app._post_tray_action("show")
        elif cmd == self.ID_EXIT:
            self.app._post_tray_action("exit_force")

    def shutdown(self) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._pystray_icon is not None:
            try:
                self._pystray_icon.stop()
            except Exception:
                pass
            self._pystray_icon = None
        try:
            if self._ctypes is not None and self.hwnd:
                self._ctypes.windll.user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self.installed = False


class UnifiedWorkbench(tk.Tk):
    def __init__(self, initial_mode: str = "research") -> None:
        super().__init__()
        self.title("很有脑子的小猪理")
        self.geometry("1260x820")
        self.minsize(1120, 720)
        self.configure(bg="#f4f6f8")

        self.active_task = tk.StringVar(value="culture" if initial_mode == "culture" else "research_digest")
        self.log_queue: queue.Queue[tuple[str, str] | str] = queue.Queue()
        self.log_buffers: dict[str, list[str]] = {
            "research_digest": [],
            "science_classic": [],
            "culture": [],
            "auto_clip": [],
            "learning_books": [],
        }
        self.log_last_ts: dict[str, float] = {}
        self.running_processes: dict[str, subprocess.Popen | None] = {}
        self.running_labels: dict[str, str] = {}
        self.last_output_dir = tk.StringVar(value="")
        self.last_research_output_dir = tk.StringVar(value="")
        self.last_science_output_dir = tk.StringVar(value="")
        self.last_culture_output_dir = tk.StringVar(value="")
        self.last_auto_clip_output_dir = tk.StringVar(value="")
        self.article_list_preview: scrolledtext.ScrolledText | None = None
        self.auto_clip_assets_list: tk.Listbox | None = None
        self.learning_books_tree: ttk.Treeview | None = None
        self.learning_books_detail: scrolledtext.ScrolledText | None = None
        self._loading_settings = False
        self._key_entries: dict[str, ttk.Entry] = {}
        self._exiting = False
        self._settings_save_after_id: str | None = None
        self._tray_icon: WindowsTrayIcon | None = None
        self._tray_actions: queue.Queue[str] = queue.Queue()

        self._init_vars()
        self._load_existing_config()
        self._bind_persistent_vars()
        self._build_style()
        self._build_ui()
        self._render_task_page()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._tray_icon = WindowsTrayIcon(self)
        try:
            icon_path = self._tray_icon._ensure_icon_file()
            if icon_path:
                self.iconbitmap(icon_path)
        except Exception:
            pass
        if self._tray_icon.install():
            self._put_log("[系统] 已启用右下角托盘后台运行：关闭窗口会隐藏到托盘，任务继续运行。", task_key=self.active_task.get())
        else:
            detail = self._tray_icon.last_error or "未返回具体错误"
            self._put_log(f"[系统] 托盘图标初始化失败：{detail}；关闭窗口时会再次尝试。", task_key=self.active_task.get())
        self._write_release_state()
        self.after(2500, self._try_release_idle_upgrade)
        self.after(200, self._poll_tray_actions)
        self.after(LOG_POLL_BUSY_MS, self._poll_logs)

    def _init_vars(self) -> None:
        self.research_days = tk.StringVar(value="14")
        self.research_max_articles = tk.StringVar(value="5")
        self.research_issue_count = tk.StringVar(value="1")
        self.research_issue_no = tk.StringVar(value="1")
        self.research_journal_fuzzy = tk.StringVar(value="")
        self.research_journals = tk.StringVar(value="")
        self.research_out_dir = tk.StringVar(value="")
        self.research_resume_dir = tk.StringVar(value="")
        self.research_article_list = tk.StringVar(value="")
        self.research_skip_image_api = tk.BooleanVar(value=False)

        self.science_pdf = tk.StringVar(value="")
        self.science_out_dir = tk.StringVar(value="")
        self.science_flow_parse = tk.BooleanVar(value=True)
        self.science_flow_script = tk.BooleanVar(value=True)
        self.science_flow_image = tk.BooleanVar(value=True)
        self.science_redraw = tk.BooleanVar(value=False)

        self.culture_book = tk.StringVar(value="")
        self.culture_out_dir = tk.StringVar(value="")
        self.culture_continue_folder = tk.StringVar(value="")
        self.culture_auto_resume = tk.BooleanVar(value=True)
        self.culture_skip_existing_text = tk.BooleanVar(value=True)
        self.culture_skip_existing_images = tk.BooleanVar(value=True)
        self.culture_skip_images = tk.BooleanVar(value=False)
        self.culture_only_postprocess = tk.BooleanVar(value=False)
        self.culture_no_split_assets = tk.BooleanVar(value=False)
        self.culture_start_stage = tk.StringVar(value="outline")
        self.culture_test_b_limit = tk.StringVar(value="0")

        self.auto_clip_image_dir = tk.StringVar(value="")
        self.auto_clip_lrc_dir = tk.StringVar(value="")
        self.auto_clip_output_dir = tk.StringVar(value="")

        self.text_engine = tk.StringVar(value="GPT-5.5")
        self.polish_engine = tk.StringVar(value="DeepSeek Chat（官方润色）")
        self.image_engine = tk.StringVar(value="生图专用｜GPT Image 2")
        self.culture_text_provider = tk.StringVar(value="openai")
        self.culture_text_model = tk.StringVar(value="gpt-5.5")
        self.culture_polish_provider = tk.StringVar(value="deepseek")
        self.culture_polish_model = tk.StringVar(value="deepseek-v4-pro")
        self.culture_image_provider = tk.StringVar(value="openai")
        self.culture_image_model = tk.StringVar(value="gpt-image-2")
        self.foreign_base_url = tk.StringVar(value="https://greatwalllink.top/v1")
        self.deepseek_base_url = tk.StringVar(value="https://api.deepseek.com")
        self.key_vars = {name: tk.StringVar(value="") for name in KEY_FILES}

        self.email_enabled = tk.BooleanVar(value=False)
        self.email_recipient = tk.StringVar(value="")
        self.smtp_host = tk.StringVar(value="smtp.qq.com")
        self.smtp_port = tk.StringVar(value="465")
        self.smtp_user = tk.StringVar(value="")
        self.smtp_sender = tk.StringVar(value="")
        self.smtp_password = tk.StringVar(value="")
        self.smtp_ssl = tk.BooleanVar(value=True)
        self.smtp_tls = tk.BooleanVar(value=False)

    def _load_existing_config(self) -> None:
        self._loading_settings = True
        scheme = _read_json(RESEARCH_ROOT / "quanlan_model_scheme.json")
        self.text_engine.set(str(scheme.get("text_engine") or self.text_engine.get()))
        self.polish_engine.set(str(scheme.get("review_engine") or self.polish_engine.get()))
        self.image_engine.set(_normalize_research_image_choice(str(scheme.get("image_engine") or self.image_engine.get())))
        self.email_enabled.set(bool(scheme.get("email_after_completion", False)))
        self.email_recipient.set(str(scheme.get("email_recipient") or ""))

        for key_name, file_name in KEY_FILES.items():
            for root in (RESEARCH_ROOT, CULTURE_ROOT):
                value = _read_text(root / file_name)
                if value:
                    self.key_vars[key_name].set(value)
                    break

        email = _read_json(RESEARCH_ROOT / "quanlan_email_settings.json")
        if not email:
            run_switch = _read_json(CULTURE_ROOT / "config" / "运行开关.json")
            email = dict((run_switch.get("email_delivery") or {}) if isinstance(run_switch.get("email_delivery"), dict) else {})
            if email:
                email = {
                    "smtp_host": email.get("smtp_host") or "",
                    "smtp_port": email.get("smtp_port") or 465,
                    "smtp_user": email.get("username") or "",
                    "smtp_from": email.get("from") or "",
                    "smtp_ssl": email.get("use_ssl", True),
                    "smtp_tls": False,
                }
        self.smtp_host.set(str(email.get("smtp_host") or self.smtp_host.get()))
        self.smtp_port.set(str(email.get("smtp_port") or self.smtp_port.get()))
        self.smtp_user.set(str(email.get("smtp_user") or ""))
        self.smtp_sender.set(str(email.get("smtp_from") or email.get("smtp_user") or ""))
        self.smtp_ssl.set(bool(email.get("smtp_ssl", True)))
        self.smtp_tls.set(bool(email.get("smtp_tls", False)))
        password = _read_text(RESEARCH_ROOT / "smtp_password.txt") or _read_text(CULTURE_ROOT / "smtp_password.txt")
        if password:
            self.smtp_password.set(password)
        self._load_workbench_settings()
        self._load_model_defaults()
        self._loading_settings = False

    def _model_defaults_payload(self) -> dict:
        return {
            "text_engine": self.text_engine.get(),
            "polish_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "culture_text_provider": self.culture_text_provider.get(),
            "culture_text_model": self.culture_text_model.get(),
            "culture_polish_provider": self.culture_polish_provider.get(),
            "culture_polish_model": self.culture_polish_model.get(),
            "culture_image_provider": self.culture_image_provider.get(),
            "culture_image_model": self.culture_image_model.get(),
            "foreign_base_url": self.foreign_base_url.get(),
            "deepseek_base_url": self.deepseek_base_url.get(),
            "keys": {name: var.get().strip() for name, var in self.key_vars.items() if var.get().strip()},
        }

    def _apply_model_defaults_payload(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        for name in (
            "text_engine", "polish_engine", "image_engine",
            "culture_text_provider", "culture_text_model",
            "culture_polish_provider", "culture_polish_model",
            "culture_image_provider", "culture_image_model",
            "foreign_base_url", "deepseek_base_url",
        ):
            if name in data and hasattr(self, name):
                value = str(data.get(name) or getattr(self, name).get())
                if name == "image_engine":
                    value = _normalize_research_image_choice(value)
                getattr(self, name).set(value)
        keys = data.get("keys")
        if isinstance(keys, dict):
            for key_name, value in keys.items():
                if key_name in self.key_vars and str(value or "").strip():
                    self.key_vars[key_name].set(str(value).strip())
        self._refresh_key_status()

    def _load_model_defaults(self) -> None:
        self._apply_model_defaults_payload(_read_json(MODEL_DEFAULTS))

    def _save_model_defaults_with_log(self) -> None:
        _write_json(MODEL_DEFAULTS, self._model_defaults_payload())
        self._save_model_config(log=False)
        self._put_log("模型默认配置和当前 Key 已保存；下次启动会自动加载。")

    def _load_model_defaults_with_log(self) -> None:
        data = _read_json(MODEL_DEFAULTS)
        if not data:
            self._put_log("尚未保存模型默认配置。")
            return
        self._apply_model_defaults_payload(data)
        self._save_model_config(log=False)
        self._save_workbench_settings()
        self._put_log("已加载模型默认配置。")

    def _load_workbench_settings(self) -> None:
        data = _read_json(WORKBENCH_SETTINGS)
        self.active_task.set(str(data.get("active_task") or self.active_task.get()))
        self.research_out_dir.set(str(data.get("research_out_dir") or self.research_out_dir.get()))
        self.research_resume_dir.set(str(data.get("research_resume_dir") or self.research_resume_dir.get()))
        self.research_article_list.set(str(data.get("research_article_list") or self.research_article_list.get()))
        self.research_journal_fuzzy.set(str(data.get("research_journal_fuzzy") or self.research_journal_fuzzy.get()))
        saved_journals = self._clean_journal_list(str(data.get("research_journals") or ""))
        self.research_journals.set(saved_journals or self.research_journals.get())
        self.science_pdf.set(str(data.get("science_pdf") or self.science_pdf.get()))
        self.science_out_dir.set(str(data.get("science_out_dir") or self.science_out_dir.get()))
        self.culture_book.set(str(data.get("culture_book") or self.culture_book.get()))
        self.culture_out_dir.set(str(data.get("culture_out_dir") or self.culture_out_dir.get()))
        self.culture_continue_folder.set(str(data.get("culture_continue_folder") or self.culture_continue_folder.get()))
        self.auto_clip_image_dir.set(str(data.get("auto_clip_image_dir") or self.auto_clip_image_dir.get()))
        self.auto_clip_lrc_dir.set(str(data.get("auto_clip_lrc_dir") or self.auto_clip_lrc_dir.get()))
        self.auto_clip_output_dir.set(str(data.get("auto_clip_output_dir") or self.auto_clip_output_dir.get()))
        legacy_last = str(data.get("last_output_dir") or self.last_output_dir.get())
        self.last_output_dir.set(legacy_last)
        self.last_research_output_dir.set(str(data.get("last_research_output_dir") or self.research_out_dir.get() or self.last_research_output_dir.get()))
        self.last_science_output_dir.set(str(data.get("last_science_output_dir") or self.science_out_dir.get() or self.last_science_output_dir.get()))
        self.last_culture_output_dir.set(str(data.get("last_culture_output_dir") or self.culture_out_dir.get() or self.culture_continue_folder.get() or self.last_culture_output_dir.get()))
        self.last_auto_clip_output_dir.set(str(data.get("last_auto_clip_output_dir") or self.auto_clip_output_dir.get() or self.last_auto_clip_output_dir.get()))
        for name in (
            "research_days", "research_max_articles", "research_issue_count", "research_issue_no",
            "text_engine", "polish_engine", "image_engine",
            "culture_text_provider", "culture_text_model",
            "culture_polish_provider", "culture_polish_model",
            "culture_image_provider", "culture_image_model",
            "foreign_base_url", "deepseek_base_url",
        ):
            if name in data and hasattr(self, name):
                value = str(data.get(name) or getattr(self, name).get())
                if name == "image_engine":
                    value = _normalize_research_image_choice(value)
                getattr(self, name).set(value)

    def _persistent_settings_payload(self) -> dict:
        return {
            "active_task": self.active_task.get(),
            "research_days": self.research_days.get(),
            "research_max_articles": self.research_max_articles.get(),
            "research_issue_count": self.research_issue_count.get(),
            "research_issue_no": self.research_issue_no.get(),
            "research_journal_fuzzy": self.research_journal_fuzzy.get(),
            "research_journals": self._clean_journal_list(self.research_journals.get()),
            "research_out_dir": self.research_out_dir.get(),
            "research_resume_dir": self.research_resume_dir.get(),
            "research_article_list": self.research_article_list.get(),
            "science_pdf": self.science_pdf.get(),
            "science_out_dir": self.science_out_dir.get(),
            "culture_book": self.culture_book.get(),
            "culture_out_dir": self.culture_out_dir.get(),
            "culture_continue_folder": self.culture_continue_folder.get(),
            "auto_clip_image_dir": self.auto_clip_image_dir.get(),
            "auto_clip_lrc_dir": self.auto_clip_lrc_dir.get(),
            "auto_clip_output_dir": self.auto_clip_output_dir.get(),
            "text_engine": self.text_engine.get(),
            "polish_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "culture_text_provider": self.culture_text_provider.get(),
            "culture_text_model": self.culture_text_model.get(),
            "culture_polish_provider": self.culture_polish_provider.get(),
            "culture_polish_model": self.culture_polish_model.get(),
            "culture_image_provider": self.culture_image_provider.get(),
            "culture_image_model": self.culture_image_model.get(),
            "foreign_base_url": self.foreign_base_url.get(),
            "deepseek_base_url": self.deepseek_base_url.get(),
            "last_output_dir": self.last_output_dir.get(),
            "last_research_output_dir": self.last_research_output_dir.get(),
            "last_science_output_dir": self.last_science_output_dir.get(),
            "last_culture_output_dir": self.last_culture_output_dir.get(),
            "last_auto_clip_output_dir": self.last_auto_clip_output_dir.get(),
        }

    def _save_workbench_settings(self) -> None:
        if self._loading_settings:
            return
        self._settings_save_after_id = None
        _write_json(WORKBENCH_SETTINGS, self._persistent_settings_payload())

    def _schedule_workbench_settings_save(self) -> None:
        if self._loading_settings:
            return
        if self._settings_save_after_id:
            try:
                self.after_cancel(self._settings_save_after_id)
            except Exception:
                pass
        self._settings_save_after_id = self.after(SETTINGS_SAVE_DELAY_MS, self._save_workbench_settings)

    def _is_task_running(self, task_key: str) -> bool:
        return task_key in self.running_processes

    def _is_any_task_running(self) -> bool:
        return bool(self.running_processes)

    def _release_state_payload(self) -> dict:
        active = [key for key, proc in self.running_processes.items() if proc is not None or key in self.running_labels]
        previous = _read_json(RELEASE_STATE)
        return {
            **previous,
            "channel": str(previous.get("channel") or os.environ.get("XGN_ASSISTANT_CHANNEL") or "dev"),
            "busy": bool(active),
            "active_tasks": active,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _write_release_state(self) -> None:
        try:
            _write_json(RELEASE_STATE, self._release_state_payload())
        except Exception:
            pass

    def _has_pending_release_update(self) -> bool:
        pending = _read_json(RELEASE_UPDATES / "pending_update.json")
        path = Path(str(pending.get("path") or ""))
        return bool(pending and path.exists())

    def _try_release_idle_upgrade(self) -> None:
        self._write_release_state()
        if self._is_any_task_running() or not self._has_pending_release_update():
            return
        script = PROJECT_ROOT / "tools" / "channel_manager.py"
        if not script.exists():
            return
        cmd = [sys.executable, str(script), "apply-pending-update"]
        try:
            completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            message = (completed.stdout or completed.stderr or "").strip()
            if completed.returncode == 0 and "已升级" in message:
                self._put_log(f"[系统] 发布版已在空闲时自动升级：{message}", task_key=self.active_task.get())
                self._put_log("[系统] 建议任务结束后重启发布版窗口，让新代码完全生效。", task_key=self.active_task.get())
            elif message and "没有待升级包" not in message:
                self._put_log(f"[系统] 发布版升级检查：{message}", task_key=self.active_task.get())
        except Exception as exc:
            self._put_log(f"[系统] 发布版自动升级检查失败：{type(exc).__name__}: {exc}", task_key=self.active_task.get())

    def _runtime_dir(self, task_key: str) -> Path:
        path = RUNTIME_ROOT / re.sub(r"[^A-Za-z0-9_.-]+", "_", task_key or "task")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _email_config_snapshot(self) -> tuple[dict, dict] | None:
        try:
            port = int(str(self.smtp_port.get()).strip() or "465")
        except Exception:
            messagebox.showwarning("端口无效", "SMTP 端口必须是数字。")
            return None
        host = self.smtp_host.get().strip()
        user = self.smtp_user.get().strip()
        sender = self.smtp_sender.get().strip() or user
        password = self.smtp_password.get().strip()
        recipients = [x.strip() for x in self.email_recipient.get().replace("，", ",").split(",") if x.strip()]
        research_email = {
            "smtp_host": host,
            "smtp_port": port,
            "smtp_user": user,
            "smtp_password": password,
            "smtp_from": sender,
            "smtp_ssl": bool(self.smtp_ssl.get()),
            "smtp_tls": bool(self.smtp_tls.get()),
            "note": "Runtime snapshot generated by the unified workbench.",
        }
        culture_email = {
            "enabled": bool(self.email_enabled.get()),
            "smtp_host": host,
            "smtp_port": port,
            "use_ssl": bool(self.smtp_ssl.get()),
            "username": user,
            "from": sender,
            "to": recipients,
            "password_env": "AMP_SMTP_PASSWORD",
            "password_file": "",
            "max_attachment_mb": 500,
            "subject_template": "素材生成完成：{part_name}",
        }
        return research_email, culture_email

    def _research_model_scheme_snapshot(self) -> dict:
        scheme = _read_json(RESEARCH_ROOT / "quanlan_model_scheme.json")
        scheme.update({
            "text_engine": self.text_engine.get(),
            "review_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "content_style": "科学经典解读",
            "call_mode": "API自动调用",
            "email_after_completion": bool(self.email_enabled.get()),
            "email_recipient": self.email_recipient.get().strip(),
        })
        return scheme

    def _runtime_env(
        self,
        task_key: str,
        *,
        model_scheme: dict | None = None,
        task_page_settings: dict | None = None,
        email_snapshot: bool = True,
    ) -> dict | None:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        key_env = {
            "openai": ("OPENAI_API_KEY",),
            "image": ("IMAGE_API_KEY", "OPENAI_IMAGE_API_KEY"),
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "deepseek": ("DEEPSEEK_API_KEY",),
        }
        for key_name, env_names in key_env.items():
            value = self.key_vars[key_name].get().strip()
            if value:
                for env_name in env_names:
                    env[env_name] = value
        env["NEWAPI_BASE_URL"] = self._normalized_foreign_base_url()
        env["FOREIGN_MODEL_BASE_URL"] = env["NEWAPI_BASE_URL"]
        env["DEEPSEEK_BASE_URL"] = self.deepseek_base_url.get().strip() or "https://api.deepseek.com"
        password = self.smtp_password.get().strip()
        if password:
            env["AMP_SMTP_PASSWORD"] = password

        runtime_dir = self._runtime_dir(task_key)
        cache_dir = runtime_dir / "cache"
        temp_dir = runtime_dir / "temp"
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        env["QUANLAN_TASK_RUNTIME_DIR"] = str(runtime_dir)
        env["QUANLAN_TASK_CACHE_DIR"] = str(cache_dir)
        env["XDG_CACHE_HOME"] = str(cache_dir / "xdg")
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        if model_scheme is not None:
            path = runtime_dir / "quanlan_model_scheme.json"
            _write_json(path, model_scheme)
            env["QUANLAN_MODEL_SCHEME_FILE"] = str(path)
        if task_page_settings is not None:
            path = runtime_dir / "quanlan_task_page_settings.json"
            _write_json(path, task_page_settings)
            env["QUANLAN_TASK_PAGE_SETTINGS_FILE"] = str(path)
        if email_snapshot:
            snapshots = self._email_config_snapshot()
            if snapshots is None:
                return None
            research_email, culture_email = snapshots
            email_path = runtime_dir / "quanlan_email_settings.json"
            _write_json(email_path, research_email)
            env["QUANLAN_EMAIL_DELIVERY_SETTINGS_FILE"] = str(email_path)

            run_switch = _read_json(CULTURE_ROOT / "config" / "运行开关.json")
            run_switch["email_delivery"] = culture_email
            run_switch_path = runtime_dir / "运行开关.json"
            _write_json(run_switch_path, run_switch)
            env["QUANLAN_CULTURE_RUN_SWITCH_FILE"] = str(run_switch_path)
        return env

    def _bind_persistent_vars(self) -> None:
        vars_to_bind = [
            self.active_task,
            self.research_days, self.research_max_articles, self.research_issue_count, self.research_issue_no,
            self.research_journal_fuzzy, self.research_journals, self.research_out_dir, self.research_resume_dir, self.research_article_list,
            self.science_pdf, self.science_out_dir,
            self.culture_book, self.culture_out_dir, self.culture_continue_folder,
            self.auto_clip_image_dir, self.auto_clip_lrc_dir, self.auto_clip_output_dir,
            self.text_engine, self.polish_engine, self.image_engine,
            self.culture_text_provider, self.culture_text_model,
            self.culture_polish_provider, self.culture_polish_model,
            self.culture_image_provider, self.culture_image_model,
            self.foreign_base_url, self.deepseek_base_url,
            self.last_output_dir, self.last_research_output_dir, self.last_science_output_dir, self.last_culture_output_dir, self.last_auto_clip_output_dir,
        ]
        for var in vars_to_bind:
            var.trace_add("write", lambda *_: self._schedule_workbench_settings_save())

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("Root.TFrame", background="#f4f6f8")
        style.configure("Side.TFrame", background="#18202b")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("SideTitle.TLabel", background="#18202b", foreground="#ffffff", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("SideBody.TLabel", background="#18202b", foreground="#c7d0dc")
        style.configure("Title.TLabel", background="#f4f6f8", foreground="#151b24", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#151b24", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("Subtle.TLabel", background="#ffffff", foreground="#606a78")
        style.configure("Mode.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(12, 10))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(12, 8))
        style.configure("Tool.TButton", padding=(10, 6))
        style.configure("TCheckbutton", background="#ffffff")

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame")
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        side = ttk.Frame(root, style="Side.TFrame", padding=18)
        side.grid(row=0, column=0, sticky="ns")
        ttk.Label(side, text="很有脑子的小猪理", style="SideTitle.TLabel").pack(anchor="w")
        ttk.Label(side, text="任务、模型、邮箱统一配置；按场景切换展示", style="SideBody.TLabel", wraplength=190).pack(anchor="w", pady=(8, 20))
        ttk.Button(side, text="科研速递", style="Mode.TButton", command=lambda: self._set_task("research_digest")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="科学经典解读", style="Mode.TButton", command=lambda: self._set_task("science_classic")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="文史小秘", style="Mode.TButton", command=lambda: self._set_task("culture")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="自动剪辑", style="Mode.TButton", command=lambda: self._set_task("auto_clip")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="学习书单/PDF", style="Mode.TButton", command=lambda: self._set_task("learning_books")).pack(fill="x")
        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=20)
        ttk.Button(side, text="打开输出目录", style="Tool.TButton", command=self._open_current_output_dir).pack(fill="x", pady=(0, 8))
        ttk.Button(side, text="清空目标文件夹", style="Tool.TButton", command=self._clear_current_output_dir).pack(fill="x", pady=(0, 8))
        ttk.Button(side, text="高级配置", style="Tool.TButton", command=self._open_advanced_config).pack(fill="x", pady=(0, 8))
        ttk.Button(side, text="停止当前任务", style="Tool.TButton", command=self._stop_process).pack(fill="x")

        main = ttk.Frame(root, style="Root.TFrame", padding=(18, 18, 18, 14))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        header = ttk.Frame(main, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(header, text="", style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.status_label = ttk.Label(header, text="空闲", background="#f4f6f8", foreground="#687384")
        self.status_label.grid(row=0, column=1, sticky="e")

        body = ttk.Frame(main, style="Root.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=0)
        body.rowconfigure(1, weight=1)

        self.task_page = ttk.Frame(body, style="Panel.TFrame", padding=18)
        self.task_page.grid(row=0, column=0, sticky="ew")
        self.task_page.columnconfigure(1, weight=1)

        log_panel = ttk.Frame(body, style="Panel.TFrame", padding=12)
        log_panel.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        log_header = ttk.Frame(log_panel, style="Panel.TFrame")
        log_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        log_header.columnconfigure(0, weight=1)
        self.log_title_label = ttk.Label(log_header, text="运行日志", style="PanelTitle.TLabel")
        self.log_title_label.grid(row=0, column=0, sticky="w")
        ttk.Button(log_header, text="清空", style="Tool.TButton", command=self._clear_log).grid(row=0, column=1, sticky="e")
        self.log_box = scrolledtext.ScrolledText(log_panel, height=16, wrap="word", font=("Consolas", 10), bg="#10151d", fg="#e6edf5", insertbackground="#e6edf5")
        self.log_box.grid(row=1, column=0, sticky="nsew")

    def _build_model_page(self) -> None:
        ttk.Label(self.model_page, text="模型方案", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._combo_row(self.model_page, 1, "科研/科学经典 文案模型", self.text_engine, TEXT_ENGINE_OPTIONS)
        self._combo_row(self.model_page, 2, "科研/科学经典 润色模型", self.polish_engine, ["跟随脚本模型", *TEXT_ENGINE_OPTIONS])
        self._combo_row(self.model_page, 3, "科研/科学经典 生图模型", self.image_engine, IMAGE_ENGINE_OPTIONS)
        self._combo_row(self.model_page, 4, "文史文本 Provider", self.culture_text_provider, ("openai", "gemini", "deepseek", "dry-run"))
        self._entry_row(self.model_page, 5, "文史文本模型", self.culture_text_model, width=28)
        self._combo_row(self.model_page, 6, "文史润色 Provider", self.culture_polish_provider, ("deepseek", "openai", "gemini", "dry-run"))
        self._entry_row(self.model_page, 7, "文史润色模型", self.culture_polish_model, width=28)
        self._combo_row(self.model_page, 8, "文史生图 Provider", self.culture_image_provider, ("openai", "gemini", "none", "dry-run"))
        self._entry_row(self.model_page, 9, "文史生图模型", self.culture_image_model, width=28)
        self._entry_row(self.model_page, 10, "国外模型中转 URL", self.foreign_base_url)
        self._entry_row(self.model_page, 11, "DeepSeek 官方 URL", self.deepseek_base_url)

        ttk.Label(self.model_page, text="Key 文件", style="PanelTitle.TLabel").grid(row=12, column=0, columnspan=3, sticky="w", pady=(16, 8))
        row = 13
        for key_name, label in KEY_LABELS.items():
            self._key_row(row, label, key_name)
            row += 1
        actions = ttk.Frame(self.model_page, style="Panel.TFrame")
        actions.grid(row=row, column=1, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="保存模型配置和 Key", style="Primary.TButton", command=self._save_model_config_with_log).pack(side="left")
        ttk.Button(actions, text="保存为默认配置", style="Tool.TButton", command=self._save_model_defaults_with_log).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="加载默认配置", style="Tool.TButton", command=self._load_model_defaults_with_log).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="测试文本模型", style="Tool.TButton", command=self._test_text_model).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="测试绘图模型", style="Tool.TButton", command=self._test_image_model).pack(side="left", padx=(10, 0))
        tests = ttk.Frame(self.model_page, style="Panel.TFrame")
        tests.grid(row=row + 1, column=1, sticky="ew", pady=(10, 0))
        for text, command in [
            ("测文史文本", lambda: self._test_named_model("culture_text")),
            ("测文史润色", lambda: self._test_named_model("culture_polish")),
            ("测文史生图", lambda: self._test_named_model("culture_image")),
            ("测科研文本", lambda: self._test_named_model("research_text")),
            ("测科研润色", lambda: self._test_named_model("research_polish")),
            ("测科研生图", lambda: self._test_named_model("research_image")),
        ]:
            ttk.Button(tests, text=text, style="Tool.TButton", command=command).pack(side="left", padx=(0, 8), pady=(0, 6))
        ttk.Label(
            self.model_page,
            text="默认配置会保存模型选择、Base URL 和当前 Key 到 quanlan_model_defaults.json；下次启动自动加载。",
            style="Subtle.TLabel",
        ).grid(row=row + 2, column=1, sticky="w", pady=(8, 0))
        self._refresh_key_status()

    def _build_email_page(self) -> None:
        ttk.Label(self.email_page, text="邮箱发送", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Checkbutton(self.email_page, text="任务完成后压缩并发送邮件", variable=self.email_enabled).grid(row=1, column=1, sticky="w", pady=6)
        self._entry_row(self.email_page, 2, "收件邮箱", self.email_recipient)
        self._entry_row(self.email_page, 3, "SMTP 服务器", self.smtp_host, width=34)
        self._entry_row(self.email_page, 4, "端口", self.smtp_port, width=12)
        self._entry_row(self.email_page, 5, "登录账号", self.smtp_user, width=34)
        self._entry_row(self.email_page, 6, "发件人", self.smtp_sender, width=34)
        self._password_row(self.email_page, 7, "SMTP 授权码", self.smtp_password, "smtp")
        switches = ttk.Frame(self.email_page, style="Panel.TFrame")
        switches.grid(row=8, column=1, sticky="w", pady=6)
        ttk.Checkbutton(switches, text="SSL", variable=self.smtp_ssl).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(switches, text="TLS", variable=self.smtp_tls).pack(side="left")
        actions = ttk.Frame(self.email_page, style="Panel.TFrame")
        actions.grid(row=9, column=1, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="QQ 邮箱预设", style="Tool.TButton", command=self._apply_qq_email_preset).pack(side="left")
        ttk.Button(actions, text="保存邮箱配置", style="Primary.TButton", command=self._save_email_config_with_log).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="测试 SMTP", style="Tool.TButton", command=self._test_email).pack(side="left", padx=(10, 0))
        ttk.Label(
            self.email_page,
            text="授权码只写入本合并工程的配置文件，用于 SMTP 登录；日志不会显示授权码。",
            style="Subtle.TLabel",
        ).grid(row=10, column=1, sticky="w", pady=(10, 0))

    def _open_advanced_config(self) -> None:
        win = tk.Toplevel(self)
        win.title("高级配置")
        win.geometry("980x700")
        win.minsize(900, 620)
        win.configure(bg="#f4f6f8")
        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=14, pady=14)
        self.task_settings_page = ttk.Frame(notebook, style="Panel.TFrame", padding=18)
        self.model_page = ttk.Frame(notebook, style="Panel.TFrame", padding=18)
        self.email_page = ttk.Frame(notebook, style="Panel.TFrame", padding=18)
        self.task_settings_page.columnconfigure(1, weight=1)
        self.model_page.columnconfigure(1, weight=1)
        self.email_page.columnconfigure(1, weight=1)
        self._key_entries = {}
        self._build_task_settings_page()
        self._build_model_page()
        self._build_email_page()
        notebook.add(self.task_settings_page, text="任务参数")
        notebook.add(self.model_page, text="模型配置与测试")
        notebook.add(self.email_page, text="邮箱配置与测试")

    def _build_task_settings_page(self) -> None:
        ttk.Label(self.task_settings_page, text="科研速递参数", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_settings_page, 1, "检索天数", self.research_days, width=12)
        self._entry_row(self.task_settings_page, 2, "文章数量", self.research_max_articles, width=12)
        ttk.Checkbutton(self.task_settings_page, text="跳过图片 API，仅生成本地占位图", variable=self.research_skip_image_api).grid(row=3, column=1, sticky="w", pady=6)

        ttk.Label(self.task_settings_page, text="科学经典解读流程", style="PanelTitle.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(18, 8))
        science = ttk.Frame(self.task_settings_page, style="Panel.TFrame")
        science.grid(row=5, column=1, sticky="w", pady=6)
        for text, var in [("切章节/解析", self.science_flow_parse), ("生成脚本/LRC", self.science_flow_script), ("生成配图", self.science_flow_image), ("强制重绘配图", self.science_redraw)]:
            ttk.Checkbutton(science, text=text, variable=var).pack(side="left", padx=(0, 14))

        ttk.Label(self.task_settings_page, text="文史小秘参数", style="PanelTitle.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(18, 8))
        self._combo_row(self.task_settings_page, 7, "起始阶段", self.culture_start_stage, CULTURE_STAGES)
        self._entry_row(self.task_settings_page, 8, "测试 B 图数", self.culture_test_b_limit, width=12)
        culture = ttk.Frame(self.task_settings_page, style="Panel.TFrame")
        culture.grid(row=9, column=1, sticky="w", pady=6)
        for text, var in [
            ("自动断点续跑", self.culture_auto_resume),
            ("复用已有文本", self.culture_skip_existing_text),
            ("复用已有图片", self.culture_skip_existing_images),
            ("跳过生图", self.culture_skip_images),
            ("只做后处理", self.culture_only_postprocess),
            ("不生成拆分素材", self.culture_no_split_assets),
        ]:
            ttk.Checkbutton(culture, text=text, variable=var).pack(side="left", padx=(0, 14))

    def _set_task(self, task_key: str) -> None:
        self.active_task.set(task_key)
        self._render_task_page()
        self._render_current_log()

    def _render_task_page(self) -> None:
        for child in self.task_page.winfo_children():
            child.destroy()
        task = self.active_task.get()
        title_map = {
            "research_digest": "科研助手｜科研速递",
            "science_classic": "科研助手｜科学经典解读",
            "culture": "文史小秘｜书籍解读",
            "auto_clip": "小猪理｜自动剪辑",
            "learning_books": "自优化器｜学习书单/PDF",
        }
        self.title_label.configure(text=title_map.get(task, "很有脑子的小猪理"))
        if hasattr(self, "log_title_label"):
            self.log_title_label.configure(text=f"运行日志｜{title_map.get(task, '当前模式')}")
        if task == "research_digest":
            self._render_research_digest()
        elif task == "science_classic":
            self._render_science_classic()
        elif task == "auto_clip":
            self._render_auto_clip()
        elif task == "learning_books":
            self._render_learning_books()
        else:
            self._render_culture()

    def _render_research_digest(self) -> None:
        ttk.Label(self.task_page, text="科研速递", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "输出目录", self.research_out_dir, browse=lambda: self._browse_dir(self.research_out_dir))
        issue_row = ttk.Frame(self.task_page, style="Panel.TFrame")
        issue_row.grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(self.task_page, text="每日期数", background="#ffffff").grid(row=2, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Combobox(issue_row, textvariable=self.research_issue_count, values=("1", "2", "3"), state="readonly", width=8).pack(side="left")
        ttk.Label(issue_row, text="本期序号", background="#ffffff").pack(side="left", padx=(14, 6))
        ttk.Combobox(issue_row, textvariable=self.research_issue_no, values=("1", "2", "3"), state="readonly", width=8).pack(side="left")
        self._entry_row(self.task_page, 3, "杂志需求", self.research_journal_fuzzy)
        self._entry_row(self.task_page, 4, "期刊列表", self.research_journals)
        self._entry_row(self.task_page, 5, "文献清单", self.research_article_list, browse=self._browse_article_list)
        self._entry_row(self.task_page, 6, "断档续作目录", self.research_resume_dir, browse=lambda: self._browse_dir(self.research_resume_dir))
        actions = ttk.Frame(self.task_page, style="Panel.TFrame")
        actions.grid(row=7, column=1, sticky="ew", pady=(14, 0))
        ttk.Button(actions, text="GPT 梳理期刊", style="Tool.TButton", command=self._normalize_journals_with_gpt).pack(side="left")
        ttk.Button(actions, text="补文献清单", style="Tool.TButton", command=self._build_research_article_list).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="从清单制作素材", style="Primary.TButton", command=self._run_research_digest_continue_list).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="续作档期", style="Tool.TButton", command=self._resume_research_digest_issue).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="刷新清单", style="Tool.TButton", command=self._refresh_article_list_preview).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="重置进度", style="Tool.TButton", command=self._reset_research_article_progress).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="停止", style="Tool.TButton", command=self._stop_process).pack(side="left", padx=(10, 0))
        ttk.Label(
            self.task_page,
            text="先补文献清单，再从清单制作素材；续作档期请选择某一期文件夹，如 20260605（1），不是“科研速递”总目录。",
            style="Subtle.TLabel",
        ).grid(row=8, column=1, sticky="w", pady=(8, 0))
        ttk.Label(self.task_page, text="文献清单预览", style="PanelTitle.TLabel").grid(row=9, column=0, columnspan=3, sticky="w", pady=(18, 8))
        self.article_list_preview = scrolledtext.ScrolledText(self.task_page, height=12, wrap="word", font=("Consolas", 9))
        self.article_list_preview.grid(row=10, column=0, columnspan=3, sticky="nsew")
        self.task_page.rowconfigure(10, weight=1)
        self._refresh_article_list_preview()

    def _render_science_classic(self) -> None:
        ttk.Label(self.task_page, text="科学经典解读", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "书籍/论文 PDF", self.science_pdf, browse=lambda: self._browse_file(self.science_pdf, [("PDF", "*.pdf"), ("All files", "*.*")]))
        self._entry_row(self.task_page, 2, "输出目录", self.science_out_dir, browse=lambda: self._browse_dir(self.science_out_dir))
        self._action_row(self.task_page, 3, [("启动科学经典解读", self._run_science_classic), ("测试 B 图", self._test_science_classic_b_image), ("停止", self._stop_process)])
        ttk.Label(self.task_page, text="流程开关、模型、邮箱和测试放在左侧“高级配置”。", style="Subtle.TLabel").grid(row=4, column=1, sticky="w", pady=(8, 0))

    def _render_culture(self) -> None:
        ttk.Label(self.task_page, text="文史小秘", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "书籍 PDF", self.culture_book, browse=lambda: self._browse_file(self.culture_book, [("PDF", "*.pdf"), ("All files", "*.*")]))
        self._entry_row(self.task_page, 2, "输出目录", self.culture_out_dir, browse=lambda: self._browse_dir(self.culture_out_dir))
        self._entry_row(self.task_page, 3, "续跑目录", self.culture_continue_folder, browse=lambda: self._browse_dir(self.culture_continue_folder))
        self._action_row(self.task_page, 4, [("开始文史生成", self._run_culture), ("测试 B 图", self._test_culture_b_image), ("停止", self._stop_process)])
        ttk.Label(self.task_page, text="起始阶段、复用、生图、后处理、模型、邮箱和测试放在左侧“高级配置”。", style="Subtle.TLabel").grid(row=5, column=1, sticky="w", pady=(8, 0))

    def _render_auto_clip(self) -> None:
        ttk.Label(self.task_page, text="自动剪辑", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "图片素材文件夹", self.auto_clip_image_dir, browse=lambda: self._browse_auto_clip_dir(self.auto_clip_image_dir))
        self._entry_row(self.task_page, 2, "LRC 素材文件夹", self.auto_clip_lrc_dir, browse=lambda: self._browse_auto_clip_dir(self.auto_clip_lrc_dir))
        self._entry_row(self.task_page, 3, "输出文件夹", self.auto_clip_output_dir, browse=lambda: self._browse_dir(self.auto_clip_output_dir))
        self._action_row(
            self.task_page,
            4,
            [
                ("开始自动剪辑", self._run_auto_clip),
                ("打开输出目录", lambda: self._open_path(self.auto_clip_output_dir.get())),
                ("刷新素材列表", self._refresh_auto_clip_assets_preview),
                ("停止", self._stop_process),
            ],
        )
        ttk.Label(
            self.task_page,
            text="LRC 每行可写 【B26】 或 B26；程序会在图片文件名里匹配同名编号，并为每个 LRC 输出一个 MP4 和字幕 SRT。",
            style="Subtle.TLabel",
        ).grid(row=5, column=1, sticky="w", pady=(8, 0))
        ttk.Label(self.task_page, text="已收集素材", style="PanelTitle.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(18, 8))
        preview_frame = ttk.Frame(self.task_page, style="Panel.TFrame")
        preview_frame.grid(row=7, column=0, columnspan=3, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.auto_clip_assets_list = tk.Listbox(preview_frame, height=11, font=("Consolas", 10))
        self.auto_clip_assets_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=self.auto_clip_assets_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.auto_clip_assets_list.configure(yscrollcommand=scrollbar.set)
        self.task_page.rowconfigure(7, weight=1)
        self._refresh_auto_clip_assets_preview()

    def _render_learning_books(self) -> None:
        ttk.Label(self.task_page, text="学习书单/PDF", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        actions = ttk.Frame(self.task_page, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        ttk.Button(actions, text="刷新书单状态", style="Primary.TButton", command=self._refresh_learning_books).pack(side="left")
        ttk.Button(actions, text="打开PDF目录", style="Tool.TButton", command=self._open_learning_pdf_dir).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="打开报告文件", style="Tool.TButton", command=self._open_learning_book_candidates_file).pack(side="left", padx=(10, 0))
        ttk.Label(
            self.task_page,
            text="这里显示自优化器查阅到的候选书单：已找到/已下载的 PDF 会显示路径；还没有 PDF 的会标记缺失或需要合法来源。",
            style="Subtle.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 8))
        columns = ("status", "category", "title", "author", "pdf")
        self.learning_books_tree = ttk.Treeview(self.task_page, columns=columns, show="headings", height=14)
        headings = {
            "status": "PDF状态",
            "category": "类别",
            "title": "书名",
            "author": "作者",
            "pdf": "PDF/原因",
        }
        widths = {"status": 110, "category": 120, "title": 180, "author": 160, "pdf": 420}
        for key in columns:
            self.learning_books_tree.heading(key, text=headings[key])
            self.learning_books_tree.column(key, width=widths[key], anchor="w")
        self.learning_books_tree.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.learning_books_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_learning_book_detail())
        ttk.Label(self.task_page, text="选中书籍详情", style="PanelTitle.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(14, 6))
        self.learning_books_detail = scrolledtext.ScrolledText(self.task_page, height=8, wrap="word", font=("Microsoft YaHei UI", 10))
        self.learning_books_detail.grid(row=5, column=0, columnspan=3, sticky="nsew")
        self.task_page.rowconfigure(3, weight=3)
        self.task_page.rowconfigure(5, weight=1)
        self._refresh_learning_books()

    def _entry_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, width: int | None = None, browse=None) -> None:
        ttk.Label(parent, text=label, background="#ffffff").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Entry(parent, textvariable=var, width=width or 72).grid(row=row, column=1, sticky="ew", pady=6)
        if browse:
            ttk.Button(parent, text="选择", style="Tool.TButton", command=browse).grid(row=row, column=2, sticky="e", padx=(10, 0), pady=6)

    def _combo_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, values) -> None:
        ttk.Label(parent, text=label, background="#ffffff").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Combobox(parent, textvariable=var, values=tuple(values), state="readonly", width=34).grid(row=row, column=1, sticky="w", pady=6)

    def _password_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, key: str) -> None:
        ttk.Label(parent, text=label, background="#ffffff").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        entry = ttk.Entry(parent, textvariable=var, show="*", width=72)
        entry.grid(row=row, column=1, sticky="ew", pady=6)
        self._key_entries[key] = entry
        ttk.Button(parent, text="显示/隐藏", style="Tool.TButton", command=lambda k=key: self._toggle_secret(k)).grid(row=row, column=2, sticky="e", padx=(10, 0), pady=6)

    def _key_row(self, row: int, label: str, key_name: str) -> None:
        self._password_row(self.model_page, row, label, self.key_vars[key_name], key_name)
        status = ttk.Label(self.model_page, text="", background="#ffffff", foreground="#687384")
        status.grid(row=row, column=3, sticky="w", padx=(10, 0))
        setattr(self, f"{key_name}_status_label", status)

    def _action_row(self, parent: ttk.Frame, row: int, buttons: list[tuple[str, object]]) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=1, sticky="ew", pady=(14, 0))
        for index, (text, command) in enumerate(buttons):
            ttk.Button(frame, text=text, style="Primary.TButton" if index == 0 else "Tool.TButton", command=command).pack(side="left", padx=(0 if index == 0 else 10, 0))

    def _browse_file(self, var: tk.StringVar, filetypes) -> None:
        value = filedialog.askopenfilename(filetypes=filetypes)
        if value:
            var.set(value)
            self._save_workbench_settings()

    def _browse_article_list(self) -> None:
        self._browse_file(self.research_article_list, [("JSON", "*.json"), ("All files", "*.*")])
        self._refresh_article_list_preview()

    def _browse_dir(self, var: tk.StringVar) -> None:
        value = filedialog.askdirectory()
        if value:
            var.set(value)
            self._save_workbench_settings()

    def _browse_auto_clip_dir(self, var: tk.StringVar) -> None:
        self._browse_dir(var)
        self._refresh_auto_clip_assets_preview()

    def _preview_files(self, folder: str, extensions: set[str], label: str) -> list[str]:
        root = Path(str(folder or "").strip())
        if not root.is_dir():
            return [f"{label}: 未选择或目录不存在"]
        files = sorted(
            (path for path in root.iterdir() if path.is_file() and path.suffix.lower() in extensions),
            key=lambda path: path.name.lower(),
        )
        rows = [f"{label}: {len(files)} 个  {root}"]
        for path in files[:AUTO_CLIP_ASSET_PREVIEW_LIMIT]:
            rows.append(f"  - {path.name}")
        if len(files) > AUTO_CLIP_ASSET_PREVIEW_LIMIT:
            rows.append(f"  ... 还有 {len(files) - AUTO_CLIP_ASSET_PREVIEW_LIMIT} 个未显示")
        return rows

    def _refresh_auto_clip_assets_preview(self) -> None:
        if self.auto_clip_assets_list is None:
            return
        rows: list[str] = []
        rows.extend(self._preview_files(self.auto_clip_image_dir.get(), AUTO_CLIP_IMAGE_EXTENSIONS, "图片素材"))
        rows.append("")
        rows.extend(self._preview_files(self.auto_clip_lrc_dir.get(), AUTO_CLIP_LRC_EXTENSIONS, "LRC 素材"))
        rows.append("")
        rows.extend(self._preview_files(self.auto_clip_lrc_dir.get(), AUTO_CLIP_AUDIO_EXTENSIONS, "同目录音频"))
        self.auto_clip_assets_list.delete(0, "end")
        for row in rows:
            self.auto_clip_assets_list.insert("end", row)

    def _book_candidates_file(self) -> Path | None:
        for path in SELF_OPTIMIZER_BOOK_CANDIDATE_FILES:
            if path.exists():
                return path
        return None

    def _load_learning_books_payload(self) -> dict:
        path = self._book_candidates_file()
        if not path:
            return {}
        return _read_json(path)

    def _book_status_label(self, item: dict) -> str:
        status = str(item.get("pdf_status") or "")
        download = str(item.get("download_status") or "")
        if status == "found":
            return "已找到"
        if status == "downloaded":
            return "已下载"
        if download == "legal_source_required":
            return "缺合法PDF源"
        if status == "missing_pdf":
            return "未找到PDF"
        return status or download or "未知"

    def _book_pdf_summary(self, item: dict) -> str:
        matches = item.get("pdf_matches") if isinstance(item.get("pdf_matches"), list) else []
        if matches:
            return str(matches[0])
        download = item.get("download_result") if isinstance(item.get("download_result"), dict) else {}
        reason = str(download.get("reason") or item.get("download_status") or "")
        if reason == "legal_source_required":
            return "没有配置合法公开 PDF 下载源"
        if reason:
            return reason
        return "等待自优化器继续查找"

    def _refresh_learning_books(self) -> None:
        if self.learning_books_tree is None:
            return
        payload = self._load_learning_books_payload()
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        self.learning_books_tree.delete(*self.learning_books_tree.get_children())
        if not candidates:
            self.learning_books_tree.insert("", "end", values=("暂无书单", "", "请先启动自优化器学习", "", "未找到 self_optimizer_book_candidates.json"))
            self._set_learning_book_detail("还没有发现自优化器书单文件。\n\n通常启动“去学习吧”或 run_self_optimizer.bat 后，会生成 self_optimizer_book_candidates.json。")
            return
        for index, item in enumerate(candidates):
            if not isinstance(item, dict):
                continue
            self.learning_books_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    self._book_status_label(item),
                    str(item.get("category") or ""),
                    str(item.get("title") or ""),
                    str(item.get("author") or ""),
                    self._book_pdf_summary(item),
                ),
            )
        source = self._book_candidates_file()
        scan = payload.get("pdf_scan") if isinstance(payload.get("pdf_scan"), dict) else {}
        self._set_learning_book_detail(
            "\n".join([
                f"书单文件：{source or '未找到'}",
                f"更新时间：{payload.get('updated_at') or '未知'}",
                f"扫描PDF数量：{scan.get('scanned_pdfs', 0)}",
                f"已匹配/下载：{scan.get('matched', 0)}",
                f"未找到PDF：{scan.get('missing_pdf', 0)}",
                f"需要合法来源：{scan.get('legal_source_required', 0)}",
            ])
        )

    def _set_learning_book_detail(self, text: str) -> None:
        if self.learning_books_detail is None:
            return
        self.learning_books_detail.configure(state="normal")
        self.learning_books_detail.delete("1.0", "end")
        self.learning_books_detail.insert("1.0", text)
        self.learning_books_detail.configure(state="disabled")

    def _show_learning_book_detail(self) -> None:
        if self.learning_books_tree is None:
            return
        selected = self.learning_books_tree.selection()
        if not selected:
            return
        payload = self._load_learning_books_payload()
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        try:
            item = candidates[int(selected[0])]
        except Exception:
            return
        if not isinstance(item, dict):
            return
        matches = item.get("pdf_matches") if isinstance(item.get("pdf_matches"), list) else []
        source_pages = item.get("legal_source_pages") if isinstance(item.get("legal_source_pages"), list) else []
        searches = item.get("search_queries") if isinstance(item.get("search_queries"), list) else []
        lines = [
            f"书名：{item.get('title') or ''}",
            f"作者：{item.get('author') or ''}",
            f"类别：{item.get('category') or ''}",
            f"PDF状态：{self._book_status_label(item)}",
            f"PDF路径：{matches[0] if matches else '暂无'}",
            "",
            f"推荐切入角度：{item.get('future_angle') or ''}",
            f"入选原因：{item.get('reason') or ''}",
            f"版权/来源状态：{item.get('source_status') or '未知'}",
            "",
            "合法来源页：",
            *(f"  {value}" for value in source_pages[:8]),
            "",
            "后续搜索词：",
            *(f"  {value}" for value in searches[:8]),
        ]
        self._set_learning_book_detail("\n".join(lines))

    def _open_learning_book_candidates_file(self) -> None:
        path = self._book_candidates_file()
        if not path:
            messagebox.showinfo("暂无书单", "还没有找到 self_optimizer_book_candidates.json。")
            return
        self._open_path(str(path.parent))

    def _open_learning_pdf_dir(self) -> None:
        payload = self._load_learning_books_payload()
        scan = payload.get("pdf_scan") if isinstance(payload.get("pdf_scan"), dict) else {}
        for key in ("download_dir", "download_fallback_dir", "download_temp_dir"):
            value = str(scan.get(key) or "").strip()
            if value and Path(value).exists():
                self._open_path(value)
                return
        messagebox.showinfo("暂无PDF目录", "还没有找到自优化器下载 PDF 的目录。")

    def _open_path(self, path: str) -> None:
        value = str(path or "").strip()
        if not value:
            messagebox.showinfo("没有输出目录", "还没有可打开的输出目录。")
            return
        target = Path(value)
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror("无法打开目录", str(exc))

    def _last_output_var_for_task(self, task: str = "") -> tk.StringVar:
        key = str(task or self.active_task.get() or "").strip()
        if key == "research_digest":
            return self.last_research_output_dir
        if key == "science_classic":
            return self.last_science_output_dir
        if key == "culture":
            return self.last_culture_output_dir
        if key == "auto_clip":
            return self.last_auto_clip_output_dir
        return self.last_output_dir

    def _set_last_output_for_task(self, task: str, path: str) -> None:
        value = str(path or "").strip()
        if not value:
            return
        self._last_output_var_for_task(task).set(value)
        self.last_output_dir.set(value)

    def _current_output_dir(self) -> str:
        task = self.active_task.get()
        if task == "research_digest":
            return self._research_daily_out_dir()
        if task == "science_classic":
            return self.science_out_dir.get().strip()
        if task == "culture":
            return self.culture_out_dir.get().strip() or self.culture_continue_folder.get().strip()
        if task == "auto_clip":
            return self.auto_clip_output_dir.get().strip()
        return self.last_output_dir.get().strip()

    def _open_current_output_dir(self) -> None:
        current_last = self._last_output_var_for_task().get().strip()
        self._open_path(current_last or self._current_output_dir())

    def _is_safe_clear_target(self, target: Path) -> bool:
        try:
            resolved = target.resolve()
        except Exception:
            resolved = target.absolute()
        forbidden = {
            PROJECT_ROOT.resolve(),
            RESEARCH_ROOT.resolve(),
            CULTURE_ROOT.resolve(),
            Path("D:/Quanlan/Codes/Python").resolve(),
        }
        if resolved in forbidden:
            return False
        if resolved.parent == resolved:
            return False
        if str(resolved).rstrip("\\/").lower() in {"d:", "d:\\", "c:", "c:\\"}:
            return False
        return True

    def _clear_current_output_dir(self) -> None:
        if self._is_task_running(self.active_task.get()):
            messagebox.showinfo("任务运行中", "请先停止或等待当前任务结束，再清空目标文件夹。")
            return
        raw = self._last_output_var_for_task().get().strip() or self._current_output_dir()
        if not raw:
            messagebox.showinfo("没有目标文件夹", "当前任务还没有可清空的目标文件夹。")
            return
        target = Path(raw)
        if not target.exists():
            messagebox.showinfo("目标文件夹不存在", f"目标文件夹不存在：\n{target}")
            return
        if not target.is_dir():
            messagebox.showwarning("目标不是文件夹", f"当前目标不是文件夹，不能清空：\n{target}")
            return
        if not self._is_safe_clear_target(target):
            messagebox.showwarning("拒绝清空", f"这个目录过大或属于工程根目录，已拒绝清空：\n{target}")
            return
        ok = messagebox.askyesno(
            "确认清空目标文件夹",
            f"将删除此文件夹内的所有内容，但保留文件夹本身：\n\n{target}\n\n此操作不可撤销，确定继续吗？",
        )
        if not ok:
            return
        try:
            preserved = []
            if self.active_task.get() == "culture":
                try:
                    from modes.culture.automedia_core.outline_preserve import backup_outline_files_before_clear

                    book_text = self.culture_book.get().strip().strip('"')
                    preserved = backup_outline_files_before_clear(target, Path(book_text).expanduser() if book_text else None)
                    if preserved:
                        self._put_log(f"已备份文史分集大纲到：{preserved[0].parent}")
                except Exception as exc:
                    self._put_log(f"备份文史分集大纲失败，继续清空：{type(exc).__name__}: {exc}")
            removed = 0
            for child in target.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed += 1
            self._put_log(f"已清空目标文件夹：{target}；删除 {removed} 项。")
            if self.active_task.get() == "research_digest" and self.research_article_list.get().strip():
                reset_ok = messagebox.askyesno(
                    "是否重置文献清单进度",
                    "目标文件夹已清空。是否同时清空当前文献清单的“已制作”标记？\n\n选择“是”后，下次可从清单第一篇重新制作。",
                )
                if reset_ok:
                    self._reset_research_article_progress(ask=False)
        except Exception as exc:
            messagebox.showerror("清空失败", f"{type(exc).__name__}: {exc}")
            self._put_log(f"清空目标文件夹失败：{type(exc).__name__}: {exc}")

    def _toggle_secret(self, key: str) -> None:
        entry = self._key_entries.get(key)
        if not entry:
            return
        entry.configure(show="" if entry.cget("show") == "*" else "*")

    def _refresh_key_status(self) -> None:
        for key_name, var in self.key_vars.items():
            label = getattr(self, f"{key_name}_status_label", None)
            if label is not None:
                label.configure(text="已填写" if var.get().strip() else "未填写")

    def _save_model_config_with_log(self) -> None:
        self._save_model_config(log=True)

    def _save_model_config(self, *, log: bool = False) -> None:
        for root in (RESEARCH_ROOT, CULTURE_ROOT):
            for key_name, file_name in KEY_FILES.items():
                value = self.key_vars[key_name].get().strip()
                if value:
                    _write_text(root / file_name, value)
        scheme = _read_json(RESEARCH_ROOT / "quanlan_model_scheme.json")
        scheme.update({
            "text_engine": self.text_engine.get(),
            "review_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "content_style": "科学经典解读",
            "call_mode": "API自动调用",
            "email_after_completion": bool(self.email_enabled.get()),
            "email_recipient": self.email_recipient.get().strip(),
        })
        _write_json(RESEARCH_ROOT / "quanlan_model_scheme.json", scheme)

        culture_settings = _read_json(CULTURE_ROOT / "gui_settings.json")
        culture_settings.update({
            "script_provider": self.culture_text_provider.get(),
            "script_model": self.culture_text_model.get(),
            "polish_provider": self.culture_polish_provider.get(),
            "polish_model": self.culture_polish_model.get(),
            "image_provider": self.culture_image_provider.get(),
            "image_model": self.culture_image_model.get(),
        })
        _write_json(CULTURE_ROOT / "gui_settings.json", culture_settings)
        self._refresh_key_status()
        if log:
            self._put_log("模型配置和 Key 已保存到合并工程副本。")

    def _save_email_config_with_log(self) -> None:
        self._save_email_config(log=True)

    def _save_email_config(self, *, log: bool = False) -> bool:
        try:
            port = int(str(self.smtp_port.get()).strip() or "465")
        except Exception:
            messagebox.showwarning("端口无效", "SMTP 端口必须是数字。")
            return False
        host = self.smtp_host.get().strip()
        user = self.smtp_user.get().strip()
        sender = self.smtp_sender.get().strip() or user
        password = self.smtp_password.get().strip()
        recipients = [x.strip() for x in self.email_recipient.get().replace("；", ",").replace("，", ",").split(",") if x.strip()]

        research_email = {
            "smtp_host": host,
            "smtp_port": port,
            "smtp_user": user,
            "smtp_password": password,
            "smtp_from": sender,
            "smtp_ssl": bool(self.smtp_ssl.get()),
            "smtp_tls": bool(self.smtp_tls.get()),
            "note": "由很有脑子的小猪理保存。授权码仅用于 SMTP 登录，请勿公开分享。",
        }
        _write_json(RESEARCH_ROOT / "quanlan_email_settings.json", research_email)
        if password:
            _write_text(RESEARCH_ROOT / "smtp_password.txt", password)
            _write_text(CULTURE_ROOT / "smtp_password.txt", password)

        run_switch_path = CULTURE_ROOT / "config" / "运行开关.json"
        run_switch = _read_json(run_switch_path)
        run_switch["email_delivery"] = {
            "enabled": bool(self.email_enabled.get()),
            "smtp_host": host,
            "smtp_port": port,
            "use_ssl": bool(self.smtp_ssl.get()),
            "username": user,
            "from": sender,
            "to": recipients,
            "password_env": "AMP_SMTP_PASSWORD",
            "password_file": "smtp_password.txt",
            "max_attachment_mb": 500,
            "subject_template": "素材生成完成：{part_name}",
        }
        _write_json(run_switch_path, run_switch)

        scheme = _read_json(RESEARCH_ROOT / "quanlan_model_scheme.json")
        scheme["email_after_completion"] = bool(self.email_enabled.get())
        scheme["email_recipient"] = self.email_recipient.get().strip()
        _write_json(RESEARCH_ROOT / "quanlan_model_scheme.json", scheme)
        if log:
            self._put_log("邮箱配置已保存到合并工程副本。")
        return True

    def _apply_qq_email_preset(self) -> None:
        self.smtp_host.set("smtp.qq.com")
        self.smtp_port.set("465")
        self.smtp_ssl.set(True)
        self.smtp_tls.set(False)
        if self.smtp_user.get().strip() and not self.smtp_sender.get().strip():
            self.smtp_sender.set(self.smtp_user.get().strip())

    def _test_email(self) -> None:
        if not self._save_email_config():
            return
        task_key = self.active_task.get()
        threading.Thread(target=self._email_test_worker, args=(task_key,), daemon=True).start()

    def _email_test_worker(self, task_key: str = "") -> None:
        started = time.perf_counter()
        try:
            host = self.smtp_host.get().strip()
            port = int(self.smtp_port.get().strip() or "465")
            user = self.smtp_user.get().strip()
            password = self.smtp_password.get().strip()
            if not host or not user or not password:
                self._put_log("SMTP 测试失败：服务器、账号或授权码未填写。", task_key=task_key)
                return
            if self.smtp_ssl.get():
                server = smtplib.SMTP_SSL(host, port, timeout=30)
            else:
                server = smtplib.SMTP(host, port, timeout=30)
                if self.smtp_tls.get():
                    server.starttls()
            try:
                server.login(user, password)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
            self._put_log(f"SMTP 测试通过，耗时 {time.perf_counter() - started:.1f}s。", task_key=task_key)
        except Exception as exc:
            self._put_log(f"SMTP 测试失败，耗时 {time.perf_counter() - started:.1f}s：{type(exc).__name__}: {exc}", task_key=task_key)

    def _run_research_digest(self) -> None:
        runtime_env = self._runtime_env("research_digest", model_scheme=self._research_model_scheme_snapshot())
        if runtime_env is None:
            return
        out_dir = self._research_daily_out_dir()
        self._set_last_output_for_task("research_digest", out_dir)
        args = ["--daily-research-digest"]
        self._add_arg(args, "--daily-out-dir", out_dir)
        self._add_arg(args, "--daily-days", self.research_days.get())
        self._add_arg(args, "--daily-max-articles", self.research_max_articles.get())
        self._add_arg(args, "--daily-journals", self.research_journals.get())
        self._add_arg(args, "--daily-text-engine", self.text_engine.get())
        self._add_arg(args, "--daily-polish-engine", self.polish_engine.get())
        self._add_arg(args, "--daily-image-engine", _normalize_research_image_choice(self.image_engine.get()))
        self._add_arg(args, "--daily-article-list", self.research_article_list.get())
        if self.research_skip_image_api.get():
            args.append("--daily-skip-image-api")
        if self.email_enabled.get():
            args.append("--daily-email")
            self._add_arg(args, "--daily-email-recipient", self.email_recipient.get())
        self._run_mode("research", args, output_dir=out_dir, task_key="research_digest", task_label="科研速递", env=runtime_env)

    def _build_research_article_list(self) -> None:
        runtime_env = self._runtime_env("research_digest", model_scheme=self._research_model_scheme_snapshot())
        if runtime_env is None:
            return
        out_dir = self._research_continue_base_out_dir()
        if not self.research_article_list.get().strip():
            self.research_article_list.set(str(Path(out_dir) / f"文献清单_{datetime.now().strftime('%Y%m%d')}.json"))
        args = ["--daily-build-article-list"]
        self._add_arg(args, "--daily-out-dir", out_dir)
        self._add_arg(args, "--daily-days", self.research_days.get())
        self._add_arg(args, "--daily-max-articles", self.research_max_articles.get())
        self._add_arg(args, "--daily-journals", self.research_journals.get())
        self._add_arg(args, "--daily-article-list", self.research_article_list.get())
        self._run_mode("research", args, output_dir="", refresh_article_list=True, task_key="research_digest", task_label="科研速递", env=runtime_env)

    def _run_research_digest_continue_list(self) -> None:
        article_list = self.research_article_list.get().strip()
        if not article_list:
            messagebox.showwarning("缺少文献清单", "请选择已有文献清单 JSON，再续做素材。")
            return
        runtime_env = self._runtime_env("research_digest", model_scheme=self._research_model_scheme_snapshot())
        if runtime_env is None:
            return
        out_dir = self._research_continue_base_out_dir()
        self._set_last_output_for_task("research_digest", out_dir)
        args = ["--daily-research-digest", "--daily-continue-until-exhausted"]
        self._add_arg(args, "--daily-out-dir", out_dir)
        self._add_arg(args, "--daily-article-list", article_list)
        self._add_arg(args, "--daily-max-articles", self.research_max_articles.get())
        self._add_arg(args, "--daily-journals", self.research_journals.get())
        self._add_arg(args, "--daily-text-engine", self.text_engine.get())
        self._add_arg(args, "--daily-polish-engine", self.polish_engine.get())
        self._add_arg(args, "--daily-image-engine", _normalize_research_image_choice(self.image_engine.get()))
        if self.research_skip_image_api.get():
            args.append("--daily-skip-image-api")
        if self.email_enabled.get():
            args.append("--daily-email")
            self._add_arg(args, "--daily-email-recipient", self.email_recipient.get())
        self._run_mode("research", args, output_dir=out_dir, refresh_article_list=True, task_key="research_digest", task_label="科研速递", env=runtime_env)

    def _resume_research_digest_issue(self) -> None:
        out_dir = self.research_resume_dir.get().strip() or self.research_out_dir.get().strip() or self.last_research_output_dir.get().strip()
        if not out_dir:
            messagebox.showwarning(
                "缺少档期",
                "请在“断档续作目录”里选择某一期研究速递档期文件夹，例如：\n"
                r"D:\Quanlan\全澜脑科学视频号\科研速递\20260605（1）"
                "\n\n不要选择“科研速递”总目录。",
            )
            return
        target, warning = self._resolve_research_issue_dir(Path(out_dir))
        if warning:
            messagebox.showwarning("请选择具体档期文件夹", warning)
            return
        if target is None:
            messagebox.showwarning(
                "缺少档期",
                "请在“断档续作目录”里选择某一期研究速递档期文件夹，例如：\n"
                r"D:\Quanlan\全澜脑科学视频号\科研速递\20260605（1）"
                "\n\n不要选择“科研速递”总目录。",
            )
            return
        runtime_env = self._runtime_env("research_digest", model_scheme=self._research_model_scheme_snapshot())
        if runtime_env is None:
            return
        self._set_last_output_for_task("research_digest", str(target))
        self.research_resume_dir.set(str(target))
        args = ["--daily-research-digest", "--daily-resume-existing"]
        self._add_arg(args, "--daily-out-dir", str(target))
        self._add_arg(args, "--daily-article-list", self.research_article_list.get())
        self._add_arg(args, "--daily-text-engine", self.text_engine.get())
        self._add_arg(args, "--daily-polish-engine", self.polish_engine.get())
        self._add_arg(args, "--daily-image-engine", _normalize_research_image_choice(self.image_engine.get()))
        if self.research_skip_image_api.get():
            args.append("--daily-skip-image-api")
        if self.email_enabled.get():
            args.append("--daily-email")
            self._add_arg(args, "--daily-email-recipient", self.email_recipient.get())
        self._run_mode("research", args, output_dir=str(target), task_key="research_digest", task_label="科研速递", env=runtime_env)

    def _resolve_research_issue_dir(self, selected: Path) -> tuple[Path | None, str]:
        target = selected.expanduser()
        if not target.exists():
            return None, f"这个路径不存在，请选择已经生成过的某一期档期文件夹：\n\n{target}"
        if not target.is_dir():
            return None, f"当前路径不是文件夹，不能续作档期：\n\n{target}"
        if self._is_research_issue_dir(target):
            return target, ""

        candidates = self._find_research_issue_children(target)
        if len(candidates) == 1:
            resolved = candidates[0]
            self._put_log(f"[科研速递] 已从上一级目录自动定位档期：{resolved}", task_key="research_digest")
            return resolved, ""
        if len(candidates) > 1:
            examples = "\n".join(f"- {p.name}" for p in candidates[:8])
            more = "" if len(candidates) <= 8 else f"\n……另有 {len(candidates) - 8} 个"
            return None, (
                "你现在选的像是研究速递总目录或上一级目录，不是具体档期。\n\n"
                "续作档期需要选择某一期文件夹，例如：\n"
                r"D:\Quanlan\全澜脑科学视频号\科研速递\20260605（1）"
                "\n\n当前目录下发现了多个档期，请重新在“断档续作目录”里选择其中一个：\n"
                f"{examples}{more}"
            )
        return None, (
            "这个文件夹里没有找到可续作的研究速递档期文件。\n\n"
            "请确认选择的是某一期档期文件夹，例如 20260605 或 20260605（1）。\n"
            "该文件夹里通常应包含 00_文献信息.json、01_栏目素材.json、02_口播台词.txt 等文件。\n\n"
            f"当前选择：{target}"
        )

    def _is_research_issue_dir(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        if not RESEARCH_ISSUE_DIR_RE.match(path.name):
            return False
        if any((path / name).exists() for name in RESEARCH_ISSUE_MARKERS):
            return True
        return self._research_issue_has_outputs(path)

    def _research_issue_has_outputs(self, path: Path) -> bool:
        try:
            for dirname in RESEARCH_ISSUE_OUTPUT_DIRS:
                folder = path / dirname
                if not folder.exists() or not folder.is_dir():
                    continue
                if any(p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} for p in folder.rglob("*")):
                    return True
        except OSError:
            return False
        return False

    def _find_research_issue_children(self, parent: Path) -> list[Path]:
        candidates: list[Path] = []
        try:
            children = [p for p in parent.iterdir() if p.is_dir()]
        except OSError:
            return candidates
        for child in children:
            if self._is_research_issue_dir(child):
                candidates.append(child)
        candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return candidates

    def _article_list_progress_path(self, path: Path) -> Path:
        return path.with_name(path.stem + "_续做进度.json")

    def _resolved_research_article_list_path(self) -> Path | None:
        raw = self.research_article_list.get().strip().strip('"')
        if not raw:
            return None
        path = Path(raw)
        if path.is_dir():
            for name in ("00_候选文献清单.json", "00_文献信息.json", "article_list.json", "articles.json"):
                candidate = path / name
                if candidate.exists():
                    path = candidate
                    break
        return path if path.exists() and path.is_file() else None

    def _reset_research_article_progress(self, *, ask: bool = True) -> bool:
        path = self._resolved_research_article_list_path()
        if path is None:
            messagebox.showinfo("没有文献清单", "请先选择一个已有文献清单 JSON。")
            return False
        progress_path = self._article_list_progress_path(path)
        if ask:
            ok = messagebox.askyesno(
                "确认重置清单进度",
                f"将清空此文献清单的“已制作”标记：\n\n{progress_path}\n\n文献清单本身不会删除。确定要从头制作吗？",
            )
            if not ok:
                return False
        try:
            if progress_path.exists():
                progress_path.unlink()
                self._put_log(f"已重置文献清单制作进度：{progress_path}")
            else:
                self._put_log(f"文献清单尚无制作进度，无需重置：{progress_path}")
            self._refresh_article_list_preview()
            return True
        except Exception as exc:
            messagebox.showerror("重置失败", f"{type(exc).__name__}: {exc}")
            self._put_log(f"重置文献清单进度失败：{type(exc).__name__}: {exc}")
            return False

    def _load_article_list_for_preview(self) -> tuple[list[dict], set[str], str]:
        raw = self.research_article_list.get().strip().strip('"')
        if not raw:
            return [], set(), "未选择文献清单。"
        path = Path(raw)
        if path.is_dir():
            for name in ("00_候选文献清单.json", "00_文献信息.json", "article_list.json", "articles.json"):
                candidate = path / name
                if candidate.exists():
                    path = candidate
                    break
        if not path.exists():
            return [], set(), f"文献清单不存在：{path}"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return [], set(), f"文献清单读取失败：{type(exc).__name__}: {exc}"
        if isinstance(data, list):
            articles = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            articles = [x for x in (data.get("articles") or data.get("items") or data.get("papers") or data.get("article_list") or []) if isinstance(x, dict)]
        else:
            articles = []
        used_pmids: set[str] = set()
        progress_path = self._article_list_progress_path(path)
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8-sig"))
            used = progress.get("used_pmids", {}) if isinstance(progress, dict) else {}
            if isinstance(used, dict):
                used_pmids = {str(x).strip() for x in used.keys() if str(x).strip()}
            elif isinstance(used, list):
                used_pmids = {str(x).strip() for x in used if str(x).strip()}
        except Exception:
            pass
        self.research_article_list.set(str(path))
        return articles, used_pmids, ""

    def _refresh_article_list_preview(self) -> None:
        widget = self.article_list_preview
        if widget is None:
            return
        articles, used_pmids, error = self._load_article_list_for_preview()
        lines: list[str] = []
        if error:
            lines.append(error)
        else:
            pending = len([x for x in articles if str(x.get("pmid", "")).strip() not in used_pmids])
            lines.append(f"清单共 {len(articles)} 篇；已用 {len(used_pmids)} 篇；待做 {pending} 篇。")
            lines.append("")
            preview_articles = articles[:ARTICLE_PREVIEW_LIMIT]
            for idx, item in enumerate(preview_articles, start=1):
                pmid = str(item.get("pmid", "")).strip()
                status = "已用" if pmid in used_pmids else "待做"
                journal = str(item.get("journal", "") or "Unknown").strip()
                title = re.sub(r"\s+", " ", str(item.get("title", "")).strip())
                lines.append(f"{idx:02d}. [{status}] {journal} | PMID {pmid or '-'}")
                lines.append(f"    {title[:180]}")
            if len(articles) > ARTICLE_PREVIEW_LIMIT:
                lines.append("")
                lines.append(f"仅预览前 {ARTICLE_PREVIEW_LIMIT} 篇；完整清单保留在 JSON 文件中。")
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines).strip() + "\n")
        widget.configure(state="disabled")

    def _research_daily_out_dir(self) -> str:
        explicit = self.research_out_dir.get().strip()
        issue_count = self._bounded_int(self.research_issue_count.get(), 1, 3, 1)
        issue_no = self._bounded_int(self.research_issue_no.get(), 1, issue_count, 1)
        date_name = datetime.now().strftime("%Y%m%d")
        folder_name = date_name if issue_count <= 1 else f"{date_name}（{issue_no}）"
        if explicit:
            path = Path(explicit)
            if path.name == folder_name:
                return str(path)
            return str(path / folder_name)
        return str(RESEARCH_ROOT / "chapter_pdf_direct_output" / "每日研究速递" / folder_name)

    def _research_continue_base_out_dir(self) -> str:
        explicit = self.research_out_dir.get().strip()
        if explicit:
            path = Path(explicit)
            if re.fullmatch(r"\d{8}(?:（\d+）)?", path.name):
                return str(path.parent)
            return str(path)
        return str(RESEARCH_ROOT / "chapter_pdf_direct_output" / "每日研究速递")

    def _bounded_int(self, value: str, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(str(value or "").strip())
        except Exception:
            number = default
        return max(minimum, min(maximum, number))

    def _normalize_journals_with_gpt(self) -> None:
        if self._is_task_running("research_digest"):
            messagebox.showinfo("任务运行中", "请等当前任务结束后再整理期刊。")
            return
        request = self.research_journal_fuzzy.get().strip()
        if not request:
            messagebox.showwarning("缺少需求", "请先在“杂志需求”里描述你想关注的方向或期刊。")
            return
        threading.Thread(target=self._journal_gpt_worker, args=(request,), daemon=True).start()

    def _journal_gpt_worker(self, request: str) -> None:
        started = time.perf_counter()
        try:
            from openai import OpenAI

            key = self.key_vars["openai"].get().strip()
            if not key:
                self._put_log("期刊梳理失败：OpenAI/GPT Key 未填写。", task_key="research_digest")
                return
            model = self.text_engine.get().strip() or "GPT-5.5"
            base_url = self._normalized_foreign_base_url()
            client = OpenAI(api_key=key, base_url=base_url, timeout=90, max_retries=0)
            prompt = (
                "你是神经科学文献速递编辑。请把用户的模糊需求整理成适合 PubMed 或期刊过滤使用的英文学术期刊名列表。"
                "只输出期刊名，用英文逗号分隔，不要解释，不要编号。优先真实期刊全名，最多 20 个。\n\n"
                f"用户需求：{request}"
            )
            response = client.responses.create(
                model=_research_text_model_id(model),
                input=prompt,
                max_output_tokens=600,
            )
            text = _extract_response_content(response)
            journals = self._clean_journal_list(text)
            if not journals:
                journals = self._clean_journal_list(request)
                if journals:
                    self._put_log("期刊梳理未拿到模型正文，已按需求使用内置神经科学顶刊列表。", task_key="research_digest")
                else:
                    self._put_log(f"期刊梳理未得到有效结果：provider=openai，model={model}，base={base_url}，key={_key_hint(key)}。", task_key="research_digest")
                    return
            self.research_journals.set(journals)
            self._put_log(f"期刊梳理完成，耗时 {time.perf_counter() - started:.1f}s：已填入 {len([x for x in journals.split(',') if x.strip()])} 个期刊。", task_key="research_digest")
        except Exception as exc:
            self._put_log(f"期刊梳理失败，耗时 {time.perf_counter() - started:.1f}s：provider=openai，model={locals().get('model', '')}，base={locals().get('base_url', '')}，key={_key_hint(locals().get('key', ''))}；{type(exc).__name__}: {exc}", task_key="research_digest")

    def _clean_journal_list(self, text: str) -> str:
        raw = str(text or "").replace("\n", ",").replace("；", ",").replace("，", ",")
        lowered = raw.lower()
        bad_markers = (
            "chat.completion",
            "completion.chunk",
            '"choices"',
            '"usage"',
            "prompt_tokens",
            "completion_tokens",
            "system_fingerprint",
            "data:",
        )
        if any(marker in lowered for marker in bad_markers):
            return ""
        items: list[str] = []
        for part in raw.split(","):
            item = re.sub(r"^[\s\-•\d.、)）(（]+", "", part).strip().strip("\"'` ")
            item = re.sub(r"\s+", " ", item)
            if not item:
                continue
            item_l = item.lower()
            if any(marker in item_l for marker in bad_markers):
                continue
            if len(item) > 80 or len(item) < 3:
                continue
            if not re.search(r"[A-Za-z]", item):
                continue
            if re.search(r"[{}\\[\\]:=]", item):
                continue
            if item and item not in items:
                items.append(item)
        if not items and str(text or "").strip() and "神经科学" in str(text):
            return DEFAULT_RESEARCH_JOURNALS
        return ", ".join(items[:20])

    def _run_science_classic(self, *, test_b_image_limit: int = 0) -> None:
        out_dir = self.science_out_dir.get().strip()
        if out_dir:
            self._set_last_output_for_task("science_classic", out_dir)
        slots = [{
            "pdf_path": self.science_pdf.get().strip(),
            "current_pdf_path": self.science_pdf.get().strip(),
            "out_dir": self.science_out_dir.get().strip(),
            "content_style": "科学经典解读",
            "text_engine": self.text_engine.get(),
            "review_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "call_mode": "API自动调用",
            "flow_parse": bool(self.science_flow_parse.get()),
            "flow_script": bool(self.science_flow_script.get()),
            "flow_image": bool(self.science_flow_image.get()),
            "clear_existing_images_before_draw": bool(self.science_redraw.get()),
            "email_after_completion": bool(self.email_enabled.get()),
            "email_recipient": self.email_recipient.get().strip(),
            "test_b_image_limit": max(0, int(test_b_image_limit or 0)),
        }]
        task_settings = {"slots": slots}
        runtime_env = self._runtime_env(
            "science_classic",
            model_scheme=self._research_model_scheme_snapshot(),
            task_page_settings=task_settings,
        )
        if runtime_env is None:
            return
        args = ["--content-style", "科学经典解读"]
        label = "科学经典解读测试" if test_b_image_limit else "科学经典解读"
        self._run_mode("research", args, gui=True, output_dir=out_dir, task_key="science_classic", task_label=label, env=runtime_env)

    def _test_science_classic_b_image(self) -> None:
        self._put_log("科学经典测试：只生成/处理第 1 张 B 图，用于快速检查文案、提示词、生图和后处理链路。", task_key="science_classic")
        self._run_science_classic(test_b_image_limit=1)

    def _run_culture(self, *, test_b_image_limit: int | None = None) -> None:
        out_dir = self.culture_out_dir.get().strip() or self.culture_continue_folder.get().strip()
        if out_dir:
            self._set_last_output_for_task("culture", out_dir)
        args: list[str] = []
        self._add_arg(args, "--book", self.culture_book.get())
        self._add_arg(args, "--out", self.culture_out_dir.get())
        self._add_arg(args, "--continue-from-folder", self.culture_continue_folder.get())
        self._add_arg(args, "--start-stage", self.culture_start_stage.get())
        limit_value = str(max(0, int(test_b_image_limit))) if test_b_image_limit is not None else self.culture_test_b_limit.get()
        try:
            effective_test_limit = max(0, int(str(limit_value or "0").strip() or 0))
        except Exception:
            effective_test_limit = 0
        self._add_arg(args, "--test-b-image-limit", limit_value)
        self._add_arg(args, "--provider", self.culture_text_provider.get())
        self._add_arg(args, "--text-model", self.culture_text_model.get())
        self._add_arg(args, "--script-provider", self.culture_text_provider.get())
        self._add_arg(args, "--script-model", self.culture_text_model.get())
        self._add_arg(args, "--polish-provider", self.culture_polish_provider.get())
        self._add_arg(args, "--polish-model", self.culture_polish_model.get())
        self._add_arg(args, "--image-provider", self.culture_image_provider.get())
        self._add_arg(args, "--image-model", self.culture_image_model.get())
        if self.culture_auto_resume.get():
            args.append("--auto-resume")
        if self.culture_skip_existing_text.get():
            args.append("--skip-existing-text")
        if self.culture_skip_existing_images.get():
            args.append("--skip-existing-images")
        if self.culture_skip_images.get():
            args.append("--skip-images")
        if self.culture_only_postprocess.get():
            args.append("--only-postprocess")
        if self.culture_no_split_assets.get():
            args.append("--no-split-assets")
        if not self.culture_book.get().strip() and not self.culture_continue_folder.get().strip():
            messagebox.showwarning("缺少输入", "请选择书籍 PDF，或选择续跑目录。")
            return
        runtime_env = self._runtime_env("culture")
        if runtime_env is None:
            return
        label = "文史小秘测试" if effective_test_limit else "文史小秘"
        self._run_mode("culture", args, output_dir=out_dir, task_key="culture", task_label=label, env=runtime_env)

    def _test_culture_b_image(self) -> None:
        self._put_log("文史小秘测试：只生成/处理第 1 张 B 图，用于快速检查脚本、提示词、生图和后处理链路。", task_key="culture")
        self._run_culture(test_b_image_limit=1)

    def _run_auto_clip(self) -> None:
        image_dir = self.auto_clip_image_dir.get().strip()
        lrc_dir = self.auto_clip_lrc_dir.get().strip()
        output_dir = self.auto_clip_output_dir.get().strip()
        if not image_dir or not Path(image_dir).is_dir():
            messagebox.showwarning("请选择图片素材文件夹", "请先选择一个有效的图片素材文件夹。")
            return
        if not lrc_dir or not Path(lrc_dir).is_dir():
            messagebox.showwarning("请选择 LRC 素材文件夹", "请先选择一个有效的 LRC 素材文件夹。")
            return
        if not output_dir:
            output_dir = str(Path(lrc_dir) / "自动剪辑输出")
            self.auto_clip_output_dir.set(output_dir)
        self._set_last_output_for_task("auto_clip", output_dir)
        self._save_workbench_settings()
        cmd = [
            sys.executable,
            "-m",
            "quanlan_dual_assistant.auto_video_editor",
            "--images",
            image_dir,
            "--lrc",
            lrc_dir,
            "--output",
            output_dir,
        ]
        self._run_direct_command(
            "auto_clip",
            "自动剪辑",
            cmd,
            cwd=PROJECT_ROOT,
            output_dir=output_dir,
        )

    def _test_text_model(self) -> None:
        self._save_model_config(log=False)
        task_key = self.active_task.get()
        threading.Thread(target=self._text_test_worker, args=(task_key,), daemon=True).start()

    def _text_test_worker(self, task_key: str = "") -> None:
        started = time.perf_counter()
        try:
            from openai import OpenAI

            if task_key == "culture":
                provider = self.culture_text_provider.get()
                if provider == "deepseek":
                    key_name = "deepseek"
                    key = self.key_vars["deepseek"].get().strip()
                    base_url = self.deepseek_base_url.get().strip() or "https://api.deepseek.com"
                    model = self.culture_polish_model.get().strip() or "deepseek-v4-pro"
                elif provider == "gemini":
                    key_name = "gemini"
                    key = self.key_vars["gemini"].get().strip()
                    base_url = self._normalized_foreign_base_url()
                    model = self.culture_text_model.get().strip() or "gemini-3.5-flash"
                else:
                    key_name = "openai"
                    key = self.key_vars["openai"].get().strip()
                    base_url = self._normalized_foreign_base_url()
                    model = self.culture_text_model.get().strip() or "gpt-5.5"
            elif "DeepSeek" in self.text_engine.get():
                key_name = "deepseek"
                key = self.key_vars["deepseek"].get().strip()
                base_url = self.deepseek_base_url.get().strip() or "https://api.deepseek.com"
                model = _research_text_model_id(self.text_engine.get())
                provider = "deepseek"
            elif "Gemini" in self.text_engine.get():
                key_name = "gemini"
                key = self.key_vars["gemini"].get().strip()
                base_url = self._normalized_foreign_base_url()
                model = _research_text_model_id(self.text_engine.get())
                provider = "gemini"
            else:
                key_name = "openai"
                key = self.key_vars["openai"].get().strip()
                base_url = self._normalized_foreign_base_url()
                model = _research_text_model_id(self.text_engine.get())
                provider = "openai"
            if not key:
                self._put_log(f"文本模型测试失败：provider={provider}，model={model}，key={KEY_LABELS.get(key_name, key_name)} 未填写。", task_key=task_key)
                return
            self._put_log(f"文本模型测试开始：provider={provider}，model={model}，base={base_url}，key={KEY_LABELS.get(key_name, key_name)} {_key_hint(key)}。", task_key=task_key)
            client = OpenAI(api_key=key, base_url=base_url, timeout=60, max_retries=0)
            if provider == "openai":
                response = client.responses.create(
                    model=model,
                    input="Connection test. Reply exactly: OK",
                    max_output_tokens=32,
                )
                content = _extract_response_content(response)
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Connection test. Reply exactly: OK"}],
                    max_tokens=8,
                    temperature=0,
                )
                content = _extract_chat_content(response)
            if not content:
                raise RuntimeError(f"模型返回为空或格式不可识别：{type(response).__name__}")
            self._put_log(f"文本模型测试通过：provider={provider}，model={model}，耗时 {time.perf_counter() - started:.1f}s，返回：{content[:20] or '空'}", task_key=task_key)
        except Exception as exc:
            self._put_log(f"文本模型测试失败，耗时 {time.perf_counter() - started:.1f}s：provider={locals().get('provider', '')}，model={locals().get('model', '')}，base={locals().get('base_url', '')}，key={KEY_LABELS.get(locals().get('key_name', ''), locals().get('key_name', ''))} {_key_hint(locals().get('key', ''))}；{type(exc).__name__}: {exc}", task_key=task_key)

    def _test_image_model(self) -> None:
        self._save_model_config(log=False)
        task_key = self.active_task.get()
        threading.Thread(target=self._image_test_worker, args=(task_key,), daemon=True).start()

    def _test_named_model(self, target: str) -> None:
        self._save_model_config(log=False)
        task_key = self.active_task.get()
        threading.Thread(target=self._named_model_test_worker, args=(target, task_key), daemon=True).start()

    def _named_model_test_worker(self, target: str, task_key: str = "") -> None:
        if target == "culture_image":
            self._image_test_worker("culture")
            return
        if target == "research_image":
            self._image_test_worker("research_digest")
            return
        mapping = {
            "culture_text": (self.culture_text_provider.get(), self.culture_text_model.get(), "文史文本"),
            "culture_polish": (self.culture_polish_provider.get(), self.culture_polish_model.get(), "文史润色"),
            "research_text": (_provider_for_engine(self.text_engine.get()), _research_text_model_id(self.text_engine.get()), "科研文本"),
            "research_polish": (_provider_for_engine(self.polish_engine.get() if self.polish_engine.get() != "跟随脚本模型" else self.text_engine.get()), _research_text_model_id(self.polish_engine.get() if self.polish_engine.get() != "跟随脚本模型" else self.text_engine.get()), "科研润色"),
        }
        provider, model, label = mapping.get(target, ("", "", target))
        self._text_test_worker_for(provider, model, label, task_key)

    def _text_test_worker_for(self, provider: str, model: str, label: str, task_key: str = "") -> None:
        started = time.perf_counter()
        provider = (provider or "openai").strip().lower()
        try:
            from openai import OpenAI

            if provider == "deepseek":
                key_name = "deepseek"
                key = self.key_vars["deepseek"].get().strip()
                base_url = self.deepseek_base_url.get().strip() or "https://api.deepseek.com"
                model = model.strip() or "deepseek-v4-pro"
            elif provider == "gemini":
                key_name = "gemini"
                key = self.key_vars["gemini"].get().strip()
                base_url = self._normalized_foreign_base_url()
                model = model.strip() or "gemini-3.1-pro-preview"
            else:
                key_name = "openai"
                key = self.key_vars["openai"].get().strip()
                base_url = self._normalized_foreign_base_url()
                model = model.strip() or "gpt-5.5"
            if not key:
                self._put_log(f"{label}测试失败：provider={provider}，model={model}，key={KEY_LABELS.get(key_name, key_name)} 未填写。", task_key=task_key)
                return
            self._put_log(f"{label}测试开始：provider={provider}，model={model}，base={base_url}，key={KEY_LABELS.get(key_name, key_name)} {_key_hint(key)}。", task_key=task_key)
            client = OpenAI(api_key=key, base_url=base_url, timeout=60, max_retries=0)
            if provider == "openai":
                response = client.responses.create(model=model, input="Connection test. Reply exactly: OK", max_output_tokens=32)
                content = _extract_response_content(response)
            else:
                response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Connection test. Reply exactly: OK"}], max_tokens=8, temperature=0)
                content = _extract_chat_content(response)
            if not content:
                raise RuntimeError(f"模型返回为空或格式不可识别：{type(response).__name__}")
            self._put_log(f"{label}测试通过：provider={provider}，model={model}，耗时 {time.perf_counter() - started:.1f}s，返回：{content[:40]}", task_key=task_key)
        except Exception as exc:
            self._put_log(f"{label}测试失败，耗时 {time.perf_counter() - started:.1f}s：provider={provider}，model={model}，base={locals().get('base_url', '')}，key={KEY_LABELS.get(locals().get('key_name', ''), locals().get('key_name', ''))} {_key_hint(locals().get('key', ''))}；{type(exc).__name__}: {exc}", task_key=task_key)

    def _image_test_worker(self, task_key: str = "") -> None:
        started = time.perf_counter()
        try:
            from openai import OpenAI

            engine = _normalize_research_image_choice(self.image_engine.get()) if task_key != "culture" else ""
            model = (self.culture_image_model.get().strip() if task_key == "culture" else _image_model_id_for_choice(engine)) or "gpt-image-2"
            is_gemini_image = "gemini" in model.lower()
            key_name = "gemini" if is_gemini_image else ("image" if self.key_vars["image"].get().strip() else "openai")
            key = self.key_vars["gemini"].get().strip() if is_gemini_image else (self.key_vars["image"].get().strip() or self.key_vars["openai"].get().strip())
            if not key:
                self._put_log(f"绘图模型测试失败：{KEY_LABELS.get(key_name, key_name)} 未填写。", task_key=task_key)
                return
            base_url = self._normalized_foreign_base_url()
            self._put_log(f"绘图模型测试开始：provider=image，model={model}，base={base_url}，key={KEY_LABELS.get(key_name, key_name)} {_key_hint(key)}，timeout=240s。", task_key=task_key)
            if is_gemini_image:
                gemini_base = base_url.rsplit("/v1", 1)[0].rstrip("/")
                url = f"{gemini_base}/v1beta/models/{model}:generateContent"
                payload = json.dumps(
                    {
                        "contents": [{"role": "user", "parts": [{"text": "A clean visual test card with simple geometric shapes, no text."}]}],
                        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=240) as resp:
                    resp.read(128)
                self._put_log(f"绘图模型测试通过：provider=gemini，model={model}，耗时 {time.perf_counter() - started:.1f}s，接口 generateContent。", task_key=task_key)
            else:
                client = OpenAI(api_key=key, base_url=base_url, timeout=240, max_retries=0)
                client.images.generate(
                    model=model,
                    prompt="A clean visual test card with simple geometric shapes, no text.",
                    size="720x1280",
                )
                self._put_log(f"绘图模型测试通过：provider=image，model={model}，耗时 {time.perf_counter() - started:.1f}s，接口 images.generate，尺寸 720x1280。", task_key=task_key)
        except Exception as exc:
            self._put_log(f"绘图模型测试失败，耗时 {time.perf_counter() - started:.1f}s：provider=image，model={locals().get('model', '')}，base={locals().get('base_url', '')}，key={KEY_LABELS.get(locals().get('key_name', ''), locals().get('key_name', ''))} {_key_hint(locals().get('key', ''))}；{type(exc).__name__}: {exc}", task_key=task_key)

    def _normalized_foreign_base_url(self) -> str:
        base_url = (self.foreign_base_url.get().strip() or "https://greatwalllink.top/v1").replace("greatwallink.top", "greatwalllink.top").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        return base_url

    def _run_mode(
        self,
        mode_key: str,
        args: list[str],
        *,
        gui: bool = False,
        output_dir: str = "",
        refresh_article_list: bool = False,
        task_key: str | None = None,
        task_label: str | None = None,
        env: dict | None = None,
    ) -> None:
        task_key = task_key or mode_key
        if self._is_task_running(task_key):
            messagebox.showinfo("任务运行中", "这个任务已经在运行中。")
            return
        mode = get_mode(mode_key)
        cmd = _python_command(mode, gui=gui, extra_args=args)
        self._put_log("", task_key=task_key)
        if "--daily-build-article-list" in args:
            task_name = "补文献清单"
        elif "--daily-resume-existing" in args:
            task_name = "续作档期"
        elif "--daily-research-digest" in args:
            task_name = "科研速递"
        else:
            task_name = task_label or mode.title
        task_label = task_label or task_name
        self.running_processes[task_key] = None
        self.running_labels[task_key] = task_label
        self._write_release_state()
        self._put_log(f"[{task_label}] 启动任务。", task_key=task_key)
        if output_dir:
            self._put_log(f"[{task_label}] 素材输出目录：{output_dir}", task_key=task_key)
        threading.Thread(target=self._process_worker, args=(task_key, task_label, mode, cmd, output_dir, refresh_article_list, env), daemon=True).start()

    def _run_direct_command(
        self,
        task_key: str,
        task_label: str,
        cmd: list[str],
        *,
        cwd: Path,
        output_dir: str = "",
        env: dict | None = None,
    ) -> None:
        if self._is_task_running(task_key):
            messagebox.showinfo("任务运行中", "这个任务已经在运行中。")
            return
        self.running_processes[task_key] = None
        self.running_labels[task_key] = task_label
        self._put_log("", task_key=task_key)
        self._put_log(f"[{task_label}] 启动任务。", task_key=task_key)
        if output_dir:
            self._put_log(f"[{task_label}] 输出目录：{output_dir}", task_key=task_key)
        threading.Thread(
            target=self._direct_process_worker,
            args=(task_key, task_label, cmd, cwd, output_dir, env),
            daemon=True,
        ).start()

    def _direct_process_worker(
        self,
        task_key: str,
        task_label: str,
        cmd: list[str],
        cwd: Path,
        output_dir: str = "",
        env: dict | None = None,
    ) -> None:
        try:
            env = dict(env or os.environ.copy())
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self.running_processes[task_key] = proc
            self._set_status(self._status_text())
            assert proc.stdout is not None
            for line in proc.stdout:
                self._put_log(f"[{task_label}] {line.rstrip(chr(10))}", task_key=task_key)
            code = proc.wait()
            self._put_log(f"[{task_label}] 已结束，退出码 {code}", task_key=task_key)
            if code == 0 and output_dir:
                self._set_last_output_for_task(task_key, output_dir)
                self._put_log(f"[{task_label}] 正在打开输出目录：{output_dir}", task_key=task_key)
                self.after(0, lambda p=output_dir: self._open_path(p))
        except Exception as exc:
            self._put_log(f"[{task_label}] 启动失败：{type(exc).__name__}: {exc}", task_key=task_key)
        finally:
            self.running_processes.pop(task_key, None)
            self.running_labels.pop(task_key, None)
            self._set_status(self._status_text())

    def _process_worker(self, task_key: str, task_label: str, mode: ModeSpec, cmd: list[str], output_dir: str = "", refresh_article_list: bool = False, env: dict | None = None) -> None:
        try:
            env = dict(env or os.environ.copy())
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            proc = subprocess.Popen(
                cmd,
                cwd=str(mode.path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self.running_processes[task_key] = proc
            self._set_status(self._status_text())
            assert proc.stdout is not None
            for line in proc.stdout:
                self._put_log(f"[{task_label}] {line.rstrip(chr(10))}", task_key=task_key)
            code = proc.wait()
            self._put_log(f"[{task_label}] 已结束，退出码 {code}", task_key=task_key)
            if code == 0 and output_dir:
                self._set_last_output_for_task(task_key, output_dir)
                self._put_log(f"[{task_label}] 正在打开素材输出目录：{output_dir}", task_key=task_key)
                self.after(0, lambda p=output_dir: self._open_path(p))
            if code == 0 and refresh_article_list:
                self.after(0, self._refresh_article_list_preview)
        except Exception as exc:
            self._put_log(f"[{task_label}] 启动失败：{type(exc).__name__}: {exc}", task_key=task_key)
        finally:
            self.running_processes.pop(task_key, None)
            self.running_labels.pop(task_key, None)
            self._write_release_state()
            self._set_status(self._status_text())
            self.after(1500, self._try_release_idle_upgrade)

    def _stop_process(self) -> None:
        task_key = self.active_task.get()
        task_label = self.running_labels.get(task_key, task_key)
        proc = self.running_processes.get(task_key)
        if proc is None:
            self._put_log(f"[{task_label}] 当前没有运行中的任务。", task_key=task_key)
            return
        try:
            proc.terminate()
            self._put_log(f"[{task_label}] 已请求停止当前任务。", task_key=task_key)
        except Exception as exc:
            self._put_log(f"[{task_label}] 停止失败：{exc}", task_key=task_key)

    def _add_arg(self, args: list[str], name: str, value: str) -> None:
        value = str(value or "").strip()
        if value:
            args.extend([name, value])

    def _put_log(self, text: str, task_key: str = "") -> None:
        key = str(task_key or self.active_task.get() or "research_digest").strip()
        if key not in self.log_buffers:
            key = self.active_task.get() if self.active_task.get() in self.log_buffers else "research_digest"
        raw_text = str(text)
        if raw_text.strip():
            now = time.perf_counter()
            last = self.log_last_ts.get(key)
            delta = f" +{now - last:.1f}s" if last is not None and (now - last) >= 10 else ""
            self.log_last_ts[key] = now
            stamped_text = f"[{datetime.now().strftime('%H:%M:%S')}{delta}] {raw_text}"
        else:
            stamped_text = raw_text
        try:
            while self.log_queue.qsize() >= LOG_QUEUE_LIMIT:
                self.log_queue.get_nowait()
        except Exception:
            pass
        self.log_queue.put((key, stamped_text))

    def _status_text(self) -> str:
        labels = [label for key, label in self.running_labels.items() if key in self.running_processes]
        if not labels:
            return "空闲"
        return "运行中：" + "、".join(labels)

    def _set_status(self, text: str) -> None:
        try:
            while self.log_queue.qsize() >= LOG_QUEUE_LIMIT:
                self.log_queue.get_nowait()
        except Exception:
            pass
        self.log_queue.put(f"__STATUS__{text}")

    def _has_running_tasks(self) -> bool:
        for proc in self.running_processes.values():
            try:
                if proc is not None and proc.poll() is None:
                    return True
            except Exception:
                continue
        return False

    def _hide_to_tray(self) -> None:
        if self._exiting:
            self._final_exit()
            return
        if not self._tray_icon or not self._tray_icon.installed:
            if self._tray_icon and self._tray_icon.install():
                self.withdraw()
                self._put_log("[系统] 窗口已隐藏到右下角托盘；正在运行的任务会继续执行。", task_key=self.active_task.get())
                return
            detail = self._tray_icon.last_error if self._tray_icon else "托盘组件未创建"
            if messagebox.askyesno("退出程序", f"托盘图标不可用：{detail}。\n是否直接退出程序？"):
                self._final_exit()
            return
        self.withdraw()
        self._put_log("[系统] 窗口已隐藏到右下角托盘；正在运行的任务会继续执行。", task_key=self.active_task.get())

    def _restore_from_tray(self) -> None:
        if self._exiting:
            return
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
            self._render_current_log()
        except Exception:
            pass

    def _post_tray_action(self, action: str) -> None:
        try:
            self._tray_actions.put_nowait(action)
        except Exception:
            pass

    def _poll_tray_actions(self) -> None:
        try:
            while True:
                action = self._tray_actions.get_nowait()
                if action == "show":
                    self._restore_from_tray()
                elif action == "exit":
                    self._quit_from_tray()
                elif action == "exit_force":
                    self._quit_from_tray(confirm=False)
        except queue.Empty:
            pass
        except Exception:
            pass
        if not self._exiting:
            self.after(200, self._poll_tray_actions)

    def _quit_from_tray(self, confirm: bool = True) -> None:
        if self._has_running_tasks():
            if confirm:
                self._restore_from_tray()
                ok = messagebox.askyesno("退出程序", "当前仍有任务在运行。确定要退出并停止这些任务吗？", parent=self)
                if not ok:
                    return
            for proc in list(self.running_processes.values()):
                try:
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
        self._final_exit()

    def _final_exit(self) -> None:
        self._exiting = True
        try:
            if self._settings_save_after_id:
                try:
                    self.after_cancel(self._settings_save_after_id)
                except Exception:
                    pass
                self._settings_save_after_id = None
            self._save_workbench_settings()
        except Exception:
            pass
        try:
            if self._tray_icon:
                self._tray_icon.shutdown()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _render_current_log(self) -> None:
        if not hasattr(self, "log_box"):
            return
        key = self.active_task.get()
        lines = self.log_buffers.get(key, [])
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        if lines:
            self.log_box.insert("end", "\n".join(lines) + "\n")
            self.log_box.see("end")

    def _poll_logs(self) -> None:
        processed = 0
        active_lines: list[str] = []
        active_key = self.active_task.get()
        visible = True
        try:
            visible = self.state() != "withdrawn"
        except Exception:
            visible = True
        try:
            while processed < LOG_POLL_BATCH_LIMIT:
                item = self.log_queue.get_nowait()
                processed += 1
                if isinstance(item, str) and item.startswith("__STATUS__"):
                    self.status_label.configure(text=item.replace("__STATUS__", "", 1))
                    continue
                if isinstance(item, tuple):
                    key, text = item
                else:
                    key, text = self.active_task.get(), str(item)
                buffer = self.log_buffers.setdefault(key, [])
                buffer.append(text)
                if len(buffer) > LOG_BUFFER_LIMIT:
                    del buffer[: len(buffer) - LOG_BUFFER_LIMIT]
                if visible and key == active_key:
                    active_lines.append(text)
        except queue.Empty:
            pass
        if active_lines and hasattr(self, "log_box"):
            self.log_box.insert("end", "\n".join(active_lines) + "\n")
            self.log_box.see("end")
        delay = 30 if processed >= LOG_POLL_BATCH_LIMIT else (LOG_POLL_BUSY_MS if self._has_running_tasks() else LOG_POLL_IDLE_MS)
        self.after(delay, self._poll_logs)

    def _clear_log(self) -> None:
        key = self.active_task.get()
        self.log_buffers[key] = []
        self.log_last_ts.pop(key, None)
        self.log_box.delete("1.0", "end")


def main(initial_mode: str = "research") -> None:
    app = UnifiedWorkbench(initial_mode=initial_mode)
    app.mainloop()


if __name__ == "__main__":
    main()
