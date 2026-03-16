"""
Cross-process TreeView automation for RAS Mapper (WinForms .NET TreeView).

Provides functions to read tree items, find nodes by name, right-click nodes,
and interact with context menus -- all via ctypes (no pywin32 dependency).

The RAS Mapper TreeView is a WinForms WindowsForms10.SysTreeView32.app.*
control hosted in a .NET process.  Cross-process access requires
VirtualAllocEx / WriteProcessMemory / ReadProcessMemory because the
TVITEMEXW text buffer must live in the target process address space.
"""

import ctypes
import ctypes.wintypes as wintypes
import struct
import time
from typing import List, Tuple, Optional

# ---------------------------------------------------------------------------
# Win32 function setup  (ctypes only -- no pywin32)
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# -- SendMessageW with 64-bit compatible signature for HTREEITEM returns --
SendMessageW = user32.SendMessageW
SendMessageW.restype = ctypes.c_uint64
SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                         ctypes.c_uint64, ctypes.c_uint64]

# For messages that return a simple int/BOOL
SendMessageW_int = user32.SendMessageW
# (shares the same DLL export -- we just cast results where needed)

# -- PostMessageW --
PostMessageW = user32.PostMessageW
PostMessageW.restype = wintypes.BOOL
PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                         wintypes.WPARAM, wintypes.LPARAM]

# -- Window / process functions --
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.restype = wintypes.DWORD
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

OpenProcess = kernel32.OpenProcess
OpenProcess.restype = wintypes.HANDLE
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

CloseHandle = kernel32.CloseHandle
CloseHandle.restype = wintypes.BOOL
CloseHandle.argtypes = [wintypes.HANDLE]

VirtualAllocEx = kernel32.VirtualAllocEx
VirtualAllocEx.restype = ctypes.c_uint64
VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_uint64,
                           ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]

VirtualFreeEx = kernel32.VirtualFreeEx
VirtualFreeEx.restype = wintypes.BOOL
VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_uint64,
                          ctypes.c_size_t, wintypes.DWORD]

WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.restype = wintypes.BOOL
WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_uint64,
                               ctypes.c_void_p, ctypes.c_size_t,
                               ctypes.POINTER(ctypes.c_size_t)]

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.restype = wintypes.BOOL
ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_uint64,
                              ctypes.c_void_p, ctypes.c_size_t,
                              ctypes.POINTER(ctypes.c_size_t)]

FindWindowExW = user32.FindWindowExW
FindWindowExW.restype = wintypes.HWND
FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                          wintypes.LPCWSTR, wintypes.LPCWSTR]

FindWindowW = user32.FindWindowW
FindWindowW.restype = wintypes.HWND
FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

GetClassNameW = user32.GetClassNameW
GetClassNameW.restype = ctypes.c_int
GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.restype = ctypes.c_int
GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextLengthW.restype = ctypes.c_int
GetWindowTextLengthW.argtypes = [wintypes.HWND]

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.restype = wintypes.BOOL
IsWindowVisible.argtypes = [wintypes.HWND]

EnumChildWindows = user32.EnumChildWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildWindows.restype = wintypes.BOOL
EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]

EnumWindows = user32.EnumWindows
EnumWindows.restype = wintypes.BOOL
EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]

ClientToScreen = user32.ClientToScreen
ClientToScreen.restype = wintypes.BOOL
ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]

ScreenToClient = user32.ScreenToClient
ScreenToClient.restype = wintypes.BOOL
ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.restype = wintypes.BOOL
SetForegroundWindow.argtypes = [wintypes.HWND]

SetFocus = user32.SetFocus
SetFocus.restype = wintypes.HWND
SetFocus.argtypes = [wintypes.HWND]

GetCurrentThreadId = kernel32.GetCurrentThreadId
GetCurrentThreadId.restype = wintypes.DWORD
GetCurrentThreadId.argtypes = []

AttachThreadInput = user32.AttachThreadInput
AttachThreadInput.restype = wintypes.BOOL
AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

keybd_event = user32.keybd_event
keybd_event.restype = None
keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.POINTER(ctypes.c_ulong)]

GetMenu = user32.GetMenu
GetMenu.restype = wintypes.HMENU
GetMenu.argtypes = [wintypes.HWND]

GetMenuItemCount = user32.GetMenuItemCount
GetMenuItemCount.restype = ctypes.c_int
GetMenuItemCount.argtypes = [wintypes.HMENU]

GetMenuStringW = user32.GetMenuStringW
GetMenuStringW.restype = ctypes.c_int
GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT,
                           wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]

GetMenuItemID = user32.GetMenuItemID
GetMenuItemID.restype = wintypes.UINT
GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]

GetSubMenu = user32.GetSubMenu
GetSubMenu.restype = wintypes.HMENU
GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]

GetLastError = kernel32.GetLastError
GetLastError.restype = wintypes.DWORD

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Process access
PROCESS_ALL_ACCESS = 0x1F0FFF

# Memory allocation
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

# TreeView messages
TVM_GETNEXTITEM   = 0x110A
TVM_GETITEMW       = 0x113E
TVM_SELECTITEM     = 0x110B
TVM_GETITEMRECT    = 0x1104
TVM_EXPAND         = 0x1102

# TreeView TVGN flags (wParam for TVM_GETNEXTITEM)
TVGN_ROOT   = 0x0000
TVGN_NEXT   = 0x0001
TVGN_CHILD  = 0x0004
TVGN_CARET  = 0x0009

# TreeView expand flags
TVE_EXPAND   = 0x0002

# TVITEMEXW.mask flags
TVIF_TEXT       = 0x0001
TVIF_HANDLE     = 0x0010
TVIF_CHILDREN   = 0x0040

# Mouse messages
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP   = 0x0205
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
WM_COMMAND     = 0x0111

# Mouse key flags
MK_RBUTTON = 0x0002
MK_LBUTTON = 0x0001

# Menu flags
MF_BYPOSITION = 0x0400
MF_STRING     = 0x0000
MF_SEPARATOR  = 0x0800
MF_POPUP      = 0x0010

# Context menu classes
# Win32 native popup menus use #32768, but .NET WinForms ContextMenuStrip
# creates a ToolStripDropDown with this WinForms class:
POPUP_MENU_CLASS = "#32768"
WINFORMS_MENU_CLASS_FRAGMENT = "Window.808"  # ToolStripDropDown

# Keyboard constants
VK_SHIFT   = 0x10
VK_F10     = 0x79
VK_APPS    = 0x5D   # Context menu key (between right Alt and right Ctrl)
VK_ESCAPE  = 0x1B
VK_RETURN  = 0x0D
VK_DOWN    = 0x28
VK_UP      = 0x26
VK_LEFT    = 0x25
VK_RIGHT   = 0x27
KEYEVENTF_KEYUP = 0x0002
WM_KEYDOWN = 0x0100
WM_KEYUP   = 0x0101
WM_CONTEXTMENU = 0x007B

# TVITEMEXW struct size on 64-bit Windows
# Layout (64-bit):
#   UINT mask;            // 0   (4 bytes)
#   UINT _pad0;           // 4   (4 bytes padding)
#   HTREEITEM hItem;      // 8   (8 bytes -- pointer)
#   UINT state;           // 16  (4 bytes)
#   UINT stateMask;       // 20  (4 bytes)
#   LPWSTR pszText;       // 24  (8 bytes -- pointer)
#   int cchTextMax;       // 32  (4 bytes)
#   int iImage;           // 36  (4 bytes)
#   int iSelectedImage;   // 40  (4 bytes)
#   int cChildren;        // 44  (4 bytes)
#   UINT _pad1;           // 48  (4 bytes padding)  -- align lParam
#   LPARAM lParam;        // 52? actually 56 (8 bytes -- pointer)
# Actual struct: 64 bytes total with full alignment
TVITEMEXW_SIZE = 72  # generous -- covers all possible padding


def _make_lparam(x: int, y: int) -> int:
    """Pack (x, y) into an LPARAM (low word = x, high word = y)."""
    return (y << 16) | (x & 0xFFFF)


# ---------------------------------------------------------------------------
# Window discovery helpers
# ---------------------------------------------------------------------------

def get_class_name(hwnd: int) -> str:
    """Get the Win32 class name of a window handle."""
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_text(hwnd: int) -> str:
    """Get the window title / text."""
    length = GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    GetWindowTextW(hwnd, buf, length)
    return buf.value


def find_ras_mapper_window() -> Optional[int]:
    """
    Find the top-level RAS Mapper window.

    Returns:
        Window handle (HWND) or None.
    """
    results = []

    def _enum_cb(hwnd, _lp):
        if IsWindowVisible(hwnd):
            title = get_window_text(hwnd)
            if "RAS Mapper" in title:
                results.append(hwnd)
        return True

    cb = WNDENUMPROC(_enum_cb)
    EnumWindows(cb, 0)

    if results:
        return results[0]
    return None


def find_treeview_in_window(parent_hwnd: int) -> Optional[int]:
    """
    Recursively search for a SysTreeView32 control inside a window.

    The RAS Mapper TreeView class is
    ``WindowsForms10.SysTreeView32.app.*`` -- we match on 'SysTreeView32'.

    Returns:
        TreeView HWND or None.
    """
    results = []

    def _enum_cb(hwnd, _lp):
        cls = get_class_name(hwnd)
        if "SysTreeView32" in cls:
            results.append(hwnd)
        return True

    cb = WNDENUMPROC(_enum_cb)
    EnumChildWindows(parent_hwnd, cb, 0)

    if results:
        return results[0]
    return None


# ---------------------------------------------------------------------------
# Cross-process TreeView reading
# ---------------------------------------------------------------------------

def _open_process_for_hwnd(hwnd: int):
    """
    Open the process that owns *hwnd* with full access.

    Returns:
        (hProcess, pid)  -- caller must CloseHandle(hProcess).
    """
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        raise RuntimeError(f"GetWindowThreadProcessId failed for hwnd {hwnd:#x}")
    hProcess = OpenProcess(PROCESS_ALL_ACCESS, False, pid.value)
    if not hProcess:
        raise RuntimeError(
            f"OpenProcess failed for PID {pid.value} (error {GetLastError()}). "
            "Try running as Administrator."
        )
    return hProcess, pid.value


def _read_tree_item_text(
    hwnd: int,
    hProcess: int,
    hItem: int,
    remote_buf: int,
    remote_text: int,
    text_buf_size: int = 512,
) -> str:
    """
    Read the text of a single tree item via cross-process memory.

    Parameters:
        hwnd        -- TreeView HWND
        hProcess    -- handle from OpenProcess
        hItem       -- HTREEITEM
        remote_buf  -- remote address for TVITEMEXW struct
        remote_text -- remote address for text buffer
        text_buf_size -- size of the text buffer in *characters*

    Returns:
        The item text as a Python str.
    """
    # Build the TVITEMEXW struct locally.
    # 64-bit layout -- we pack manually to be sure of alignment.
    #
    # Offsets (64-bit):
    #   0: mask       (UINT,  4)
    #   4: pad        (4)
    #   8: hItem      (HTREEITEM, 8)
    #  16: state      (UINT, 4)
    #  20: stateMask  (UINT, 4)
    #  24: pszText    (LPWSTR, 8)
    #  32: cchTextMax (int, 4)
    #  36: iImage     (int, 4)
    #  40: iSelectedImage (int, 4)
    #  44: cChildren  (int, 4)
    #  48: lParam     (LPARAM, 8)  -- packed struct may add pad here
    #  Total through lParam: 56 bytes
    #
    # We'll write 72 bytes (generous) so padding doesn't matter.

    local_buf = (ctypes.c_byte * TVITEMEXW_SIZE)()
    ctypes.memset(local_buf, 0, TVITEMEXW_SIZE)

    mask = TVIF_TEXT | TVIF_HANDLE | TVIF_CHILDREN
    struct.pack_into("<I", local_buf, 0, mask)           # mask
    struct.pack_into("<Q", local_buf, 8, hItem)          # hItem (64-bit ptr)
    struct.pack_into("<Q", local_buf, 24, remote_text)   # pszText (64-bit ptr)
    struct.pack_into("<i", local_buf, 32, text_buf_size) # cchTextMax

    # Write struct to remote process
    written = ctypes.c_size_t()
    ok = WriteProcessMemory(hProcess, remote_buf, local_buf,
                            TVITEMEXW_SIZE, ctypes.byref(written))
    if not ok:
        return f"<WriteProcessMemory failed: {GetLastError()}>"

    # Zero out remote text buffer first
    zero_buf = (ctypes.c_byte * (text_buf_size * 2))()
    WriteProcessMemory(hProcess, remote_text, zero_buf,
                       text_buf_size * 2, ctypes.byref(written))

    # Send TVM_GETITEMW
    result = SendMessageW(hwnd, TVM_GETITEMW, 0, remote_buf)
    if result == 0:
        # The message can return 0 on success for some implementations --
        # still try to read the text.
        pass

    # Read text back
    local_text = (ctypes.c_byte * (text_buf_size * 2))()
    read_bytes = ctypes.c_size_t()
    ok = ReadProcessMemory(hProcess, remote_text, local_text,
                           text_buf_size * 2, ctypes.byref(read_bytes))
    if not ok:
        return f"<ReadProcessMemory failed: {GetLastError()}>"

    # Decode UTF-16LE
    raw = bytes(local_text)
    try:
        text = raw.decode("utf-16-le")
        text = text.split("\x00", 1)[0]  # truncate at first null
    except Exception:
        text = "<decode error>"

    return text


def read_tree_items(treeview_hwnd: int) -> List[Tuple[int, int, str]]:
    """
    Walk the entire TreeView and return every item.

    Returns:
        List of (hItem, depth, text) tuples.
    """
    hProcess, pid = _open_process_for_hwnd(treeview_hwnd)
    text_buf_chars = 512
    alloc_size = TVITEMEXW_SIZE + text_buf_chars * 2 + 64  # struct + text + slack

    remote_mem = VirtualAllocEx(
        hProcess, 0, alloc_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    )
    if not remote_mem:
        CloseHandle(hProcess)
        raise RuntimeError(f"VirtualAllocEx failed (error {GetLastError()})")

    remote_struct = remote_mem
    remote_text = remote_mem + TVITEMEXW_SIZE + 16  # 16 bytes slack

    items: List[Tuple[int, int, str]] = []

    def _walk(parent_hItem: int, depth: int):
        if parent_hItem == 0:
            return
        hItem = parent_hItem
        while hItem:
            text = _read_tree_item_text(
                treeview_hwnd, hProcess, hItem,
                remote_struct, remote_text, text_buf_chars,
            )
            items.append((hItem, depth, text))
            # Recurse into children
            child = SendMessageW(treeview_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, hItem)
            if child and child != 0:
                _walk(child, depth + 1)
            # Next sibling
            hItem = SendMessageW(treeview_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, hItem)

    # Get root item
    root = SendMessageW(treeview_hwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    if root:
        _walk(root, 0)

    VirtualFreeEx(hProcess, remote_mem, 0, MEM_RELEASE)
    CloseHandle(hProcess)
    return items


def find_tree_item(treeview_hwnd: int, target_text: str) -> int:
    """
    Find a tree item by (case-insensitive) name.

    Returns:
        HTREEITEM handle, or 0 if not found.
    """
    items = read_tree_items(treeview_hwnd)
    target_lower = target_text.lower()
    for hItem, _depth, text in items:
        if text.lower() == target_lower:
            return hItem
    # Partial / substring match as fallback
    for hItem, _depth, text in items:
        if target_lower in text.lower():
            return hItem
    return 0


def find_tree_item_by_path(
    treeview_hwnd: int,
    path: List[str],
) -> int:
    """
    Navigate the TreeView by a list of node names, expanding each level.

    Example:
        find_tree_item_by_path(tv, ["Geometries", "Muncie", "2D Flow Areas"])

    Returns:
        HTREEITEM of the final node, or 0 if not found.
    """
    hProcess, pid = _open_process_for_hwnd(treeview_hwnd)
    text_buf_chars = 512
    alloc_size = TVITEMEXW_SIZE + text_buf_chars * 2 + 64
    remote_mem = VirtualAllocEx(
        hProcess, 0, alloc_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    )
    if not remote_mem:
        CloseHandle(hProcess)
        return 0

    remote_struct = remote_mem
    remote_text = remote_mem + TVITEMEXW_SIZE + 16

    current = SendMessageW(treeview_hwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)

    for depth, target_name in enumerate(path):
        target_lower = target_name.lower()
        found = 0
        while current:
            text = _read_tree_item_text(
                treeview_hwnd, hProcess, current,
                remote_struct, remote_text, text_buf_chars,
            )
            if text.lower() == target_lower or target_lower in text.lower():
                found = current
                break
            current = SendMessageW(treeview_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, current)

        if not found:
            VirtualFreeEx(hProcess, remote_mem, 0, MEM_RELEASE)
            CloseHandle(hProcess)
            print(f"[!] Could not find '{target_name}' at depth {depth}")
            return 0

        # Expand this node if we need to go deeper
        if depth < len(path) - 1:
            SendMessageW(treeview_hwnd, TVM_EXPAND, TVE_EXPAND, found)
            time.sleep(0.1)
            # Move to first child for next iteration
            current = SendMessageW(treeview_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, found)
        else:
            current = found

    VirtualFreeEx(hProcess, remote_mem, 0, MEM_RELEASE)
    CloseHandle(hProcess)
    return current


# ---------------------------------------------------------------------------
# Right-click / context menu interaction
# ---------------------------------------------------------------------------

def _focus_treeview(treeview_hwnd: int) -> bool:
    """
    Set keyboard focus to the TreeView via AttachThreadInput + SetFocus.

    Cross-process focus requires attaching our thread's input queue to the
    target window's thread first.  Returns True if focus was set.
    """
    pid = wintypes.DWORD()
    target_tid = GetWindowThreadProcessId(treeview_hwnd, ctypes.byref(pid))
    our_tid = GetCurrentThreadId()

    if target_tid == 0:
        print("[!] GetWindowThreadProcessId failed")
        return False

    # Bring the top-level parent to foreground first
    parent = _find_top_level_parent(treeview_hwnd)
    if parent:
        SetForegroundWindow(parent)
    time.sleep(0.1)

    # Attach our input queue to target thread
    attached = False
    if our_tid != target_tid:
        attached = bool(AttachThreadInput(our_tid, target_tid, True))
        if not attached:
            print(f"[!] AttachThreadInput failed (error {GetLastError()})")

    try:
        SetFocus(treeview_hwnd)
        time.sleep(0.05)
        return True
    finally:
        if attached:
            AttachThreadInput(our_tid, target_tid, False)


def _keyboard_context_menu(treeview_hwnd: int) -> bool:
    """
    Open context menu via keyboard: Shift+F10 or VK_APPS.

    .NET WinForms generates WM_CONTEXTMENU with lParam=-1 for keyboard-
    triggered context menus, which is the standard code path that
    ContextMenuStrip responds to.  This is MORE RELIABLE than synthetic
    mouse messages for cross-process .NET automation.

    Returns True if a popup menu appeared.
    """
    # Method 1: VK_APPS key (dedicated context menu key)
    keybd_event(VK_APPS, 0, 0, None)
    time.sleep(0.05)
    keybd_event(VK_APPS, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.5)

    menu_hwnd = _find_popup_menu()
    if menu_hwnd:
        print(f"[+] Context menu via VK_APPS: hwnd={menu_hwnd:#x}")
        return True

    # Method 2: Shift+F10 (equivalent to VK_APPS on all keyboards)
    keybd_event(VK_SHIFT, 0, 0, None)
    time.sleep(0.02)
    keybd_event(VK_F10, 0, 0, None)
    time.sleep(0.05)
    keybd_event(VK_F10, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.02)
    keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.5)

    menu_hwnd = _find_popup_menu()
    if menu_hwnd:
        print(f"[+] Context menu via Shift+F10: hwnd={menu_hwnd:#x}")
        return True

    # Method 3: Post WM_CONTEXTMENU directly with lParam=-1 (keyboard flag)
    PostMessageW(treeview_hwnd, WM_CONTEXTMENU,
                 treeview_hwnd, 0xFFFFFFFF)  # lParam=-1 = keyboard
    time.sleep(0.5)

    menu_hwnd = _find_popup_menu()
    if menu_hwnd:
        print(f"[+] Context menu via WM_CONTEXTMENU: hwnd={menu_hwnd:#x}")
        return True

    return False


def _postmessage_right_click(treeview_hwnd: int, hItem: int) -> bool:
    """
    Fallback right-click via PostMessage WM_RBUTTONDOWN/UP.

    This may NOT work with .NET WinForms because SendMessage/PostMessage
    for mouse messages bypasses DefWindowProc's WM_RBUTTONUP -> WM_CONTEXTMENU
    translation in some .NET WndProc overrides.
    """
    # Get item rectangle for click coordinates
    hProcess, pid = _open_process_for_hwnd(treeview_hwnd)
    remote_rect = VirtualAllocEx(
        hProcess, 0, 64, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    )
    if not remote_rect:
        CloseHandle(hProcess)
        return False

    hItem_bytes = struct.pack("<Q", hItem)
    written = ctypes.c_size_t()
    WriteProcessMemory(hProcess, remote_rect, hItem_bytes, 8, ctypes.byref(written))
    result = SendMessageW(treeview_hwnd, TVM_GETITEMRECT, 1, remote_rect)

    local_rect = (ctypes.c_byte * 16)()
    read_sz = ctypes.c_size_t()
    ReadProcessMemory(hProcess, remote_rect, local_rect, 16, ctypes.byref(read_sz))
    VirtualFreeEx(hProcess, remote_rect, 0, MEM_RELEASE)
    CloseHandle(hProcess)

    left, top, right, bottom = struct.unpack("<iiii", bytes(local_rect))
    cx = (left + right) // 2
    cy = (top + bottom) // 2

    if cx <= 0 or cy <= 0:
        cx, cy = 80, 20
        print(f"[!] Using fallback click position ({cx}, {cy})")
    else:
        print(f"[*] PostMessage right-click at ({cx}, {cy})")

    parent = _find_top_level_parent(treeview_hwnd)
    if parent:
        SetForegroundWindow(parent)
    time.sleep(0.1)

    lp = _make_lparam(cx, cy)
    PostMessageW(treeview_hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lp)
    time.sleep(0.1)
    PostMessageW(treeview_hwnd, WM_RBUTTONUP, 0, lp)
    time.sleep(0.5)

    menu_hwnd = _find_popup_menu()
    if menu_hwnd:
        print(f"[+] Context menu via PostMessage: hwnd={menu_hwnd:#x}")
        return True

    for _ in range(5):
        time.sleep(0.2)
        menu_hwnd = _find_popup_menu()
        if menu_hwnd:
            print(f"[+] Context menu via PostMessage: hwnd={menu_hwnd:#x}")
            return True

    return False


def _physical_mouse_right_click(treeview_hwnd: int, hItem: int) -> bool:
    """
    Open context menu via physical mouse left-click + right-click.

    .NET WinForms ToolStripDropDown context menus require physical mouse
    input — they do NOT respond to PostMessage or SendMessage mouse events.
    A left-click is needed first to establish selection in the WinForms
    event model before right-click produces the context menu.

    The context menu appears as a WindowsForms10.Window.808.* window
    (ToolStripDropDown), NOT as a Win32 #32768 popup.

    Returns True if a context menu appeared.
    """
    # Get item rectangle in screen coordinates
    hProcess, pid = _open_process_for_hwnd(treeview_hwnd)
    remote_rect = VirtualAllocEx(
        hProcess, 0, 64, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    )
    if not remote_rect:
        CloseHandle(hProcess)
        return False

    hItem_bytes = struct.pack("<Q", hItem)
    written = ctypes.c_size_t()
    WriteProcessMemory(hProcess, remote_rect, hItem_bytes, 8, ctypes.byref(written))
    result = SendMessageW(treeview_hwnd, TVM_GETITEMRECT, 1, remote_rect)

    local_rect = (ctypes.c_byte * 16)()
    read_sz = ctypes.c_size_t()
    ReadProcessMemory(hProcess, remote_rect, local_rect, 16, ctypes.byref(read_sz))
    VirtualFreeEx(hProcess, remote_rect, 0, MEM_RELEASE)
    CloseHandle(hProcess)

    left, top, right, bottom = struct.unpack("<iiii", bytes(local_rect))

    # Convert client coords to screen coords
    pt1 = wintypes.POINT(left, top)
    user32.ClientToScreen(treeview_hwnd, ctypes.byref(pt1))
    pt2 = wintypes.POINT(right, bottom)
    user32.ClientToScreen(treeview_hwnd, ctypes.byref(pt2))

    cx = (pt1.x + pt2.x) // 2
    cy = (pt1.y + pt2.y) // 2

    if cx <= 0 or cy <= 0:
        print("[!] Could not get valid screen coordinates for item")
        return False

    print(f"[*] Physical mouse click at screen ({cx}, {cy})")

    # Bring window to foreground
    parent = _find_top_level_parent(treeview_hwnd)
    if parent:
        SetForegroundWindow(parent)
    time.sleep(0.5)

    # Physical LEFT click first (establishes WinForms selection)
    user32.SetCursorPos(cx, cy)
    time.sleep(0.3)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    time.sleep(0.5)

    # Physical RIGHT click
    user32.mouse_event(0x0008, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTDOWN
    time.sleep(0.15)
    user32.mouse_event(0x0010, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTUP
    time.sleep(1.0)

    menu_hwnd = _find_popup_menu()
    if menu_hwnd:
        print(f"[+] Context menu via physical mouse: hwnd={menu_hwnd:#x}")
        return True

    # Retry with longer wait
    for _ in range(3):
        time.sleep(0.5)
        menu_hwnd = _find_popup_menu()
        if menu_hwnd:
            print(f"[+] Context menu via physical mouse: hwnd={menu_hwnd:#x}")
            return True

    return False


def right_click_tree_item(treeview_hwnd: int, hItem: int) -> bool:
    """
    Right-click a tree item to open its context menu.

    Uses a multi-strategy approach:
      1. Select item via TVM_SELECTITEM
      2. PRIMARY: Physical mouse left+right click (required for WinForms)
      3. FALLBACK 1: Keyboard context menu (VK_APPS / Shift+F10)
      4. FALLBACK 2: PostMessage WM_RBUTTONDOWN/UP

    Returns:
        True if the context menu appeared.
    """
    # 1. Select the item via Win32 message (scrolls it into view)
    SendMessageW(treeview_hwnd, TVM_SELECTITEM, TVGN_CARET, hItem)
    time.sleep(0.2)

    # 2. PRIMARY: Physical mouse click (works with .NET WinForms)
    print("[*] Trying physical mouse right-click...")
    if _physical_mouse_right_click(treeview_hwnd, hItem):
        return True

    # 3. FALLBACK 1: Keyboard context menu
    print("[*] Physical mouse failed, trying keyboard (VK_APPS / Shift+F10)...")
    _focus_treeview(treeview_hwnd)
    time.sleep(0.1)
    if _keyboard_context_menu(treeview_hwnd):
        return True

    # 4. FALLBACK 2: PostMessage right-click
    print("[*] Keyboard failed, trying PostMessage right-click...")
    if _postmessage_right_click(treeview_hwnd, hItem):
        return True

    print("[!] All right-click methods failed")
    return False


def _find_top_level_parent(hwnd: int) -> int:
    """Walk up the parent chain to find the top-level window."""
    GetParent = user32.GetParent
    GetParent.restype = wintypes.HWND
    GetParent.argtypes = [wintypes.HWND]

    current = hwnd
    while True:
        parent = GetParent(current)
        if not parent:
            return current
        current = parent


def _find_popup_menu() -> Optional[int]:
    """
    Find a visible context menu window.

    Checks for both Win32 native popup (#32768) and .NET WinForms
    ToolStripDropDown (WindowsForms10.Window.808.*).
    """
    results = []

    def _enum_cb(hwnd, _lp):
        if IsWindowVisible(hwnd):
            cls = get_class_name(hwnd)
            if cls == POPUP_MENU_CLASS or WINFORMS_MENU_CLASS_FRAGMENT in cls:
                results.append(hwnd)
        return True

    cb = WNDENUMPROC(_enum_cb)
    EnumWindows(cb, 0)
    return results[0] if results else None


def _get_menu_handle_from_popup(popup_hwnd: int):
    """
    Get the HMENU from a #32768 popup menu window.

    The menu handle is sent via MN_GETHMENU (0x01E1).
    """
    MN_GETHMENU = 0x01E1
    hmenu = SendMessageW(popup_hwnd, MN_GETHMENU, 0, 0)
    return hmenu


def click_context_menu_item(menu_text: str, timeout: float = 2.0) -> bool:
    """
    Find and click an item in the currently-open context menu.

    Parameters:
        menu_text -- text (or substring) of the menu item to click.
        timeout   -- seconds to wait for menu to appear.

    Returns:
        True if the item was found and clicked.
    """
    # Find the popup menu window
    deadline = time.time() + timeout
    popup_hwnd = None
    while time.time() < deadline:
        popup_hwnd = _find_popup_menu()
        if popup_hwnd:
            break
        time.sleep(0.1)

    if not popup_hwnd:
        print("[!] No popup menu found")
        return False

    # Get the HMENU
    hmenu = _get_menu_handle_from_popup(popup_hwnd)
    if not hmenu:
        print("[!] Could not get HMENU from popup window")
        return False

    count = GetMenuItemCount(hmenu)
    print(f"[*] Context menu has {count} items (hmenu={hmenu:#x})")

    target_lower = menu_text.lower()
    buf = ctypes.create_unicode_buffer(256)

    found_id = None
    found_pos = None
    found_text = None

    for i in range(count):
        result = GetMenuStringW(hmenu, i, buf, 256, MF_BYPOSITION)
        if result > 0:
            item_text = buf.value
            item_id = GetMenuItemID(hmenu, i)
            print(f"    [{i}] '{item_text}'  (id={item_id})")

            if target_lower in item_text.lower():
                found_id = item_id
                found_pos = i
                found_text = item_text
        else:
            print(f"    [{i}] <separator or empty>")

    if found_id is None:
        print(f"[!] Menu item '{menu_text}' not found")
        # Dismiss the menu
        SendMessageW(popup_hwnd, WM_LBUTTONDOWN, 0, 0)
        return False

    print(f"[+] Clicking menu item '{found_text}' (id={found_id}, pos={found_pos})")

    # Find the owner window of the menu to send WM_COMMAND
    # The owner is typically the TreeView's top-level parent or the TreeView itself.
    # We can send WM_COMMAND to the popup window -- the system will forward it.
    # But the standard approach is to find the menu's owner.
    # Simplest: just post WM_COMMAND with the menu ID to the popup's owner.

    # Method: send MN_SELECTITEM + MN_EXECUTE or just use WM_COMMAND.
    # Actually the most reliable way is: get the owner and WM_COMMAND it.
    # The owner can be found via GetWindow(popup_hwnd, GW_OWNER).

    GetWindow = user32.GetWindow
    GetWindow.restype = wintypes.HWND
    GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    GW_OWNER = 4
    owner = GetWindow(popup_hwnd, GW_OWNER)
    if not owner:
        # Fallback: try sending to popup window
        owner = popup_hwnd

    print(f"[*] Menu owner window: {owner:#x} ('{get_window_text(owner)}')")

    if found_id and found_id != 0xFFFFFFFF:
        # Send WM_COMMAND with the menu item ID
        PostMessageW(owner, WM_COMMAND, found_id, 0)
    else:
        # The item might be a submenu -- found_id == -1 means popup item
        # For submenus, we would need to navigate into them.
        # For now, try positional click approach.
        print(f"[!] Menu item has no direct ID (may be a submenu). Trying positional click.")
        _click_menu_item_by_position(popup_hwnd, found_pos)

    time.sleep(0.2)
    return True


def _click_menu_item_by_position(popup_hwnd: int, position: int):
    """
    Click a menu item by sending mouse messages at its position.

    Uses MENUITEMINFO to get the item's rectangle, then clicks its center.
    """
    # We'll use GetMenuItemRect (user32)
    GetMenuItemRect = user32.GetMenuItemRect
    GetMenuItemRect.restype = wintypes.BOOL
    GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT,
                                ctypes.POINTER(wintypes.RECT)]

    hmenu = _get_menu_handle_from_popup(popup_hwnd)

    rect = wintypes.RECT()
    ok = GetMenuItemRect(popup_hwnd, hmenu, position, ctypes.byref(rect))
    if not ok:
        print(f"[!] GetMenuItemRect failed for position {position}")
        return

    # rect is in screen coordinates -- convert to client coords of popup
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2

    pt = wintypes.POINT(cx, cy)
    ScreenToClient(popup_hwnd, ctypes.byref(pt))

    lp = _make_lparam(pt.x, pt.y)
    SendMessageW(popup_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.05)
    SendMessageW(popup_hwnd, WM_LBUTTONUP, 0, lp)


def click_context_menu_item_uia(menu_text: str, timeout: float = 2.0) -> bool:
    """
    Find and click a context menu item using UI Automation.

    This works with .NET WinForms ToolStripDropDown menus that do NOT
    respond to standard Win32 GetMenu/GetMenuItemCount messages.

    Requires comtypes to be installed.

    Parameters:
        menu_text -- text (or substring) of the menu item to click.
        timeout   -- seconds to wait for menu item to be found.

    Returns:
        True if the item was found and clicked.
    """
    try:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import IUIAutomation

        uia = comtypes.CoCreateInstance(
            comtypes.GUID("{FF48DBA4-60EF-4201-AA87-54103EEF594E}"),
            interface=IUIAutomation,
        )
        root = uia.GetRootElement()

        # Search for the menu item by name
        UIA_NamePropertyId = 30005
        cond = uia.CreatePropertyCondition(UIA_NamePropertyId, menu_text)

        deadline = time.time() + timeout
        item = None
        while time.time() < deadline:
            item = root.FindFirst(4, cond)  # TreeScope_Descendants
            if item:
                break
            time.sleep(0.2)

        if not item:
            # Try partial match by searching all menu items
            UIA_MenuItemControlTypeId = 50011
            UIA_ControlTypePropertyId = 30003
            mi_cond = uia.CreatePropertyCondition(
                UIA_ControlTypePropertyId, UIA_MenuItemControlTypeId
            )
            all_items = root.FindAll(4, mi_cond)
            if all_items:
                target_lower = menu_text.lower()
                for i in range(all_items.Length):
                    mi = all_items.GetElement(i)
                    try:
                        if target_lower in mi.CurrentName.lower():
                            item = mi
                            break
                    except Exception:
                        continue

        if not item:
            print(f"[!] Menu item '{menu_text}' not found via UIA")
            return False

        print(f"[+] Found menu item: '{item.CurrentName}'")

        # Get bounding rectangle and click physically
        rect = item.CurrentBoundingRectangle
        mx = (rect.left + rect.right) // 2
        my = (rect.top + rect.bottom) // 2

        user32.SetCursorPos(mx, my)
        time.sleep(0.2)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        time.sleep(0.3)

        return True

    except ImportError:
        print("[!] comtypes not installed -- UIA menu click unavailable")
        return False
    except Exception as e:
        print(f"[!] UIA menu click failed: {e}")
        return False


def enumerate_context_menu() -> List[Tuple[int, str, int]]:
    """
    Enumerate items in the currently-visible context menu.

    Returns:
        List of (position, text, menu_id) tuples.
    """
    popup_hwnd = _find_popup_menu()
    if not popup_hwnd:
        return []

    hmenu = _get_menu_handle_from_popup(popup_hwnd)
    if not hmenu:
        return []

    count = GetMenuItemCount(hmenu)
    items = []
    buf = ctypes.create_unicode_buffer(256)

    for i in range(count):
        result = GetMenuStringW(hmenu, i, buf, 256, MF_BYPOSITION)
        if result > 0:
            text = buf.value
            item_id = GetMenuItemID(hmenu, i)
            items.append((i, text, item_id))
        else:
            items.append((i, "<separator>", 0))

    return items


# ---------------------------------------------------------------------------
# Convenience / high-level
# ---------------------------------------------------------------------------

def find_and_right_click(
    target_node: str,
    menu_item: Optional[str] = None,
) -> bool:
    """
    High-level: find RAS Mapper TreeView, locate a node, right-click it,
    and optionally click a context menu item.

    Parameters:
        target_node -- tree node text to find (e.g. "2D Flow Areas")
        menu_item   -- context menu item to click (e.g. "View 2D Flow Area Properties")
                       If None, just opens the context menu.

    Returns:
        True on success.
    """
    # Find RAS Mapper
    mapper_hwnd = find_ras_mapper_window()
    if not mapper_hwnd:
        print("[!] Could not find RAS Mapper window")
        return False
    print(f"[+] RAS Mapper window: {mapper_hwnd:#x}")

    # Find TreeView
    tv_hwnd = find_treeview_in_window(mapper_hwnd)
    if not tv_hwnd:
        print("[!] Could not find TreeView in RAS Mapper")
        return False
    print(f"[+] TreeView hwnd: {tv_hwnd:#x}  class='{get_class_name(tv_hwnd)}'")

    # Find the target node
    hItem = find_tree_item(tv_hwnd, target_node)
    if not hItem:
        print(f"[!] Tree item '{target_node}' not found")
        return False
    print(f"[+] Found '{target_node}' at hItem={hItem:#x}")

    # Right-click it
    ok = right_click_tree_item(tv_hwnd, hItem)
    if not ok:
        return False

    # Optionally click a menu item
    if menu_item:
        time.sleep(0.2)
        return click_context_menu_item(menu_item)

    return True


# ---------------------------------------------------------------------------
# Main -- live test
# ---------------------------------------------------------------------------

def dismiss_context_menu():
    """Dismiss any open context menu by pressing Escape."""
    keybd_event(VK_ESCAPE, 0, 0, None)
    time.sleep(0.05)
    keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.2)


def main():
    print("=" * 70)
    print("RAS Mapper TreeView Automation (ctypes only)")
    print("=" * 70)

    # 1. Find RAS Mapper window
    mapper_hwnd = find_ras_mapper_window()
    if not mapper_hwnd:
        print("[!] RAS Mapper window not found. Is HEC-RAS open with RAS Mapper visible?")
        return
    print(f"\n[+] RAS Mapper window: {mapper_hwnd:#x}  title='{get_window_text(mapper_hwnd)}'")

    # 2. Find TreeView
    tv_hwnd = find_treeview_in_window(mapper_hwnd)
    if not tv_hwnd:
        print("[!] TreeView control not found inside RAS Mapper")
        return
    print(f"[+] TreeView: {tv_hwnd:#x}  class='{get_class_name(tv_hwnd)}'")

    # 3. Read all tree items
    print(f"\n{'='*70}")
    print("Tree Contents:")
    print(f"{'='*70}")
    items = read_tree_items(tv_hwnd)
    if not items:
        print("[!] No tree items found (tree may be empty or access denied)")
        return

    for hItem, depth, text in items:
        indent = "  " * depth
        print(f"  {indent}[{hItem:#010x}] {text}")
    print(f"\nTotal items: {len(items)}")

    # 4. Try to find a specific node
    search_targets = ["2D Flow Areas", "Perimeters", "Geometries", "Results"]
    print(f"\n{'='*70}")
    print("Searching for specific nodes:")
    print(f"{'='*70}")
    for target in search_targets:
        hItem = find_tree_item(tv_hwnd, target)
        if hItem:
            print(f"  [+] '{target}' -> hItem={hItem:#010x}")
        else:
            print(f"  [-] '{target}' -> not found")

    # 5. Right-click test using NEW keyboard approach
    for target in search_targets:
        hItem = find_tree_item(tv_hwnd, target)
        if hItem:
            print(f"\n{'='*70}")
            print(f"Right-click test on '{target}' (keyboard + fallbacks):")
            print(f"{'='*70}")
            ok = right_click_tree_item(tv_hwnd, hItem)
            if ok:
                time.sleep(0.3)
                menu_items = enumerate_context_menu()
                if menu_items:
                    print(f"\nContext menu items:")
                    for pos, text, mid in menu_items:
                        print(f"  [{pos}] '{text}' (id={mid})")
                dismiss_context_menu()
            break

    # 6. Path-based navigation test
    print(f"\n{'='*70}")
    print("Path navigation test:")
    print(f"{'='*70}")
    # Try to navigate to 2D Flow Areas via path
    test_paths = [
        ["Geometries"],
        ["Results"],
    ]
    for path in test_paths:
        hItem = find_tree_item_by_path(tv_hwnd, path)
        if hItem:
            print(f"  [+] Path {' > '.join(path)} -> hItem={hItem:#010x}")
        else:
            print(f"  [-] Path {' > '.join(path)} -> not found")


if __name__ == "__main__":
    main()
