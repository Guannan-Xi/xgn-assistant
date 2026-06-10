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
import webbrowser
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
TOTAL_CONSOLE_URL = os.environ.get("XGN_TOTAL_CONSOLE_URL", "http://127.0.0.1:8767/assistant/")


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
    "DeepSeek Chat（官方润色）",
    "Gemini 3 Flash Preview",
    "Gemini 2.5 Flash",
]
IMAGE_ENGINE_OPTIONS = [
    "GPT Image 2",
    "Gemini 3 Pro Image Preview",
    "Gemini 3.1 Flash Image Preview",
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
    "image": "鐢熷浘涓撶敤 Key",
    "gemini": "Gemini Key",
    "deepseek": "DeepSeek Key",
}

RESEARCH_ISSUE_DIR_RE = re.compile(r"^\d{8}(?:[锛?]\d+[锛?])?$")
RESEARCH_ISSUE_MARKERS = (
    "00_鏂囩尞淇℃伅.json",
    "00_鍊欓€夋枃鐚竻鍗?json",
    "01_鏍忕洰绱犳潗.json",
    "02_鍙ｆ挱鍙拌瘝.txt",
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
    if "gpt-5.5 mini" in lower:
        return "gpt-5.5"
    if "gpt-5.5" in lower:
        return "gpt-5.5"
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
        return "鐢熷浘涓撶敤锝淕PT Image 2"
    if "gemini 3 pro" in lower or value == "gemini-3-pro-image-preview":
        return "鐢熷浘涓撶敤锝淕emini 3 Pro Image Preview"
    if "gemini 3.1" in lower or value == "gemini-3.1-flash-image-preview":
        return "鐢熷浘涓撶敤锝淕emini 3.1 Flash Image Preview"
    if "imagen" in lower:
        return "鐢熷浘涓撶敤锝淕emini 3 Pro Image Preview"
    return "鐢熷浘涓撶敤锝淕PT Image 2"


def _key_hint(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "not set"
    return f"set, {len(text)} chars"


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
            text = "N"
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
            self._set_error("Tray thread startup timed out; shell notification area did not return initialization result.")
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
                pystray.MenuItem("Show main window", lambda icon, item: self.app._post_tray_action("show"), default=True),
                pystray.MenuItem("Exit", lambda icon, item: self.app._post_tray_action("exit_force")),
            )
            self._pystray_icon = pystray.Icon("quanlan_piglet", image, "Quanlan Assistant", menu)
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
                    self._set_error(f"RegisterClassW failed锛學in32閿欒鐮?{err}")
            self.hwnd = user32.CreateWindowExW(0, self._class_name, self._class_name, 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                self._set_error(f"CreateWindowExW failed锛學in32閿欒鐮?{win_error()}")
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
            nid.szTip = "寰堟湁鑴戝瓙鐨勫皬鐚悊"
            self._nid = nid
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self._set_error(f"Shell_NotifyIconW(NIM_ADD) failed锛學in32閿欒鐮?{win_error()}")
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
        user32.AppendMenuW(menu, 0x0000, self.ID_SHOW, "Show main window")
        user32.AppendMenuW(menu, 0x0800, 0, None)
        user32.AppendMenuW(menu, 0x0000, self.ID_EXIT, "Exit")
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
        self.title("寰堟湁鑴戝瓙鐨勫皬鐚悊")
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
            self._put_log("[system] Tray background mode enabled; closing the window hides it while tasks continue.", task_key=self.active_task.get())
        else:
            detail = self._tray_icon.last_error or "no detailed error"
            self._put_log(f"[system] Tray icon initialization failed: {detail}; will retry when closing the window.", task_key=self.active_task.get())
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
        self.image_engine = tk.StringVar(value="鐢熷浘涓撶敤锝淕PT Image 2")
        self.culture_text_provider = tk.StringVar(value="openai")
        self.culture_text_model = tk.StringVar(value="gpt-5.5")
        self.culture_polish_provider = tk.StringVar(value="deepseek")
        self.culture_polish_model = tk.StringVar(value="deepseek-chat")
        self.culture_image_provider = tk.StringVar(value="openai")
        self.culture_image_model = tk.StringVar(value="gpt-image-2")
        self.foreign_base_url = tk.StringVar(value="https://www.fhl.mom/v1")
        self.deepseek_base_url = tk.StringVar(value="https://api.deepseek.com")
        self.culture_text_base_url = tk.StringVar(value="")
        self.culture_polish_base_url = tk.StringVar(value="")
        self.culture_image_base_url = tk.StringVar(value="")
        self.research_text_base_url = tk.StringVar(value="")
        self.research_polish_base_url = tk.StringVar(value="")
        self.research_image_base_url = tk.StringVar(value="")
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
            run_switch = _read_json(CULTURE_ROOT / "config" / "杩愯寮€鍏?json")
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
            "culture_text_base_url": self.culture_text_base_url.get(),
            "culture_polish_base_url": self.culture_polish_base_url.get(),
            "culture_image_base_url": self.culture_image_base_url.get(),
            "research_text_base_url": self.research_text_base_url.get(),
            "research_polish_base_url": self.research_polish_base_url.get(),
            "research_image_base_url": self.research_image_base_url.get(),
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
            "culture_text_base_url", "culture_polish_base_url", "culture_image_base_url",
            "research_text_base_url", "research_polish_base_url", "research_image_base_url",
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
        self._put_log("Model defaults and current keys were saved; they will load automatically next time.")

    def _load_model_defaults_with_log(self) -> None:
        data = _read_json(MODEL_DEFAULTS)
        if not data:
            self._put_log("No saved model defaults yet.")
            return
        self._apply_model_defaults_payload(data)
        self._save_model_config(log=False)
        self._save_workbench_settings()
        self._put_log("Model defaults loaded.")

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
            if completed.returncode == 0 and "upgraded" in message.lower():
                self._put_log(f"[system] Release version upgraded while idle: {message}", task_key=self.active_task.get())
                self._put_log("[system] Restart the release window after tasks finish so the new code fully takes effect.", task_key=self.active_task.get())
            elif message and "no pending update" not in message.lower():
                self._put_log(f"[system] Release upgrade check: {message}", task_key=self.active_task.get())
        except Exception as exc:
            self._put_log(f"[绯荤粺] 鍙戝竷鐗堣嚜鍔ㄥ崌绾ф鏌ュけ璐ワ細{type(exc).__name__}: {exc}", task_key=self.active_task.get())

    def _runtime_dir(self, task_key: str) -> Path:
        path = RUNTIME_ROOT / re.sub(r"[^A-Za-z0-9_.-]+", "_", task_key or "task")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _email_config_snapshot(self) -> tuple[dict, dict] | None:
        try:
            port = int(str(self.smtp_port.get()).strip() or "465")
        except Exception:
            messagebox.showwarning("Invalid port", "SMTP port must be a number.")
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
            "subject_template": "Materials generated: {part_name}",
        }
        return research_email, culture_email

    def _research_model_scheme_snapshot(self) -> dict:
        scheme = _read_json(RESEARCH_ROOT / "quanlan_model_scheme.json")
        scheme.update({
            "text_engine": self.text_engine.get(),
            "review_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "content_style": "绉戝缁忓吀瑙ｈ",
            "call_mode": "API鑷姩璋冪敤",
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
        env.setdefault("AMP_IMAGE_QUALITY", "low")
        env.setdefault("AMP_IMAGE_COST_MODE", "lowest")
        env.setdefault("AMP_IMAGE_MAX_RETRIES", "1")
        env.setdefault("OPENAI_IMAGE_RETRY_DELAYS", "0,8")
        env.setdefault("OPENAI_IMAGE_TIMEOUT", "240")
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
        env["CULTURE_TEXT_BASE_URL"] = self._normalized_model_base_url(self.culture_text_base_url)
        env["CULTURE_POLISH_BASE_URL"] = self._normalized_model_base_url(self.culture_polish_base_url)
        env["CULTURE_IMAGE_BASE_URL"] = self._normalized_model_base_url(self.culture_image_base_url)
        env["RESEARCH_TEXT_BASE_URL"] = self._normalized_model_base_url(self.research_text_base_url)
        env["RESEARCH_POLISH_BASE_URL"] = self._normalized_model_base_url(self.research_polish_base_url)
        env["RESEARCH_IMAGE_BASE_URL"] = self._normalized_model_base_url(self.research_image_base_url)
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

            run_switch = _read_json(CULTURE_ROOT / "config" / "杩愯寮€鍏?json")
            run_switch["email_delivery"] = culture_email
            run_switch_path = runtime_dir / "杩愯寮€鍏?json"
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
            self.culture_text_base_url, self.culture_polish_base_url, self.culture_image_base_url,
            self.research_text_base_url, self.research_polish_base_url, self.research_image_base_url,
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
        ttk.Label(side, text="Quanlan Assistant", style="SideTitle.TLabel").pack(anchor="w")
        ttk.Label(side, text="Task parameters live here; models, keys, and email are configured in the web console.", style="SideBody.TLabel", wraplength=190).pack(anchor="w", pady=(8, 20))
        ttk.Button(side, text="Research digest", style="Mode.TButton", command=lambda: self._set_task("research_digest")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="Science classic", style="Mode.TButton", command=lambda: self._set_task("science_classic")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="Culture", style="Mode.TButton", command=lambda: self._set_task("culture")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="Auto clip", style="Mode.TButton", command=lambda: self._set_task("auto_clip")).pack(fill="x", pady=(0, 10))
        ttk.Button(side, text="Learning books/PDF", style="Mode.TButton", command=lambda: self._set_task("learning_books")).pack(fill="x")
        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=20)
        ttk.Button(side, text="Open output folder", style="Tool.TButton", command=self._open_current_output_dir).pack(fill="x", pady=(0, 8))
        ttk.Button(side, text="Clear target folder", style="Tool.TButton", command=self._clear_current_output_dir).pack(fill="x", pady=(0, 8))
        ttk.Button(side, text="Advanced config", style="Tool.TButton", command=self._open_advanced_config).pack(fill="x", pady=(0, 8))
        ttk.Button(side, text="Stop current task", style="Tool.TButton", command=self._stop_process).pack(fill="x")

        main = ttk.Frame(root, style="Root.TFrame", padding=(18, 18, 18, 14))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        header = ttk.Frame(main, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(header, text="", style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.status_label = ttk.Label(header, text="绌洪棽", background="#f4f6f8", foreground="#687384")
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
        self.log_title_label = ttk.Label(log_header, text="杩愯鏃ュ織", style="PanelTitle.TLabel")
        self.log_title_label.grid(row=0, column=0, sticky="w")
        ttk.Button(log_header, text="娓呯┖", style="Tool.TButton", command=self._clear_log).grid(row=0, column=1, sticky="e")
        self.log_box = scrolledtext.ScrolledText(log_panel, height=16, wrap="word", font=("Consolas", 10), bg="#10151d", fg="#e6edf5", insertbackground="#e6edf5")
        self.log_box.grid(row=1, column=0, sticky="nsew")

    def _build_model_page(self) -> None:
        ttk.Label(self.model_page, text="妯″瀷鏂规", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._combo_row(self.model_page, 1, "绉戠爺/绉戝缁忓吀 鏂囨妯″瀷", self.text_engine, TEXT_ENGINE_OPTIONS)
        self._combo_row(self.model_page, 2, "绉戠爺/绉戝缁忓吀 娑﹁壊妯″瀷", self.polish_engine, ["璺熼殢鑴氭湰妯″瀷", *TEXT_ENGINE_OPTIONS])
        self._combo_row(self.model_page, 3, "绉戠爺/绉戝缁忓吀 鐢熷浘妯″瀷", self.image_engine, IMAGE_ENGINE_OPTIONS)
        self._combo_row(self.model_page, 4, "鏂囧彶鏂囨湰 Provider", self.culture_text_provider, ("openai", "gemini", "deepseek", "dry-run"))
        self._entry_row(self.model_page, 5, "鏂囧彶鏂囨湰妯″瀷", self.culture_text_model, width=28)
        self._combo_row(self.model_page, 6, "鏂囧彶娑﹁壊 Provider", self.culture_polish_provider, ("deepseek", "openai", "gemini", "dry-run"))
        self._entry_row(self.model_page, 7, "鏂囧彶娑﹁壊妯″瀷", self.culture_polish_model, width=28)
        self._combo_row(self.model_page, 8, "鏂囧彶鐢熷浘 Provider", self.culture_image_provider, ("openai", "gemini", "none", "dry-run"))
        self._entry_row(self.model_page, 9, "鏂囧彶鐢熷浘妯″瀷", self.culture_image_model, width=28)
        self._entry_row(self.model_page, 10, "鍥藉妯″瀷涓浆 URL", self.foreign_base_url)
        self._entry_row(self.model_page, 11, "DeepSeek 瀹樻柟 URL", self.deepseek_base_url)

        ttk.Label(self.model_page, text="Key 鏂囦欢", style="PanelTitle.TLabel").grid(row=18, column=0, columnspan=3, sticky="w", pady=(16, 8))
        row = 19
        for key_name, label in KEY_LABELS.items():
            self._key_row(row, label, key_name)
            row += 1
        actions = ttk.Frame(self.model_page, style="Panel.TFrame")
        actions.grid(row=row, column=1, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Save model config and keys", style="Primary.TButton", command=self._save_model_config_with_log).pack(side="left")
        ttk.Button(actions, text="Save as defaults", style="Tool.TButton", command=self._save_model_defaults_with_log).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Load defaults", style="Tool.TButton", command=self._load_model_defaults_with_log).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Test text model", style="Tool.TButton", command=self._test_text_model).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Test image model", style="Tool.TButton", command=self._test_image_model).pack(side="left", padx=(10, 0))
        tests = ttk.Frame(self.model_page, style="Panel.TFrame")
        tests.grid(row=row + 1, column=1, sticky="ew", pady=(10, 0))
        for text, command in [
            ("Test culture text", lambda: self._test_named_model("culture_text")),
            ("Test culture polish", lambda: self._test_named_model("culture_polish")),
            ("Test culture image", lambda: self._test_named_model("culture_image")),
            ("Test research text", lambda: self._test_named_model("research_text")),
            ("Test research polish", lambda: self._test_named_model("research_polish")),
            ("Test research image", lambda: self._test_named_model("research_image")),
        ]:
            ttk.Button(tests, text=text, style="Tool.TButton", command=command).pack(side="left", padx=(0, 8), pady=(0, 6))
        ttk.Label(
            self.model_page,
            text="Defaults save model choices, base URLs, and current key status to quanlan_model_defaults.json; they load automatically next time.",
            style="Subtle.TLabel",
        ).grid(row=row + 2, column=1, sticky="w", pady=(8, 0))
        self._refresh_key_status()

    def _build_email_page(self) -> None:
        ttk.Label(self.email_page, text="Email delivery", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Checkbutton(self.email_page, text="Compress and send email after task completion", variable=self.email_enabled).grid(row=1, column=1, sticky="w", pady=6)
        self._entry_row(self.email_page, 2, "Recipient email", self.email_recipient)
        self._entry_row(self.email_page, 3, "SMTP server", self.smtp_host, width=34)
        self._entry_row(self.email_page, 4, "Port", self.smtp_port, width=12)
        self._entry_row(self.email_page, 5, "Login account", self.smtp_user, width=34)
        self._entry_row(self.email_page, 6, "Sender", self.smtp_sender, width=34)
        self._password_row(self.email_page, 7, "SMTP auth code", self.smtp_password, "smtp")
        switches = ttk.Frame(self.email_page, style="Panel.TFrame")
        switches.grid(row=8, column=1, sticky="w", pady=6)
        ttk.Checkbutton(switches, text="SSL", variable=self.smtp_ssl).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(switches, text="TLS", variable=self.smtp_tls).pack(side="left")
        actions = ttk.Frame(self.email_page, style="Panel.TFrame")
        actions.grid(row=9, column=1, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="QQ email preset", style="Tool.TButton", command=self._apply_qq_email_preset).pack(side="left")
        ttk.Button(actions, text="Save email config", style="Primary.TButton", command=self._save_email_config_with_log).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Test SMTP", style="Tool.TButton", command=self._test_email).pack(side="left", padx=(10, 0))
        ttk.Label(
            self.email_page,
            text="SMTP auth code is written only to local config files and is not shown in logs.",
            style="Subtle.TLabel",
        ).grid(row=10, column=1, sticky="w", pady=(10, 0))

    def _open_total_console(self, fragment: str = "") -> None:
        url = TOTAL_CONSOLE_URL
        if fragment:
            url = url.split("#", 1)[0].rstrip("/") + f"/{fragment}"
        webbrowser.open(url)
        self._put_log(f"宸叉墦寮€鎬绘帶鍙帮細{url}")

    def _build_centralized_config_page(self, parent: ttk.Frame, title: str, body: str, fragment: str) -> None:
        ttk.Label(parent, text=title, style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(parent, text=body, style="Subtle.TLabel", wraplength=760).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))
        actions = ttk.Frame(parent, style="Panel.TFrame")
        actions.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Button(actions, text="Open console", style="Primary.TButton", command=lambda: self._open_total_console(fragment)).pack(side="left")
        ttk.Button(actions, text="Open tools", style="Tool.TButton", command=lambda: self._open_total_console("#more")).pack(side="left", padx=(10, 0))
        ttk.Label(
            parent,
            text="This legacy page still reads local config saved by the central console when tasks start, but model, key, and SMTP editing now live in the console.",
            style="Subtle.TLabel",
            wraplength=760,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(16, 0))

    def _open_advanced_config(self) -> None:
        win = tk.Toplevel(self)
        win.title("楂樼骇閰嶇疆")
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
        self._build_centralized_config_page(
            self.model_page,
            "Models and keys are managed by the central console",
            "Model URLs, model names, profile switching, and model keys are centralized in the web console. This legacy desktop page no longer saves or tests model config.",
            "#model",
        )
        self._build_centralized_config_page(
            self.email_page,
            "Email and SMTP are managed by the central console",
            "Recipient email, SMTP server, account, and auth code are centralized in the web console. This legacy desktop page no longer saves or tests email config.",
            "#more",
        )
        notebook.add(self.task_settings_page, text="Task params")
        notebook.add(self.model_page, text="Models/Keys")
        notebook.add(self.email_page, text="Email/SMTP")

    def _build_task_settings_page(self) -> None:
        ttk.Label(self.task_settings_page, text="Research digest params", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_settings_page, 1, "Search days", self.research_days, width=12)
        self._entry_row(self.task_settings_page, 2, "Article count", self.research_max_articles, width=12)
        ttk.Checkbutton(self.task_settings_page, text="Skip image API and generate local placeholders only", variable=self.research_skip_image_api).grid(row=3, column=1, sticky="w", pady=6)

        ttk.Label(self.task_settings_page, text="Science classic workflow", style="PanelTitle.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(18, 8))
        science = ttk.Frame(self.task_settings_page, style="Panel.TFrame")
        science.grid(row=5, column=1, sticky="w", pady=6)
        for text, var in [("鍒囩珷鑺?瑙ｆ瀽", self.science_flow_parse), ("鐢熸垚鑴氭湰/LRC", self.science_flow_script), ("鐢熸垚閰嶅浘", self.science_flow_image), ("寮哄埗閲嶇粯閰嶅浘", self.science_redraw)]:
            ttk.Checkbutton(science, text=text, variable=var).pack(side="left", padx=(0, 14))

        ttk.Label(self.task_settings_page, text="鏂囧彶灏忕鍙傛暟", style="PanelTitle.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(18, 8))
        self._combo_row(self.task_settings_page, 7, "璧峰闃舵", self.culture_start_stage, CULTURE_STAGES)
        self._entry_row(self.task_settings_page, 8, "Test B image count", self.culture_test_b_limit, width=12)
        culture = ttk.Frame(self.task_settings_page, style="Panel.TFrame")
        culture.grid(row=9, column=1, sticky="w", pady=6)
        for text, var in [
            ("Auto resume", self.culture_auto_resume),
            ("Reuse existing text", self.culture_skip_existing_text),
            ("Reuse existing images", self.culture_skip_existing_images),
            ("Skip image generation", self.culture_skip_images),
            ("Postprocess only", self.culture_only_postprocess),
            ("Do not split assets", self.culture_no_split_assets),
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
            "research_digest": "Research digest",
            "science_classic": "Science classic",
            "culture": "Culture book workflow",
            "auto_clip": "Auto clip",
            "learning_books": "Learning books/PDF",
        }
        self.title_label.configure(text=title_map.get(task, "Quanlan Assistant"))
        if hasattr(self, "log_title_label"):
            self.log_title_label.configure(text=f"Run log - {title_map.get(task, 'current mode')}")
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
        ttk.Label(self.task_page, text="Research digest", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "Output folder", self.research_out_dir, browse=lambda: self._browse_dir(self.research_out_dir))
        issue_row = ttk.Frame(self.task_page, style="Panel.TFrame")
        issue_row.grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(self.task_page, text="Daily issues", background="#ffffff").grid(row=2, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Combobox(issue_row, textvariable=self.research_issue_count, values=("1", "2", "3"), state="readonly", width=8).pack(side="left")
        ttk.Label(issue_row, text="Issue no.", background="#ffffff").pack(side="left", padx=(14, 6))
        ttk.Combobox(issue_row, textvariable=self.research_issue_no, values=("1", "2", "3"), state="readonly", width=8).pack(side="left")
        self._entry_row(self.task_page, 3, "Journal requirement", self.research_journal_fuzzy)
        self._entry_row(self.task_page, 4, "Journal list", self.research_journals)
        self._entry_row(self.task_page, 5, "Article list", self.research_article_list, browse=self._browse_article_list)
        self._entry_row(self.task_page, 6, "Resume folder", self.research_resume_dir, browse=lambda: self._browse_dir(self.research_resume_dir))
        actions = ttk.Frame(self.task_page, style="Panel.TFrame")
        actions.grid(row=7, column=1, sticky="ew", pady=(14, 0))
        ttk.Button(actions, text="Normalize journals", style="Tool.TButton", command=self._normalize_journals_with_gpt).pack(side="left")
        ttk.Button(actions, text="Build article list", style="Tool.TButton", command=self._build_research_article_list).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Create from list", style="Primary.TButton", command=self._run_research_digest_continue_list).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Resume issue", style="Tool.TButton", command=self._resume_research_digest_issue).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Refresh list", style="Tool.TButton", command=self._refresh_article_list_preview).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Reset progress", style="Tool.TButton", command=self._reset_research_article_progress).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Stop", style="Tool.TButton", command=self._stop_process).pack(side="left", padx=(10, 0))
        ttk.Label(
            self.task_page,
            text="Build or refresh the article list first, then create materials from it. For resume, choose a specific issue folder.",
            style="Subtle.TLabel",
        ).grid(row=8, column=1, sticky="w", pady=(8, 0))
        ttk.Label(self.task_page, text="Article list preview", style="PanelTitle.TLabel").grid(row=9, column=0, columnspan=3, sticky="w", pady=(18, 8))
        self.article_list_preview = scrolledtext.ScrolledText(self.task_page, height=12, wrap="word", font=("Consolas", 9))
        self.article_list_preview.grid(row=10, column=0, columnspan=3, sticky="nsew")
        self.task_page.rowconfigure(10, weight=1)
        self._refresh_article_list_preview()

    def _render_science_classic(self) -> None:
        ttk.Label(self.task_page, text="Science classic", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "Book/paper PDF", self.science_pdf, browse=lambda: self._browse_file(self.science_pdf, [("PDF", "*.pdf"), ("All files", "*.*")]))
        self._entry_row(self.task_page, 2, "Output folder", self.science_out_dir, browse=lambda: self._browse_dir(self.science_out_dir))
        self._action_row(self.task_page, 3, [("Start science classic", self._run_science_classic), ("Test B image", self._test_science_classic_b_image), ("Stop", self._stop_process)])
        ttk.Label(self.task_page, text="Workflow switches are in Advanced config; models, keys, and email are configured in the web console.", style="Subtle.TLabel").grid(row=4, column=1, sticky="w", pady=(8, 0))

    def _render_culture(self) -> None:
        ttk.Label(self.task_page, text="Culture workflow", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "Book PDF", self.culture_book, browse=lambda: self._browse_file(self.culture_book, [("PDF", "*.pdf"), ("All files", "*.*")]))
        self._entry_row(self.task_page, 2, "Output folder", self.culture_out_dir, browse=lambda: self._browse_dir(self.culture_out_dir))
        self._entry_row(self.task_page, 3, "Continue folder", self.culture_continue_folder, browse=lambda: self._browse_dir(self.culture_continue_folder))
        self._action_row(self.task_page, 4, [("Start culture generation", self._run_culture), ("Test B image", self._test_culture_b_image), ("Stop", self._stop_process)])
        ttk.Label(self.task_page, text="Stage, reuse, image generation, and postprocess options are in Advanced config; models, keys, and email are configured in the web console.", style="Subtle.TLabel").grid(row=5, column=1, sticky="w", pady=(8, 0))

    def _render_auto_clip(self) -> None:
        ttk.Label(self.task_page, text="Auto clip", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._entry_row(self.task_page, 1, "Image assets folder", self.auto_clip_image_dir, browse=lambda: self._browse_auto_clip_dir(self.auto_clip_image_dir))
        self._entry_row(self.task_page, 2, "LRC assets folder", self.auto_clip_lrc_dir, browse=lambda: self._browse_auto_clip_dir(self.auto_clip_lrc_dir))
        self._entry_row(self.task_page, 3, "Output folder", self.auto_clip_output_dir, browse=lambda: self._browse_dir(self.auto_clip_output_dir))
        self._action_row(
            self.task_page,
            4,
            [
                ("Start auto clip", self._run_auto_clip),
                ("Open output folder", lambda: self._open_path(self.auto_clip_output_dir.get())),
                ("Refresh assets", self._refresh_auto_clip_assets_preview),
                ("Stop", self._stop_process),
            ],
        )
        ttk.Label(
            self.task_page,
            text="Each LRC line may contain a code such as [B26] or B26; matching image filenames are used to create one MP4 and SRT per LRC.",
            style="Subtle.TLabel",
        ).grid(row=5, column=1, sticky="w", pady=(8, 0))
        ttk.Label(self.task_page, text="Collected assets", style="PanelTitle.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(18, 8))
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
        ttk.Label(self.task_page, text="Learning books/PDF", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        actions = ttk.Frame(self.task_page, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        ttk.Button(actions, text="Refresh book status", style="Primary.TButton", command=self._refresh_learning_books).pack(side="left")
        ttk.Button(actions, text="Open PDF folder", style="Tool.TButton", command=self._open_learning_pdf_dir).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Open report file", style="Tool.TButton", command=self._open_learning_book_candidates_file).pack(side="left", padx=(10, 0))
        ttk.Label(
            self.task_page,
            text="This view shows candidate books found by the optimizer. Located or downloaded PDFs show paths; missing PDFs are marked for legal source follow-up.",
            style="Subtle.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 8))
        columns = ("status", "category", "title", "author", "pdf")
        self.learning_books_tree = ttk.Treeview(self.task_page, columns=columns, show="headings", height=14)
        headings = {
            "status": "PDF status",
            "category": "Category",
            "title": "Title",
            "author": "Author",
            "pdf": "PDF/reason",
        }
        widths = {"status": 110, "category": 120, "title": 180, "author": 160, "pdf": 420}
        for key in columns:
            self.learning_books_tree.heading(key, text=headings[key])
            self.learning_books_tree.column(key, width=widths[key], anchor="w")
        self.learning_books_tree.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.learning_books_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_learning_book_detail())
        ttk.Label(self.task_page, text="閫変腑涔︾睄璇︽儏", style="PanelTitle.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(14, 6))
        self.learning_books_detail = scrolledtext.ScrolledText(self.task_page, height=8, wrap="word", font=("Microsoft YaHei UI", 10))
        self.learning_books_detail.grid(row=5, column=0, columnspan=3, sticky="nsew")
        self.task_page.rowconfigure(3, weight=3)
        self.task_page.rowconfigure(5, weight=1)
        self._refresh_learning_books()

    def _entry_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, width: int | None = None, browse=None) -> None:
        ttk.Label(parent, text=label, background="#ffffff").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Entry(parent, textvariable=var, width=width or 72).grid(row=row, column=1, sticky="ew", pady=6)
        if browse:
            ttk.Button(parent, text="閫夋嫨", style="Tool.TButton", command=browse).grid(row=row, column=2, sticky="e", padx=(10, 0), pady=6)

    def _combo_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, values) -> None:
        ttk.Label(parent, text=label, background="#ffffff").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Combobox(parent, textvariable=var, values=tuple(values), state="readonly", width=34).grid(row=row, column=1, sticky="w", pady=6)

    def _password_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, key: str) -> None:
        ttk.Label(parent, text=label, background="#ffffff").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        entry = ttk.Entry(parent, textvariable=var, show="*", width=72)
        entry.grid(row=row, column=1, sticky="ew", pady=6)
        self._key_entries[key] = entry
        ttk.Button(parent, text="鏄剧ず/闅愯棌", style="Tool.TButton", command=lambda k=key: self._toggle_secret(k)).grid(row=row, column=2, sticky="e", padx=(10, 0), pady=6)

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
            return [f"{label}: 鏈€夋嫨鎴栫洰褰曚笉瀛樺湪"]
        files = sorted(
            (path for path in root.iterdir() if path.is_file() and path.suffix.lower() in extensions),
            key=lambda path: path.name.lower(),
        )
        rows = [f"{label}: {len(files)} 涓? {root}"]
        for path in files[:AUTO_CLIP_ASSET_PREVIEW_LIMIT]:
            rows.append(f"  - {path.name}")
        if len(files) > AUTO_CLIP_ASSET_PREVIEW_LIMIT:
            rows.append(f"  ... 杩樻湁 {len(files) - AUTO_CLIP_ASSET_PREVIEW_LIMIT} 涓湭鏄剧ず")
        return rows

    def _refresh_auto_clip_assets_preview(self) -> None:
        if self.auto_clip_assets_list is None:
            return
        rows: list[str] = []
        rows.extend(self._preview_files(self.auto_clip_image_dir.get(), AUTO_CLIP_IMAGE_EXTENSIONS, "Image assets"))
        rows.append("")
        rows.extend(self._preview_files(self.auto_clip_lrc_dir.get(), AUTO_CLIP_LRC_EXTENSIONS, "LRC assets"))
        rows.append("")
        rows.extend(self._preview_files(self.auto_clip_lrc_dir.get(), AUTO_CLIP_AUDIO_EXTENSIONS, "Audio in same folder"))
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
            return "found"
        if status == "downloaded":
            return "downloaded"
        if download == "legal_source_required":
            return "legal source required"
        if status == "missing_pdf":
            return "missing PDF"
        return status or download or "unknown"

    def _book_pdf_summary(self, item: dict) -> str:
        matches = item.get("pdf_matches") if isinstance(item.get("pdf_matches"), list) else []
        if matches:
            return str(matches[0])
        download = item.get("download_result") if isinstance(item.get("download_result"), dict) else {}
        reason = str(download.get("reason") or item.get("download_status") or "")
        if reason == "legal_source_required":
            return "No legal public PDF download source configured."
        if reason:
            return reason
        return "Waiting for optimizer to continue searching."

    def _refresh_learning_books(self) -> None:
        if self.learning_books_tree is None:
            return
        payload = self._load_learning_books_payload()
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        self.learning_books_tree.delete(*self.learning_books_tree.get_children())
        if not candidates:
            self.learning_books_tree.insert("", "end", values=("No book list", "", "Start optimizer learning first", "", "self_optimizer_book_candidates.json not found"))
            self._set_learning_book_detail("No optimizer book-list file was found yet.\n\nStart the self-learning optimizer first; it should generate self_optimizer_book_candidates.json.")
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
                f"Book list file: {source or 'not found'}",
                f"Updated at: {payload.get('updated_at') or 'unknown'}",
                f"Scanned PDFs: {scan.get('scanned_pdfs', 0)}",
                f"Matched/downloaded: {scan.get('matched', 0)}",
                f"Missing PDF: {scan.get('missing_pdf', 0)}",
                f"Legal source required: {scan.get('legal_source_required', 0)}",
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
            f"Title: {item.get('title') or ''}",
            f"Author: {item.get('author') or ''}",
            f"Category: {item.get('category') or ''}",
            f"PDF status: {self._book_status_label(item)}",
            f"PDF path: {matches[0] if matches else 'none'}",
            "",
            f"Suggested angle: {item.get('future_angle') or ''}",
            f"Reason: {item.get('reason') or ''}",
            f"Copyright/source status: {item.get('source_status') or 'unknown'}",
            "",
            "Legal source pages:",
            *(f"  {value}" for value in source_pages[:8]),
            "",
            "Follow-up search queries:",
            *(f"  {value}" for value in searches[:8]),
        ]
        self._set_learning_book_detail("\n".join(lines))

    def _open_learning_book_candidates_file(self) -> None:
        path = self._book_candidates_file()
        if not path:
            messagebox.showinfo("No book list", "self_optimizer_book_candidates.json was not found yet.")
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
        messagebox.showinfo("No PDF folder", "No optimizer PDF download folder was found yet.")

    def _open_path(self, path: str) -> None:
        value = str(path or "").strip()
        if not value:
            messagebox.showinfo("No output folder", "There is no output folder to open yet.")
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
            messagebox.showerror("鏃犳硶鎵撳紑鐩綍", str(exc))

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
            messagebox.showinfo("Task running", "Stop or wait for the current task before clearing the target folder.")
            return
        raw = self._last_output_var_for_task().get().strip() or self._current_output_dir()
        if not raw:
            messagebox.showinfo("No target folder", "The current task has no target folder to clear.")
            return
        target = Path(raw)
        if not target.exists():
            messagebox.showinfo("Target folder missing", f"Target folder does not exist:\n{target}")
            return
        if not target.is_dir():
            messagebox.showwarning("Target is not a folder", f"The current target is not a folder and cannot be cleared:\n{target}")
            return
        if not self._is_safe_clear_target(target):
            messagebox.showwarning("Clear refused", f"This folder is too broad or belongs to the project root, so clearing was refused:\n{target}")
            return
        ok = messagebox.askyesno(
            "Confirm clear target folder",
            f"This will delete all contents inside this folder while keeping the folder itself:\n\n{target}\n\nThis cannot be undone. Continue?",
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
                        self._put_log(f"Backed up culture episode outline to: {preserved[0].parent}")
                except Exception as exc:
                    self._put_log(f"Culture outline backup failed; continuing clear: {type(exc).__name__}: {exc}")
            removed = 0
            for child in target.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed += 1
            self._put_log(f"Cleared target folder: {target}; removed {removed} item(s).")
            if self.active_task.get() == "research_digest" and self.research_article_list.get().strip():
                reset_ok = messagebox.askyesno(
                    "Reset article-list progress?",
                    "The target folder has been cleared. Also clear the current article list's produced markers?\n\nChoose yes to regenerate from the first article next time.",
                )
                if reset_ok:
                    self._reset_research_article_progress(ask=False)
        except Exception as exc:
            messagebox.showerror("娓呯┖澶辫触", f"{type(exc).__name__}: {exc}")
            self._put_log(f"娓呯┖鐩爣鏂囦欢澶瑰け璐ワ細{type(exc).__name__}: {exc}")

    def _toggle_secret(self, key: str) -> None:
        entry = self._key_entries.get(key)
        if not entry:
            return
        entry.configure(show="" if entry.cget("show") == "*" else "*")

    def _refresh_key_status(self) -> None:
        for key_name, var in self.key_vars.items():
            label = getattr(self, f"{key_name}_status_label", None)
            if label is not None:
                label.configure(text="set" if var.get().strip() else "not set")

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
            "content_style": "绉戝缁忓吀瑙ｈ",
            "call_mode": "API鑷姩璋冪敤",
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
            self._put_log("Model config and keys saved to merged project copies.")

    def _save_email_config_with_log(self) -> None:
        self._save_email_config(log=True)

    def _save_email_config(self, *, log: bool = False) -> bool:
        try:
            port = int(str(self.smtp_port.get()).strip() or "465")
        except Exception:
            messagebox.showwarning("Invalid port", "SMTP port must be a number.")
            return False
        host = self.smtp_host.get().strip()
        user = self.smtp_user.get().strip()
        sender = self.smtp_sender.get().strip() or user
        password = self.smtp_password.get().strip()
        recipients_raw = self.email_recipient.get().replace("，", ",").replace("；", ",").replace(";", ",")
        recipients = [x.strip() for x in recipients_raw.split(",") if x.strip()]

        research_email = {
            "smtp_host": host,
            "smtp_port": port,
            "smtp_user": user,
            "smtp_password": password,
            "smtp_from": sender,
            "smtp_ssl": bool(self.smtp_ssl.get()),
            "smtp_tls": bool(self.smtp_tls.get()),
            "note": "Saved by Quanlan Assistant. SMTP auth code is only for login; do not share it publicly.",
        }
        _write_json(RESEARCH_ROOT / "quanlan_email_settings.json", research_email)
        if password:
            _write_text(RESEARCH_ROOT / "smtp_password.txt", password)
            _write_text(CULTURE_ROOT / "smtp_password.txt", password)

        run_switch_path = CULTURE_ROOT / "config" / "杩愯寮€鍏?json"
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
            "subject_template": "Assets generated: {part_name}",
        }
        _write_json(run_switch_path, run_switch)

        scheme = _read_json(RESEARCH_ROOT / "quanlan_model_scheme.json")
        scheme["email_after_completion"] = bool(self.email_enabled.get())
        scheme["email_recipient"] = self.email_recipient.get().strip()
        _write_json(RESEARCH_ROOT / "quanlan_model_scheme.json", scheme)
        if log:
            self._put_log("Email config saved to merged project copies.")
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
                self._put_log("SMTP test failed: server, account, or auth code is missing.", task_key=task_key)
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
            self._put_log(f"SMTP test passed in {time.perf_counter() - started:.1f}s.", task_key=task_key)
        except Exception as exc:
            self._put_log(f"SMTP test failed after {time.perf_counter() - started:.1f}s: {type(exc).__name__}: {exc}", task_key=task_key)

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
        self._run_mode("research", args, output_dir=out_dir, task_key="research_digest", task_label="Research digest", env=runtime_env)

    def _build_research_article_list(self) -> None:
        runtime_env = self._runtime_env("research_digest", model_scheme=self._research_model_scheme_snapshot())
        if runtime_env is None:
            return
        out_dir = self._research_continue_base_out_dir()
        if not self.research_article_list.get().strip():
            self.research_article_list.set(str(Path(out_dir) / f"article_list_{datetime.now().strftime('%Y%m%d')}.json"))
        args = ["--daily-build-article-list"]
        self._add_arg(args, "--daily-out-dir", out_dir)
        self._add_arg(args, "--daily-days", self.research_days.get())
        self._add_arg(args, "--daily-max-articles", self.research_max_articles.get())
        self._add_arg(args, "--daily-journals", self.research_journals.get())
        self._add_arg(args, "--daily-article-list", self.research_article_list.get())
        self._run_mode("research", args, output_dir="", refresh_article_list=True, task_key="research_digest", task_label="Research digest", env=runtime_env)

    def _run_research_digest_continue_list(self) -> None:
        article_list = self.research_article_list.get().strip()
        if not article_list:
            messagebox.showwarning("Missing article list", "Select an existing article-list JSON before continuing materials.")
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
        self._run_mode("research", args, output_dir=out_dir, refresh_article_list=True, task_key="research_digest", task_label="Research digest", env=runtime_env)

    def _resume_research_digest_issue(self) -> None:
        out_dir = self.research_resume_dir.get().strip() or self.research_out_dir.get().strip() or self.last_research_output_dir.get().strip()
        if not out_dir:
            messagebox.showwarning(
                "Missing issue folder",
                "Choose a generated research digest issue folder, for example:\n"
                r"D:\Quanlan\ResearchDigest\20260605"
                "\n\nDo not choose the parent research digest directory.",
            )
            return
        target, warning = self._resolve_research_issue_dir(Path(out_dir))
        if warning:
            messagebox.showwarning("Choose issue folder", warning)
            return
        if target is None:
            messagebox.showwarning(
                "Missing issue folder",
                "Choose a generated research digest issue folder, for example:\n"
                r"D:\Quanlan\ResearchDigest\20260605"
                "\n\nDo not choose the parent research digest directory.",
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
        self._run_mode("research", args, output_dir=str(target), task_key="research_digest", task_label="Research digest", env=runtime_env)

    def _resolve_research_issue_dir(self, selected: Path) -> tuple[Path | None, str]:
        target = selected.expanduser()
        if not target.exists():
            return None, f"This path does not exist. Choose an existing generated issue folder:\n\n{target}"
        if not target.is_dir():
            return None, f"This path is not a folder, so it cannot be resumed:\n\n{target}"
        if self._is_research_issue_dir(target):
            return target, ""

        candidates = self._find_research_issue_children(target)
        if len(candidates) == 1:
            resolved = candidates[0]
            self._put_log(f"[Research digest] Auto-selected issue folder from parent: {resolved}", task_key="research_digest")
            return resolved, ""
        if len(candidates) > 1:
            examples = "\n".join(f"- {p.name}" for p in candidates[:8])
            more = "" if len(candidates) <= 8 else f"\n... plus {len(candidates) - 8} more"
            return None, (
                "The selected folder looks like a parent folder, not a specific issue folder.\n\n"
                "Resume needs one generated issue folder, for example:\n"
                r"D:\Quanlan\ResearchDigest\20260605"
                "\n\nMultiple issue folders were found. Choose one:\n"
                f"{examples}{more}"
            )
        return None, (
            "No resumable research digest issue files were found in this folder.\n\n"
            "Choose an issue folder such as 20260605 or 20260605(2).\n"
            "The folder should usually contain files such as article metadata, column assets, and narration text.\n\n"
            f"Current selection: {target}"
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
        return path.with_name(path.stem + "_缁仛杩涘害.json")

    def _resolved_research_article_list_path(self) -> Path | None:
        raw = self.research_article_list.get().strip().strip('"')
        if not raw:
            return None
        path = Path(raw)
        if path.is_dir():
            for name in ("00_鍊欓€夋枃鐚竻鍗?json", "00_鏂囩尞淇℃伅.json", "article_list.json", "articles.json"):
                candidate = path / name
                if candidate.exists():
                    path = candidate
                    break
        return path if path.exists() and path.is_file() else None

    def _reset_research_article_progress(self, *, ask: bool = True) -> bool:
        path = self._resolved_research_article_list_path()
        if path is None:
            messagebox.showinfo("No article list", "Choose an existing article list JSON first.")
            return False
        progress_path = self._article_list_progress_path(path)
        if ask:
            ok = messagebox.askyesno(
                "Reset article progress",
                f"This will clear used-article progress for:\n\n{progress_path}\n\nThe article list itself will not be deleted. Continue?",
            )
            if not ok:
                return False
        try:
            if progress_path.exists():
                progress_path.unlink()
                self._put_log(f"Article progress reset: {progress_path}")
            else:
                self._put_log(f"Article list had no progress to reset: {progress_path}")
            self._refresh_article_list_preview()
            return True
        except Exception as exc:
            messagebox.showerror("Reset failed", f"{type(exc).__name__}: {exc}")
            self._put_log(f"Article progress reset failed: {type(exc).__name__}: {exc}")
            return False

    def _load_article_list_for_preview(self) -> tuple[list[dict], set[str], str]:
        raw = self.research_article_list.get().strip().strip('"')
        if not raw:
            return [], set(), "No article list selected."
        path = Path(raw)
        if path.is_dir():
            for name in ("00_鍊欓€夋枃鐚竻鍗?json", "00_鏂囩尞淇℃伅.json", "article_list.json", "articles.json"):
                candidate = path / name
                if candidate.exists():
                    path = candidate
                    break
        if not path.exists():
            return [], set(), f"Article list does not exist: {path}"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return [], set(), f"Failed to read article list: {type(exc).__name__}: {exc}"
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
            lines.append(f"Article list: {len(articles)} total; {len(used_pmids)} used; {pending} pending.")
            lines.append("")
            preview_articles = articles[:ARTICLE_PREVIEW_LIMIT]
            for idx, item in enumerate(preview_articles, start=1):
                pmid = str(item.get("pmid", "")).strip()
                status = "used" if pmid in used_pmids else "pending"
                journal = str(item.get("journal", "") or "Unknown").strip()
                title = re.sub(r"\s+", " ", str(item.get("title", "")).strip())
                lines.append(f"{idx:02d}. [{status}] {journal} | PMID {pmid or '-'}")
                lines.append(f"    {title[:180]}")
            if len(articles) > ARTICLE_PREVIEW_LIMIT:
                lines.append("")
                lines.append(f"Previewing first {ARTICLE_PREVIEW_LIMIT} articles; full list remains in the JSON file.")
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines).strip() + "\n")
        widget.configure(state="disabled")

    def _research_daily_out_dir(self) -> str:
        explicit = self.research_out_dir.get().strip()
        issue_count = self._bounded_int(self.research_issue_count.get(), 1, 3, 1)
        issue_no = self._bounded_int(self.research_issue_no.get(), 1, issue_count, 1)
        date_name = datetime.now().strftime("%Y%m%d")
        folder_name = date_name if issue_count <= 1 else f"{date_name}({issue_no})"
        if explicit:
            path = Path(explicit)
            if path.name == folder_name:
                return str(path)
            return str(path / folder_name)
        return str(RESEARCH_ROOT / "chapter_pdf_direct_output" / "daily_research_digest" / folder_name)

    def _research_continue_base_out_dir(self) -> str:
        explicit = self.research_out_dir.get().strip()
        if explicit:
            path = Path(explicit)
            if re.fullmatch(r"\d{8}(?:\(\d+\))?", path.name):
                return str(path.parent)
            return str(path)
        return str(RESEARCH_ROOT / "chapter_pdf_direct_output" / "daily_research_digest")

    def _bounded_int(self, value: str, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(str(value or "").strip())
        except Exception:
            number = default
        return max(minimum, min(maximum, number))

    def _normalize_journals_with_gpt(self) -> None:
        if self._is_task_running("research_digest"):
            messagebox.showinfo("Task running", "Wait for the current task to finish before normalizing journals.")
            return
        request = self.research_journal_fuzzy.get().strip()
        if not request:
            messagebox.showwarning("Missing request", "Describe the journal topic or journal names first.")
            return
        threading.Thread(target=self._journal_gpt_worker, args=(request,), daemon=True).start()

    def _journal_gpt_worker(self, request: str) -> None:
        started = time.perf_counter()
        try:
            from openai import OpenAI

            key = self.key_vars["openai"].get().strip()
            if not key:
                self._put_log("Journal normalization failed: OpenAI/FHL key is not set.", task_key="research_digest")
                return
            model = self.text_engine.get().strip() or "GPT-5.5"
            base_url = self._normalized_foreign_base_url()
            client = OpenAI(api_key=key, base_url=base_url, timeout=90, max_retries=0)
            prompt = (
                "You are editing a neuroscience research digest. Convert the user's fuzzy request "
                "into a comma-separated list of English academic journal names suitable for PubMed "
                "or journal filtering. Output journal names only, no numbering or explanations. "
                "Prefer real full journal names, maximum 20 items.\n\n"
                f"User request: {request}"
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
                    self._put_log("Journal normalization fell back to the user request text.", task_key="research_digest")
                else:
                    self._put_log(f"Journal normalization produced no valid result: provider=openai, model={model}, base={base_url}, key={_key_hint(key)}.", task_key="research_digest")
                    return
            self.research_journals.set(journals)
            self._put_log(f"Journal normalization completed in {time.perf_counter() - started:.1f}s; filled {len([x for x in journals.split(',') if x.strip()])} journals.", task_key="research_digest")
        except Exception as exc:
            self._put_log(f"Journal normalization failed after {time.perf_counter() - started:.1f}s: provider=openai, model={locals().get('model', '')}, base={locals().get('base_url', '')}, key={_key_hint(locals().get('key', ''))}, {type(exc).__name__}: {exc}", task_key="research_digest")

    def _clean_journal_list(self, text: str) -> str:
        raw = str(text or "").replace("\n", ",").replace("，", ",").replace("；", ",").replace(";", ",")
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
            item = re.sub(r"^[\s\-\d\.\)\(]+", "", part).strip().strip("\"'` ")
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
        if not items and str(text or "").strip() and "绁炵粡绉戝" in str(text):
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
            "content_style": "绉戝缁忓吀瑙ｈ",
            "text_engine": self.text_engine.get(),
            "review_engine": self.polish_engine.get(),
            "image_engine": _normalize_research_image_choice(self.image_engine.get()),
            "call_mode": "API鑷姩璋冪敤",
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
        args = ["--content-style", "science_classic"]
        label = "Science classic test" if test_b_image_limit else "Science classic"
        self._run_mode("research", args, gui=True, output_dir=out_dir, task_key="science_classic", task_label=label, env=runtime_env)

    def _test_science_classic_b_image(self) -> None:
        self._put_log("Science classic test: generate/process only the first B image for a quick pipeline check.", task_key="science_classic")
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
            messagebox.showwarning("Missing input", "Choose a book PDF or a continue-from folder.")
            return
        runtime_env = self._runtime_env("culture")
        if runtime_env is None:
            return
        label = "Culture test" if effective_test_limit else "Culture"
        self._run_mode("culture", args, output_dir=out_dir, task_key="culture", task_label=label, env=runtime_env)

    def _test_culture_b_image(self) -> None:
        self._put_log("Culture test: generate/process only the first B image for a quick pipeline check.", task_key="culture")
        self._run_culture(test_b_image_limit=1)

    def _run_auto_clip(self) -> None:
        image_dir = self.auto_clip_image_dir.get().strip()
        lrc_dir = self.auto_clip_lrc_dir.get().strip()
        output_dir = self.auto_clip_output_dir.get().strip()
        if not image_dir or not Path(image_dir).is_dir():
            messagebox.showwarning("Choose image folder", "Choose a valid image asset folder first.")
            return
        if not lrc_dir or not Path(lrc_dir).is_dir():
            messagebox.showwarning("Choose LRC folder", "Choose a valid LRC asset folder first.")
            return
        if not output_dir:
            output_dir = str(Path(lrc_dir) / "auto_clip_output")
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
            "Auto clip",
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
                    model = self.culture_polish_model.get().strip() or "deepseek-chat"
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
                self._put_log(f"Text model test failed: provider={provider}, model={model}, key={KEY_LABELS.get(key_name, key_name)} is not set.", task_key=task_key)
                return
            self._put_log(f"Text model test starting: provider={provider}, model={model}, base={base_url}, key={KEY_LABELS.get(key_name, key_name)} {_key_hint(key)}.", task_key=task_key)
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
                raise RuntimeError(f"Model returned empty or unrecognized response: {type(response).__name__}")
            self._put_log(f"Text model test passed: provider={provider}, model={model}, elapsed={time.perf_counter() - started:.1f}s, reply={content[:20] or 'empty'}", task_key=task_key)
        except Exception as exc:
            self._put_log(f"Text model test failed after {time.perf_counter() - started:.1f}s: provider={locals().get('provider', '')}, model={locals().get('model', '')}, base={locals().get('base_url', '')}, key={KEY_LABELS.get(locals().get('key_name', ''), locals().get('key_name', ''))} {_key_hint(locals().get('key', ''))}, {type(exc).__name__}: {exc}", task_key=task_key)

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
            "culture_text": (self.culture_text_provider.get(), self.culture_text_model.get(), "Culture text"),
            "culture_polish": (self.culture_polish_provider.get(), self.culture_polish_model.get(), "Culture polish"),
            "research_text": (_provider_for_engine(self.text_engine.get()), _research_text_model_id(self.text_engine.get()), "Research text"),
            "research_polish": (_provider_for_engine(self.polish_engine.get() if self.polish_engine.get() != "Follow script model" else self.text_engine.get()), _research_text_model_id(self.polish_engine.get() if self.polish_engine.get() != "Follow script model" else self.text_engine.get()), "Research polish"),
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
                model = model.strip() or "deepseek-chat"
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
                self._put_log(f"{label} test failed: provider={provider}, model={model}, key={KEY_LABELS.get(key_name, key_name)} is not set.", task_key=task_key)
                return
            self._put_log(f"{label} test starting: provider={provider}, model={model}, base={base_url}, key={KEY_LABELS.get(key_name, key_name)} {_key_hint(key)}.", task_key=task_key)
            client = OpenAI(api_key=key, base_url=base_url, timeout=60, max_retries=0)
            if provider == "openai":
                response = client.responses.create(model=model, input="Connection test. Reply exactly: OK", max_output_tokens=32)
                content = _extract_response_content(response)
            else:
                response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Connection test. Reply exactly: OK"}], max_tokens=8, temperature=0)
                content = _extract_chat_content(response)
            if not content:
                raise RuntimeError(f"Model returned empty or unrecognized response: {type(response).__name__}")
            self._put_log(f"{label} test passed: provider={provider}, model={model}, elapsed={time.perf_counter() - started:.1f}s, reply={content[:40]}", task_key=task_key)
        except Exception as exc:
            self._put_log(f"{label} test failed after {time.perf_counter() - started:.1f}s: provider={provider}, model={model}, base={locals().get('base_url', '')}, key={KEY_LABELS.get(locals().get('key_name', ''), locals().get('key_name', ''))} {_key_hint(locals().get('key', ''))}, {type(exc).__name__}: {exc}", task_key=task_key)

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
                self._put_log(f"Image model test failed: key={KEY_LABELS.get(key_name, key_name)} is not set.", task_key=task_key)
                return
            base_url = self._normalized_foreign_base_url()
            self._put_log(f"Image model test starting: provider=image, model={model}, base={base_url}, key={KEY_LABELS.get(key_name, key_name)} {_key_hint(key)}, timeout=240s.", task_key=task_key)
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
                self._put_log(f"Image model test passed: provider=gemini, model={model}, elapsed={time.perf_counter() - started:.1f}s, endpoint=generateContent.", task_key=task_key)
            else:
                client = OpenAI(api_key=key, base_url=base_url, timeout=240, max_retries=0)
                client.images.generate(
                    model=model,
                    prompt="A clean visual test card with simple geometric shapes, no text.",
                    size="720x1280",
                )
                self._put_log(f"Image model test passed: provider=image, model={model}, elapsed={time.perf_counter() - started:.1f}s, endpoint=images.generate, size=720x1280.", task_key=task_key)
        except Exception as exc:
            self._put_log(f"Image model test failed after {time.perf_counter() - started:.1f}s: provider=image, model={locals().get('model', '')}, base={locals().get('base_url', '')}, key={KEY_LABELS.get(locals().get('key_name', ''), locals().get('key_name', ''))} {_key_hint(locals().get('key', ''))}, {type(exc).__name__}: {exc}", task_key=task_key)

    def _normalized_foreign_base_url(self) -> str:
        base_url = (self.foreign_base_url.get().strip() or "https://www.fhl.mom/v1").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        return base_url

    def _normalized_model_base_url(self, var: tk.StringVar) -> str:
        base_url = (var.get().strip() or self._normalized_foreign_base_url()).rstrip("/")
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
            messagebox.showinfo("浠诲姟杩愯涓?, "杩欎釜浠诲姟宸茬粡鍦ㄨ繍琛屼腑銆?)
            return
        mode = get_mode(mode_key)
        cmd = _python_command(mode, gui=gui, extra_args=args)
        self._put_log("", task_key=task_key)
        if "--daily-build-article-list" in args:
            task_name = "Build article list"
        elif "--daily-resume-existing" in args:
            task_name = "Resume issue"
        elif "--daily-research-digest" in args:
            task_name = "Research digest"
        else:
            task_name = task_label or mode.title
        task_label = task_label or task_name
        self.running_processes[task_key] = None
        self.running_labels[task_key] = task_label
        self._write_release_state()
        self._put_log(f"[{task_label}] Starting task.", task_key=task_key)
        if output_dir:
            self._put_log(f"[{task_label}] Output directory: {output_dir}", task_key=task_key)
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
            messagebox.showinfo("浠诲姟杩愯涓?, "杩欎釜浠诲姟宸茬粡鍦ㄨ繍琛屼腑銆?)
            return
        self.running_processes[task_key] = None
        self.running_labels[task_key] = task_label
        self._put_log("", task_key=task_key)
        self._put_log(f"[{task_label}] 鍚姩浠诲姟銆?, task_key=task_key)
        if output_dir:
            self._put_log(f"[{task_label}] 杈撳嚭鐩綍锛歿output_dir}", task_key=task_key)
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
            self._put_log(f"[{task_label}] 宸茬粨鏉燂紝閫€鍑虹爜 {code}", task_key=task_key)
            if code == 0 and output_dir:
                self._set_last_output_for_task(task_key, output_dir)
                self._put_log(f"[{task_label}] 姝ｅ湪鎵撳紑杈撳嚭鐩綍锛歿output_dir}", task_key=task_key)
                self.after(0, lambda p=output_dir: self._open_path(p))
        except Exception as exc:
            self._put_log(f"[{task_label}] 鍚姩澶辫触锛歿type(exc).__name__}: {exc}", task_key=task_key)
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
            self._put_log(f"[{task_label}] 宸茬粨鏉燂紝閫€鍑虹爜 {code}", task_key=task_key)
            if code == 0 and output_dir:
                self._set_last_output_for_task(task_key, output_dir)
                self._put_log(f"[{task_label}] 姝ｅ湪鎵撳紑绱犳潗杈撳嚭鐩綍锛歿output_dir}", task_key=task_key)
                self.after(0, lambda p=output_dir: self._open_path(p))
            if code == 0 and refresh_article_list:
                self.after(0, self._refresh_article_list_preview)
        except Exception as exc:
            self._put_log(f"[{task_label}] 鍚姩澶辫触锛歿type(exc).__name__}: {exc}", task_key=task_key)
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
            self._put_log(f"[{task_label}] 褰撳墠娌℃湁杩愯涓殑浠诲姟銆?, task_key=task_key)
            return
        try:
            proc.terminate()
            self._put_log(f"[{task_label}] 宸茶姹傚仠姝㈠綋鍓嶄换鍔°€?, task_key=task_key)
        except Exception as exc:
            self._put_log(f"[{task_label}] 鍋滄澶辫触锛歿exc}", task_key=task_key)

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
            return "绌洪棽"
        return "杩愯涓細" + "銆?.join(labels)

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
                self._put_log("[绯荤粺] 绐楀彛宸查殣钘忓埌鍙充笅瑙掓墭鐩橈紱姝ｅ湪杩愯鐨勪换鍔′細缁х画鎵ц銆?, task_key=self.active_task.get())
                return
            detail = self._tray_icon.last_error if self._tray_icon else "鎵樼洏缁勪欢鏈垱寤?
            if messagebox.askyesno("閫€鍑虹▼搴?, f"鎵樼洏鍥炬爣涓嶅彲鐢細{detail}銆俓n鏄惁鐩存帴閫€鍑虹▼搴忥紵"):
                self._final_exit()
            return
        self.withdraw()
        self._put_log("[绯荤粺] 绐楀彛宸查殣钘忓埌鍙充笅瑙掓墭鐩橈紱姝ｅ湪杩愯鐨勪换鍔′細缁х画鎵ц銆?, task_key=self.active_task.get())

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
                ok = messagebox.askyesno("閫€鍑虹▼搴?, "褰撳墠浠嶆湁浠诲姟鍦ㄨ繍琛屻€傜‘瀹氳閫€鍑哄苟鍋滄杩欎簺浠诲姟鍚楋紵", parent=self)
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


