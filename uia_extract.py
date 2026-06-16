"""
UI Automation text extraction for Windows.
Reads text + coordinates from foreground windows via the accessibility API.
Falls back gracefully if uiautomation is not installed or unavailable.
"""

import logging
import sys

logger = logging.getLogger(__name__)

UIA_ENABLED = True
UIA_MIN_ELEMENTS = 1
UIA_TIMEOUT_MS = 200

_available = None


def is_available():
    global _available
    if _available is not None:
        return _available
    if not UIA_ENABLED:
        _available = False
        return False
    if sys.platform != "win32":
        _available = False
        return False
    try:
        import uiautomation  # noqa: F401
        _available = True
    except ImportError:
        _available = False
        logger.info("UI Automation disabled: uiautomation package not installed")
    return _available


def extract_text_from_region(left, top, width, height):
    if not is_available():
        return None

    try:
        import uiautomation as auto

        auto.SetGlobalSearchTimeout(UIA_TIMEOUT_MS / 1000.0)

        cx = left + width // 2
        cy = top + height // 2
        control = auto.ControlFromPoint(cx, cy)

        if control is None:
            return None

        root = _find_window_root(control)
        if root is None:
            root = control

        blocks = []
        _walk_tree(root, left, top, width, height, blocks)

        if len(blocks) < UIA_MIN_ELEMENTS:
            return None

        return blocks

    except Exception:
        logger.exception("UI Automation extraction failed")
        return None


def _find_window_root(control):
    try:
        import uiautomation as auto
        current = control
        for _ in range(50):
            parent = current.GetParentControl()
            if parent is None:
                return current
            if isinstance(parent, auto.PaneControl) and parent.ClassName == "":
                return current
            ct = getattr(parent, "ControlTypeName", "")
            if ct == "WindowControl" or ct == "Window":
                return parent
            current = parent
        return current
    except Exception:
        return control


def _walk_tree(control, reg_left, reg_top, reg_w, reg_h, blocks, depth=0):
    if depth > 15:
        return

    try:
        rect = control.BoundingRectangle
        if rect is None:
            return
        cx, cy, cw, ch = rect.left, rect.top, rect.width(), rect.height()
    except Exception:
        return

    if cw <= 0 or ch <= 0:
        return
    if cx + cw < reg_left or cx > reg_left + reg_w:
        return
    if cy + ch < reg_top or cy > reg_top + reg_h:
        return

    text = ""
    try:
        name = control.Name
        if name and isinstance(name, str) and name.strip():
            text = name.strip()
    except Exception:
        pass

    if not text:
        try:
            vp = control.GetValuePattern()
            if vp and vp.Value:
                text = vp.Value.strip()
        except Exception:
            pass

    if text and len(text) > 1:
        local_x = max(0, cx - reg_left)
        local_y = max(0, cy - reg_top)
        block_w = min(cw, reg_left + reg_w - cx)
        block_h = min(ch, reg_top + reg_h - cy)

        if block_w > 0 and block_h > 0:
            blocks.append({
                "x": int(local_x),
                "y": int(local_y),
                "w": int(block_w),
                "h": int(block_h),
                "text": text,
                "median_char_h": max(10, int(ch * 0.8)),
                "median_conf": 100,
            })

    try:
        children = control.GetChildren()
        if children:
            for child in children:
                _walk_tree(child, reg_left, reg_top, reg_w, reg_h, blocks, depth + 1)
    except Exception:
        pass
