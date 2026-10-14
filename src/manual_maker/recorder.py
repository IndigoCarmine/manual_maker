"""操作を記録してスクリーンショットを撮る。

- クリック（押下時）に自動撮影
- Ctrl+Shift+S: 手動撮影 / Ctrl+Shift+P: 一時停止・再開 / Ctrl+Shift+Q: 終了
"""

from __future__ import annotations

import queue
import threading
import time
import winsound
from dataclasses import dataclass
from datetime import datetime

import mss
import mss.tools
from pynput import keyboard, mouse

from . import model, winutil
from .model import Click, Element, Manual, Step
from .winutil import Rect

DOUBLE_CLICK_SEC = 0.3
DOUBLE_CLICK_PX = 6
VK_S, VK_P, VK_Q = 0x53, 0x50, 0x51
IGNORED_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
DESKTOP_CLASSES = {"Progman", "WorkerW"}
MENU_CLASS = "#32768"
TERMINAL_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow"}


@dataclass
class Capture:
    trigger: str
    rect: Rect
    raw: object  # mss ScreenShot
    hwnd: int | None
    point: tuple[int, int] | None
    button: str
    time: datetime
    typed_before: str = ""  # 前のステップ以降に入力された文字（前のステップに付与）


class Recorder:
    def __init__(self, name: str, fullscreen: bool = False, record_keys: bool = True):
        self.name = name
        self.fullscreen = fullscreen
        self.record_keys = record_keys
        self.paused = False
        self.stopped = threading.Event()
        self.queue: queue.Queue[Capture | None] = queue.Queue()
        self._local = threading.local()
        self._last_click: tuple[float, int, int] | None = None
        self._mods: set[str] = set()
        self._typed: list[str] = []
        self._typed_lock = threading.Lock()
        self._ignored_hwnds: set[int] = set()

        try:
            self.manual = model.load(name)
        except FileNotFoundError:
            self.manual = Manual(title=name)
            model.project_dir(name).joinpath("images").mkdir(parents=True, exist_ok=True)
            model.save(name, self.manual)

    # ---------- 撮影 ----------
    def _sct(self) -> mss.base.MSSBase:
        if not hasattr(self._local, "sct"):
            self._local.sct = mss.mss()
        return self._local.sct

    def _capture_rect(self, x: int, y: int) -> tuple[Rect, int | None] | None:
        """クリック位置から撮影範囲を決める。None なら撮影しない。"""
        if self.fullscreen:
            return winutil.monitor_rect_at(x, y), winutil.window_from_point(x, y)

        clicked = winutil.window_from_point(x, y)
        if not clicked:
            return None
        owner = winutil.root_owner(clicked)
        if clicked in self._ignored_hwnds or owner in self._ignored_hwnds:
            return None
        cls = winutil.window_class(clicked)
        if cls in IGNORED_CLASSES:
            return None
        if cls in DESKTOP_CLASSES:
            return winutil.monitor_rect_at(x, y), clicked

        rect = winutil.window_rect(owner)
        if clicked != owner:
            rect = rect.union(winutil.window_rect(clicked))
        if cls == MENU_CLASS:
            # 所有者を持たないポップアップメニューは前面ウィンドウと合成する
            fg = winutil.foreground_window()
            if fg and fg != clicked:
                rect = rect.union(winutil.window_rect(fg))
        rect = rect.intersect(winutil.virtual_screen())
        if rect.width <= 0 or rect.height <= 0:
            return None
        return rect, owner

    @staticmethod
    def _is_background(hwnd: int) -> bool:
        if winutil.window_class(hwnd) == MENU_CLASS:
            return False
        fg = winutil.foreground_window()
        return not fg or winutil.root_owner(fg) != winutil.root_owner(hwnd)

    def _grab(self, rect: Rect):
        return self._sct().grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not pressed or self.paused or self.stopped.is_set():
            return
        if button not in (mouse.Button.left, mouse.Button.right):
            return
        now = time.monotonic()
        if self._last_click:
            t, lx, ly = self._last_click
            if now - t < DOUBLE_CLICK_SEC and abs(x - lx) <= DOUBLE_CLICK_PX and abs(y - ly) <= DOUBLE_CLICK_PX:
                self._last_click = (now, x, y)
                return
        self._last_click = (now, x, y)
        try:
            target = self._capture_rect(x, y)
            if target is None:
                return
            rect, hwnd = target
            raw = None
            if not self.fullscreen and hwnd and self._is_background(hwnd):
                # 背面ウィンドウをクリックした（前面化する）場合、画面には他のウィンドウが
                # 重なっているので、ウィンドウ自体の描画内容を取得する
                raw = winutil.print_window(hwnd)
                if raw is not None:
                    rect = winutil.window_rect(hwnd)
            if raw is None:
                raw = self._grab(rect)
        except Exception as e:  # フック内で例外を出すとリスナーが止まる
            print(f"  [!] 撮影失敗: {e}")
            return
        self.queue.put(
            Capture("click", rect, raw, hwnd, (x, y), button.name, datetime.now(), self._flush_typed())
        )

    def _manual_capture(self) -> None:
        try:
            hwnd = winutil.foreground_window()
            if self.fullscreen or not hwnd:
                pos = mouse.Controller().position
                rect, hwnd = winutil.monitor_rect_at(*map(int, pos)), hwnd
            else:
                rect = winutil.window_rect(hwnd).intersect(winutil.virtual_screen())
            raw = self._grab(rect)
        except Exception as e:
            print(f"  [!] 撮影失敗: {e}")
            return
        self.queue.put(Capture("hotkey", rect, raw, hwnd, None, "", datetime.now(), self._flush_typed()))
        winsound.MessageBeep(winsound.MB_OK)

    # ---------- キーボード ----------
    @staticmethod
    def _mod_name(key) -> str | None:
        k = keyboard.Key
        if key in (k.ctrl, k.ctrl_l, k.ctrl_r):
            return "Ctrl"
        if key in (k.shift, k.shift_l, k.shift_r):
            return "Shift"
        if key in (k.alt, k.alt_l, k.alt_r, k.alt_gr):
            return "Alt"
        if key in (k.cmd, k.cmd_l, k.cmd_r):
            return "Win"
        return None

    def _on_press(self, key) -> None:
        mod = self._mod_name(key)
        if mod:
            self._mods.add(mod)
            return
        vk = getattr(key, "vk", None)
        if {"Ctrl", "Shift"} <= self._mods and vk in (VK_S, VK_P, VK_Q):
            if vk == VK_S:
                if not self.paused:
                    print("  [S] 手動撮影")
                    self._manual_capture()
            elif vk == VK_P:
                self.paused = not self.paused
                print("  [P] 一時停止中..." if self.paused else "  [P] 再開")
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                print("  [Q] 記録を終了します")
                self.stopped.set()
            return
        if self.paused or not self.record_keys:
            return
        self._record_key(key)

    def _on_release(self, key) -> None:
        mod = self._mod_name(key)
        if mod:
            self._mods.discard(mod)

    def _record_key(self, key) -> None:
        k = keyboard.Key
        combo = self._mods - {"Shift"}
        with self._typed_lock:
            if combo:
                label = getattr(key, "char", None)
                vk = getattr(key, "vk", None)
                if vk and 0x41 <= vk <= 0x5A:
                    label = chr(vk)
                elif isinstance(key, k):
                    label = key.name.capitalize()
                if label and label.isprintable():
                    self._typed.append(f"[{'+'.join(sorted(combo))}+{label}]")
                return
            if key == k.space:
                self._typed.append(" ")
            elif key == k.enter:
                self._typed.append("[Enter]")
            elif key == k.tab:
                self._typed.append("[Tab]")
            elif key == k.backspace:
                if self._typed and len(self._typed[-1]) == 1:
                    self._typed.pop()
            elif key == k.esc:
                self._typed.append("[Esc]")
            else:
                ch = getattr(key, "char", None)
                if ch and ch.isprintable():
                    self._typed.append(ch)

    def _flush_typed(self) -> str:
        with self._typed_lock:
            text = "".join(self._typed)
            self._typed.clear()
        return text

    # ---------- 保存（ワーカー） ----------
    def _worker(self) -> None:
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            while True:
                cap = self.queue.get()
                if cap is None:
                    break
                try:
                    self._save_capture(cap, auto)
                except Exception as e:
                    print(f"  [!] 保存失敗: {e}")

    def _element_at(self, auto, x: int, y: int) -> Element | None:
        try:
            ctrl = auto.ControlFromPoint(x, y)
            for _ in range(3):  # 名前が空なら親をたどる
                if ctrl is None:
                    return None
                if ctrl.Name:
                    return Element(ctrl.Name[:100], ctrl.ControlTypeName)
                ctrl = ctrl.GetParentControl()
        except Exception:
            pass
        return None

    def _save_capture(self, cap: Capture, auto) -> None:
        m = self.manual
        if m.steps and cap.typed_before:
            m.steps[-1].typed_text += cap.typed_before

        step_id = m.next_id()
        rel = f"images/{step_id}.png"
        out = model.project_dir(self.name) / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(cap.raw, "save"):  # PIL Image（PrintWindow）
            cap.raw.save(out)
        else:  # mss ScreenShot
            mss.tools.to_png(cap.raw.rgb, cap.raw.size, output=str(out))

        click = element = None
        if cap.point:
            px, py = cap.point
            click = Click(
                round((px - cap.rect.left) / cap.rect.width, 4),
                round((py - cap.rect.top) / cap.rect.height, 4),
                cap.button,
            )
            element = self._element_at(auto, px, py)

        title = proc = ""
        if cap.hwnd:
            title = winutil.window_title(cap.hwnd)
            proc = winutil.app_process_name(cap.hwnd)
        if not m.app_name and proc:
            m.app_name = proc.removesuffix(".exe")

        m.steps.append(
            Step(
                id=step_id,
                image=rel,
                trigger=cap.trigger,
                time=cap.time.isoformat(timespec="seconds"),
                window_title=title,
                process=proc,
                click=click,
                element=element,
                highlight=click is not None,
            )
        )
        model.save(self.name, m)
        el = f" 「{element.name}」({element.control_type})" if element else ""
        print(f"  #{step_id} {cap.trigger:6s} {proc} {title[:40]}{el}")

    # ---------- 実行 ----------
    def run(self) -> None:
        # 起動したコンソール（ターミナル）上のクリックは無視する
        candidates = [winutil.console_window()]
        fg = winutil.foreground_window()
        if fg and winutil.window_class(fg) in TERMINAL_CLASSES:
            candidates.append(fg)
        for h in candidates:
            if h:
                self._ignored_hwnds.add(h)
                self._ignored_hwnds.add(winutil.root_owner(h))

        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        mouse_listener = mouse.Listener(on_click=self._on_click)
        key_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        mouse_listener.start()
        key_listener.start()

        print(f"記録開始: projects/{self.name}  （既存 {len(self.manual.steps)} ステップ）")
        print("  クリック     : 自動撮影")
        print("  Ctrl+Shift+S : 手動撮影")
        print("  Ctrl+Shift+P : 一時停止 / 再開")
        print("  Ctrl+Shift+Q : 終了")
        try:
            while not self.stopped.wait(0.2):
                pass
        except KeyboardInterrupt:
            print("  中断されました")
        finally:
            mouse_listener.stop()
            key_listener.stop()
            self.queue.put(None)
            worker.join(timeout=30)
            typed = self._flush_typed()
            if typed and self.manual.steps:
                self.manual.steps[-1].typed_text += typed
            model.save(self.name, self.manual)
        print(f"記録終了: {len(self.manual.steps)} ステップ -> {model.manual_path(self.name)}")


def record(name: str, fullscreen: bool = False, record_keys: bool = True) -> None:
    winutil.set_dpi_aware()
    Recorder(name, fullscreen=fullscreen, record_keys=record_keys).run()
