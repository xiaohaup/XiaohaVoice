"""Windows OS adapters. Instantiation is restricted to Windows; imports are inert."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path
import os, threading
from .core import Gesture, Shortcut, MODIFIER_KEYS


@dataclass(frozen=True)
class Target:
    window: int
    focus: int
    pid: int
    revision: int
    application: str = ''


class Windows:
    def __init__(self):
        if os.name != 'nt': raise RuntimeError('此组件仅在Windows运行')
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.shell = C.WinDLL('shell32', use_last_error=True)
        U, K = self.user, self.kernel
        U.GetForegroundWindow.restype = W.HWND
        U.GetClipboardOwner.restype = W.HWND
        U.GetWindowThreadProcessId.argtypes = [W.HWND,C.POINTER(W.DWORD)]; U.GetWindowThreadProcessId.restype = W.DWORD
        U.GetGUIThreadInfo.argtypes = [W.DWORD,C.c_void_p]; U.GetGUIThreadInfo.restype = W.BOOL
        U.IsWindow.argtypes = [W.HWND]; U.IsWindow.restype = W.BOOL
        U.GetAsyncKeyState.argtypes = [C.c_int]; U.GetAsyncKeyState.restype = C.c_short
        U.OpenClipboard.argtypes = [W.HWND]; U.OpenClipboard.restype = W.BOOL
        U.GetClipboardData.argtypes = [W.UINT]; U.GetClipboardData.restype = W.HANDLE
        U.SetClipboardData.argtypes = [W.UINT,W.HANDLE]; U.SetClipboardData.restype = W.HANDLE
        U.GetClipboardSequenceNumber.restype = W.DWORD
        U.EnumClipboardFormats.argtypes = [W.UINT]; U.EnumClipboardFormats.restype = W.UINT
        U.CloseClipboard.restype = W.BOOL; U.EmptyClipboard.restype = W.BOOL
        K.GlobalAlloc.argtypes = [W.UINT,C.c_size_t]; K.GlobalAlloc.restype = W.HGLOBAL
        K.GlobalSize.argtypes = [W.HGLOBAL]; K.GlobalSize.restype = C.c_size_t
        K.GlobalLock.argtypes = [W.HGLOBAL]; K.GlobalLock.restype = C.c_void_p
        K.GlobalUnlock.argtypes = [W.HGLOBAL]; K.GlobalFree.argtypes = [W.HGLOBAL]
        K.GlobalFree.restype = W.HGLOBAL
        K.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD]; K.OpenProcess.restype = W.HANDLE
        K.CloseHandle.argtypes = [W.HANDLE]
        K.QueryFullProcessImageNameW.argtypes = [W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
        self.revision = 0

    def capture(self, include_application=True):
        class GUI(C.Structure):
            _fields_ = [('cbSize',W.DWORD),('flags',W.DWORD),('active',W.HWND),('focus',W.HWND),
                        ('capture',W.HWND),('menu',W.HWND),('move',W.HWND),('caret',W.HWND),('rect',W.RECT)]
        revision = self.revision
        hwnd = self.user.GetForegroundWindow(); pid = W.DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd,C.byref(pid))
        if not hwnd or not pid.value: return None
        info = GUI(); info.cbSize = C.sizeof(info)
        focus = int(info.focus or 0) if self.user.GetGUIThreadInfo(thread,C.byref(info)) else 0
        name = self.application(pid.value) if include_application else ''
        if revision != self.revision or self.user.GetForegroundWindow() != hwnd: return None
        return Target(int(hwnd),focus,pid.value,revision,name)

    def application(self,pid):
        name=''
        process = self.kernel.OpenProcess(0x1000,False,pid)
        if process:
            try:
                buffer = C.create_unicode_buffer(32768); size = W.DWORD(len(buffer))
                if self.kernel.QueryFullProcessImageNameW(process,0,buffer,C.byref(size)):
                    name = Path(buffer.value).stem
            finally: self.kernel.CloseHandle(process)
        return name

    def matches(self, target):
        now = self.capture()
        return bool(target and now and self.user.IsWindow(target.window) and
                    now.window == target.window and now.pid == target.pid and now.revision == target.revision and
                    (not target.focus or not now.focus or target.focus == now.focus))

    def modifiers_down(self):
        return any(self.user.GetAsyncKeyState(k)&0x8000 for k in MODIFIER_KEYS)

    def paste_keys(self):
        class KEY(C.Structure):
            _fields_ = [('vk',W.WORD),('scan',W.WORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        class MOUSE(C.Structure):
            _fields_ = [('dx',W.LONG),('dy',W.LONG),('data',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        class HARD(C.Structure): _fields_ = [('msg',W.DWORD),('low',W.WORD),('high',W.WORD)]
        class UNION(C.Union): _fields_ = [('key',KEY),('mouse',MOUSE),('hard',HARD)]
        class INPUT(C.Structure): _anonymous_ = ('value',); _fields_ = [('type',W.DWORD),('value',UNION)]
        events = (INPUT*4)()
        for event,(vk,up) in zip(events,[(0x11,False),(0x56,False),(0x56,True),(0x11,True)]):
            event.type = 1; event.key = KEY(vk,0,2 if up else 0,0,0)
        self.user.SendInput.argtypes = [W.UINT,C.POINTER(INPUT),C.c_int]; self.user.SendInput.restype = W.UINT
        return self.user.SendInput(4,events,C.sizeof(INPUT)) == 4

    def trash(self, path):
        from PySide6.QtCore import QFile
        if not QFile.supportsMoveToTrash(): raise OSError('当前设备不支持系统回收站，录音保留')
        file = QFile(Path(path).resolve().as_posix())
        if not file.moveToTrash(): raise OSError('未能移至系统回收站，原录音保留')


class Clipboard:
    """Copies all HGLOBAL formats. Refuses unsafe handle-only formats before mutation.
    This intentionally does not pretend CF_BITMAP/metafile handles are byte buffers.
    """
    HANDLE_FORMATS = {2,3,9,14,0x82,0x83,0x8e}
    def __init__(self, windows, owner):
        self.windows = windows; self._owner = owner
        self.original = None; self.owned = None; self.generation = 0
    @property
    def owner(self): return int(self._owner() if callable(self._owner) else self._owner)
    @property
    def sequence(self): return int(self.windows.user.GetClipboardSequenceNumber())
    def abandon(self): self.original = None; self.owned = None; self.generation += 1
    def _snapshot_open(self):
        U,K = self.windows.user,self.windows.kernel; result = []; total = 0; fmt = 0
        while True:
            C.set_last_error(0); fmt = U.EnumClipboardFormats(fmt)
            if not fmt:
                if C.get_last_error(): raise OSError('剪贴板格式读取失败')
                return result
            if fmt in self.HANDLE_FORMATS: raise ValueError('原剪贴板含暂不支持完整恢复的格式，已保留原内容')
            handle = U.GetClipboardData(fmt)
            if not handle: raise OSError('原剪贴板暂时不可读取')
            size = K.GlobalSize(handle)
            if not size or size > 64_000_000 or total+size > 128_000_000:
                raise ValueError('原剪贴板暂不适合完整暂存，已保留原内容')
            pointer = K.GlobalLock(handle)
            if not pointer: raise OSError('原剪贴板暂时不可读取')
            try: result.append((fmt,C.string_at(pointer,size))); total += size
            finally: K.GlobalUnlock(handle)
    def _write_open(self, rows):
        U,K = self.windows.user,self.windows.kernel
        # Allocate before EmptyClipboard to avoid destroying old data on allocation failure.
        prepared = []
        try:
            for fmt,data in rows:
                handle = K.GlobalAlloc(2,len(data)); pointer = K.GlobalLock(handle) if handle else None
                if not pointer:
                    if handle: K.GlobalFree(handle)
                    raise OSError('无法准备剪贴板数据')
                C.memmove(pointer,data,len(data)); K.GlobalUnlock(handle); prepared.append([fmt,handle])
            if not U.EmptyClipboard(): raise OSError('无法写入剪贴板')
            for pair in prepared:
                if not U.SetClipboardData(*pair): raise OSError('剪贴板写入未完成')
                pair[1] = None
        finally:
            for _,handle in prepared:
                if handle: K.GlobalFree(handle)
    def _claim(self):
        # CloseClipboard can synthesize text/locale formats and advance the
        # sequence. Claim the resulting version only while our HWND owns it.
        # Read the sequence first so a later user copy is still detected.
        sequence = self.sequence
        if int(self.windows.user.GetClipboardOwner() or 0) != self.owner:
            self.abandon(); return None
        self.owned = sequence
        return self.generation,self.owned
    def stage(self, text, keep):
        U = self.windows.user
        if not U.OpenClipboard(self.owner): raise OSError('剪贴板正在使用，请稍后复制')
        try:
            if self.original is not None and self.sequence != self.owned: self.abandon()
            original = None if keep else (self.original if self.original is not None else self._snapshot_open())
            try: self._write_open([(13,(text+'\0').encode('utf-16-le'))])
            except Exception:
                if original is not None:
                    try: self._write_open(original)
                    except Exception: pass
                raise
            self.generation += 1; self.original = original
        finally: U.CloseClipboard()
        token = self._claim()
        if token is None: raise ValueError('剪贴板已被其他应用更新，已保留最新内容')
        return token
    def restore(self, token):
        if self.original is None or token[0] != self.generation: return False
        if self.sequence != self.owned: self.abandon(); return False
        U = self.windows.user
        if not U.OpenClipboard(self.owner): return False
        try:
            if self.sequence != self.owned: self.abandon(); return False
            try: self._write_open(self.original)
            except (ValueError,OSError):
                # A partial multi-format write changes the sequence; retain the snapshot
                # and claim after CloseClipboard, including synthesized formats.
                pass
            else: self.abandon(); return True
        finally: U.CloseClipboard()
        self._claim(); return False


class Hooks:
    def __init__(self, windows, emit):
        self.windows = windows; self.emit = emit; self.gesture = Gesture()
        self.suspended = False; self.recording = False; self.capture_mouse = False
        self.thread_id = None; self.running = False; self.thread = None
        self.blocked_keys=set()
    def start(self):
        self.thread = threading.Thread(target=self._run, name='XiaohaHotkey', daemon=True); self.thread.start()
    def stop(self):
        if self.thread_id: self.windows.user.PostThreadMessageW(self.thread_id,0x12,0,0)
    def _run(self):
        U,K = self.windows.user,self.windows.kernel
        class KEY(C.Structure):
            _fields_ = [('vk',W.DWORD),('scan',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        class MOUSE(C.Structure):
            _fields_ = [('point',W.POINT),('data',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        callback_type = C.WINFUNCTYPE(C.c_ssize_t,C.c_int,W.WPARAM,W.LPARAM)
        U.SetWindowsHookExW.argtypes = [C.c_int,callback_type,W.HINSTANCE,W.DWORD]; U.SetWindowsHookExW.restype = W.HHOOK
        U.CallNextHookEx.argtypes = [W.HHOOK,C.c_int,W.WPARAM,W.LPARAM]; U.CallNextHookEx.restype = C.c_ssize_t
        U.UnhookWindowsHookEx.argtypes = [W.HHOOK]
        K.GetModuleHandleW.argtypes = [W.LPCWSTR]; K.GetModuleHandleW.restype = W.HMODULE
        K.GetCurrentThreadId.restype = W.DWORD
        U.PostThreadMessageW.argtypes = [W.DWORD,W.UINT,W.WPARAM,W.LPARAM]
        U.GetMessageW.argtypes = [C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT]
        U.GetMessageW.restype = W.BOOL
        U.TranslateMessage.argtypes = [C.POINTER(W.MSG)]; U.TranslateMessage.restype = W.BOOL
        U.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]; U.DispatchMessageW.restype = C.c_ssize_t
        @callback_type
        def keyboard(code,message,pointer):
            if code == 0:
                data = C.cast(pointer,C.POINTER(KEY)).contents
                if not data.flags&0x10:
                    vk = int(data.vk)
                    if vk == 16: vk = 0xA1 if data.scan == 0x36 else 0xA0
                    elif vk == 17: vk = 0xA3 if data.flags&1 else 0xA2
                    elif vk == 18: vk = 0xA5 if data.flags&1 else 0xA4
                    down = message in (0x100,0x104); config = self.gesture.shortcut
                    blocked=vk in self.blocked_keys
                    if not down: self.blocked_keys.discard(vk)
                    member = vk == config.key or bool(MODIFIER_KEYS.get(vk,0)&config.modifiers)
                    if not self.suspended:
                        if vk == 27 and self.recording:
                            if down: self.blocked_keys.add(vk); self.emit('cancel',None)
                            return 1
                        if down and not member: self.windows.revision += 1
                        trigger = self.gesture.key(vk,down)
                        if trigger: self.emit('toggle',self.windows.capture(False))
                        if vk == config.key and (config.key in MODIFIER_KEYS or trigger or self.gesture.armed):
                            if down: self.blocked_keys.add(vk)
                            return 1
                    if blocked: return 1
            return U.CallNextHookEx(None,code,message,pointer)
        @callback_type
        def mouse(code,message,pointer):
            if code == 0:
                data = C.cast(pointer,C.POINTER(MOUSE)).contents
                if not data.flags&1:
                    button = 3+int(data.data>>16) if message in (0x20B,0x20C) else 0
                    if button and self.capture_mouse:
                        if message == 0x20C: self.emit('mouseShortcut',{'keyCode':0,'modifiers':0,'mouseButton':button,'label':'鼠标侧键 '+str(button-3)})
                        return 1
                    if not self.suspended and button and button == self.gesture.shortcut.mouse:
                        if message == 0x20C: self.emit('toggle',self.windows.capture(False))
                        return 1
                    if message in (0x201,0x204,0x207,0x20A,0x20B,0x20E): self.windows.revision += 1
            return U.CallNextHookEx(None,code,message,pointer)
        self.thread_id = K.GetCurrentThreadId()
        module = K.GetModuleHandleW(None)
        key_hook = U.SetWindowsHookExW(13,keyboard,module,0); mouse_hook = U.SetWindowsHookExW(14,mouse,module,0)
        self.running = bool(key_hook and mouse_hook)
        self.emit('hookStatus',self.running)
        if not self.running:
            if key_hook: U.UnhookWindowsHookEx(key_hook)
            if mouse_hook: U.UnhookWindowsHookEx(mouse_hook)
            return
        try:
            msg = W.MSG()
            while U.GetMessageW(C.byref(msg),None,0,0)>0:
                U.TranslateMessage(C.byref(msg)); U.DispatchMessageW(C.byref(msg))
        finally:
            U.UnhookWindowsHookEx(key_hook); U.UnhookWindowsHookEx(mouse_hook); self.running = False
