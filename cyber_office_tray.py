from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import win32api
import win32con
import win32event
import win32gui
import winerror
from PIL import Image, ImageDraw, ImageFont


APP_NAME = "郤冠楠的赛博办公室"
PORT = 8765
ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / ".workbench_runtime"
ICON_PATH = RUNTIME_DIR / "cyber_office.ico"
LOG_PATH = RUNTIME_DIR / "cyber_office_tray.log"
URL = f"http://127.0.0.1:{PORT}/"
WM_TASKBAR = win32gui.RegisterWindowMessage("TaskbarCreated")
WM_TRAY = win32con.WM_USER + 8765
MUTEX_NAME = "Local\\XGN_Cyber_Office_Tray_8765"

ID_OPEN = 1001
ID_RESTART = 1002
ID_STOP = 1003
ID_EXIT = 1004
TIMER_ID = 8765
CHECK_INTERVAL_SECONDS = 15


class TrayApp:
    def __init__(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self.hinst = win32api.GetModuleHandle(None)
        self.hwnd = 0
        self.notify_id = None
        self.service: subprocess.Popen | None = None
        self.running = True
        self.auto_start = True
        self.icon = self._load_icon()

    def run(self) -> None:
        self._create_window()
        self._add_icon()
        self.ensure_service(open_browser=False)
        threading.Thread(target=self._keepalive_loop, daemon=True).start()
        win32gui.PumpMessages()

    def _create_window(self) -> None:
        message_map = {
            WM_TASKBAR: self._on_taskbar_created,
            WM_TRAY: self._on_tray,
            win32con.WM_COMMAND: self._on_command,
            win32con.WM_DESTROY: self._on_destroy,
        }
        wndclass = win32gui.WNDCLASS()
        wndclass.hInstance = self.hinst
        wndclass.lpszClassName = "XGNCyberOfficeTrayWindow"
        wndclass.lpfnWndProc = message_map
        try:
            win32gui.RegisterClass(wndclass)
        except win32gui.error:
            pass
        self.hwnd = win32gui.CreateWindow(
            wndclass.lpszClassName,
            APP_NAME,
            0,
            0,
            0,
            win32con.CW_USEDEFAULT,
            win32con.CW_USEDEFAULT,
            0,
            0,
            self.hinst,
            None,
        )

    def _load_icon(self) -> int:
        self._ensure_icon_file()
        return win32gui.LoadImage(
            self.hinst,
            str(ICON_PATH),
            win32con.IMAGE_ICON,
            0,
            0,
            win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
        )

    def _ensure_icon_file(self) -> None:
        if ICON_PATH.exists():
            return
        img = Image.new("RGBA", (256, 256), (15, 118, 110, 255))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((20, 20, 236, 236), radius=48, fill=(16, 32, 51, 255))
        draw.rounded_rectangle((42, 48, 214, 190), radius=28, fill=(20, 184, 166, 255))
        draw.rectangle((74, 190, 182, 212), fill=(245, 158, 11, 255))
        font = self._font(96)
        draw.text((128, 113), "郤", anchor="mm", fill=(255, 255, 255, 255), font=font)
        img.save(ICON_PATH, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    def _font(self, size: int) -> ImageFont.ImageFont:
        candidates = [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "simhei.ttf",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "simsun.ttc",
        ]
        for path in candidates:
            if path.exists():
                return ImageFont.truetype(str(path), size)
        return ImageFont.load_default()

    def _add_icon(self) -> None:
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        self.notify_id = (self.hwnd, 0, flags, WM_TRAY, self.icon, APP_NAME)
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.notify_id)

    def _modify_tip(self, tip: str) -> None:
        if not self.notify_id:
            return
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, (self.hwnd, 0, flags, WM_TRAY, self.icon, tip[:120]))

    def _on_taskbar_created(self, hwnd, msg, wparam, lparam):
        self._add_icon()
        return True

    def _on_tray(self, hwnd, msg, wparam, lparam):
        if lparam == win32con.WM_LBUTTONDBLCLK:
            self.open_office()
        elif lparam in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
            self._show_menu()
        return True

    def _show_menu(self) -> None:
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_OPEN, "打开赛博办公室")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_RESTART, "重启后台服务")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_STOP, "关闭后台服务")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_EXIT, "退出托盘")
        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        command_id = win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY,
            pos[0],
            pos[1],
            0,
            self.hwnd,
            None,
        )
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        if command_id:
            self._handle_command(command_id)

    def _on_command(self, hwnd, msg, wparam, lparam):
        self._handle_command(win32api.LOWORD(wparam))
        return True

    def _handle_command(self, command_id: int) -> None:
        if command_id == ID_OPEN:
            self.open_office()
        elif command_id == ID_RESTART:
            self.restart_service()
        elif command_id == ID_STOP:
            self.stop_service()
        elif command_id == ID_EXIT:
            win32gui.DestroyWindow(self.hwnd)

    def _keepalive_loop(self) -> None:
        while self.running:
            time.sleep(CHECK_INTERVAL_SECONDS)
            if self.auto_start:
                self.ensure_service(open_browser=False)

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        self.running = False
        if self.notify_id:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, self.notify_id)
        win32gui.PostQuitMessage(0)
        return True

    def open_office(self) -> None:
        self.auto_start = True
        self.ensure_service(open_browser=False)
        webbrowser.open(URL)

    def restart_service(self) -> None:
        self.stop_service()
        time.sleep(0.8)
        self.auto_start = True
        self.ensure_service(open_browser=False, force=True)

    def stop_service(self) -> None:
        self.auto_start = False
        for pid in self._service_pids():
            if pid != os.getpid():
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        if self.service and self.service.poll() is None:
            self.service.terminate()
        self.service = None
        self._modify_tip(f"{APP_NAME} - 服务已关闭")

    def ensure_service(self, *, open_browser: bool, force: bool = False) -> None:
        if not force and self._http_ok():
            self._modify_tip(f"{APP_NAME} - 已在线")
            return
        self._start_service()
        if open_browser:
            webbrowser.open(URL)

    def _start_service(self) -> None:
        if self.service and self.service.poll() is None:
            return
        exe = self._service_python()
        cmd = [exe, "-X", "utf8", "-m", "quanlan_dual_assistant.web_app", str(PORT)]
        log = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        self.service = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
        self._modify_tip(f"{APP_NAME} - 正在启动")

    def _service_python(self) -> str:
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            python_exe = exe.with_name("python.exe")
            if python_exe.exists():
                return str(python_exe)
        return str(exe)

    def _http_ok(self) -> bool:
        try:
            with urllib.request.urlopen(URL, timeout=1.5) as resp:
                return 200 <= int(resp.status) < 500
        except Exception:
            return self._port_open()

    def _port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return True
        except OSError:
            return False

    def _service_pids(self) -> list[int]:
        command = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match 'quanlan_dual_assistant.web_app' -and $_.CommandLine -match '8765' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        pids = []
        for line in completed.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids


def _single_instance_guard():
    handle = win32event.CreateMutex(None, False, MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        webbrowser.open(URL)
        raise SystemExit(0)
    return handle


def main() -> None:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("XGN.CyberOffice.Tray")
    guard = _single_instance_guard()
    try:
        TrayApp().run()
    finally:
        win32api.CloseHandle(guard)


if __name__ == "__main__":
    main()
