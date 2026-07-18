#!/usr/bin/env python3
"""
Claude Code Progress Sidebar  (native macOS / AppKit build)
-----------------------------------------------------------
A floating, always-on-top panel that shows, for the currently active
Claude Code session:

  * NOW    - what Claude is doing (last message + last tool used)
  * GOAL   - progress on the todo list (done / total, bar + %)
  * ETA    - estimated time-to-finish, derived from completion rate

It only reads files Claude Code already writes:
  ~/.claude/projects/<slug>/<sessionId>.jsonl   -> activity feed
  ~/.claude/todos/<sessionId>*.json             -> goal / progress

Pure stdlib + PyObjC (ships with the macOS system python3). No pip installs.

Run with the SYSTEM python (has AppKit):
    /usr/bin/python3 progress_sidebar.py
    /usr/bin/python3 progress_sidebar.py --cwd /Volumes/PortableSSD
    /usr/bin/python3 progress_sidebar.py --interval 1.5
"""

import argparse
import glob
import json
import os
import time
from datetime import datetime, timezone

from AppKit import (
    NSApplication, NSApp, NSWindow, NSView, NSTextField, NSColor, NSFont,
    NSMakeRect, NSBackingStoreBuffered, NSApplicationActivationPolicyAccessory,
    NSFloatingWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary, NSLineBreakByWordWrapping,
)
from Foundation import NSObject, NSTimer
import objc

# Style masks (constants not always exported by name across versions)
NS_TITLED = 1 << 0
NS_CLOSABLE = 1 << 1
NS_MINIATURIZABLE = 1 << 2

HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
TODOS_DIR = os.path.join(HOME, ".claude", "todos")
STATE_FILE = os.path.join(HOME, ".claude", ".progress-sidebar-state.json")


def hex_color(h, a=1.0):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


BG = "#1c1c1c"
FG = "#e6e6e6"
MUTED = "#8a8a8a"
ACCENT = "#d97757"     # Claude terracotta
GOOD = "#4ade80"
TRACK = "#3a3a3a"


# ==========================================================================
# Data layer: read Claude Code's own files  (pure stdlib)
# ==========================================================================
def newest_session(cwd_filter=None):
    best, best_mtime = None, -1
    for path in glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl")):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if cwd_filter:
            slug = os.path.basename(os.path.dirname(path))
            want = cwd_filter.replace("/", "-").strip("-")
            if want not in slug:
                continue
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    if not best:
        return None, None
    return best, os.path.splitext(os.path.basename(best))[0]


def tail_lines(path, max_bytes=200_000):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def current_activity(jsonl_path):
    last_text = last_tool = ""
    last_ts = None
    for ln in tail_lines(jsonl_path):
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if obj.get("timestamp"):
            last_ts = obj["timestamp"]
        content = obj.get("content") or (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    last_text = block["text"].strip()
                elif block.get("type") == "tool_use":
                    name = block.get("name", "tool")
                    inp = block.get("input", {}) or {}
                    hint = (inp.get("description") or inp.get("command")
                            or inp.get("file_path") or inp.get("pattern") or "")
                    last_tool = f"{name}: {hint}".strip().strip(":").strip()
    headline = last_tool or "thinking / responding"
    return headline, last_text[:240], last_ts


def load_todos(session_id):
    if not os.path.isdir(TODOS_DIR):
        return []
    cands = glob.glob(os.path.join(TODOS_DIR, f"*{session_id}*.json"))
    if not cands:
        return []
    cands.sort(key=os.path.getmtime, reverse=True)
    try:
        with open(cands[0], "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    todos = data if isinstance(data, list) else data.get("todos", [])
    out = []
    for t in todos:
        if isinstance(t, dict):
            out.append({"content": t.get("content") or t.get("activeForm") or "task",
                        "status": t.get("status", "pending")})
    return out


# ---- ETA -----------------------------------------------------------------
def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass


def estimate_eta(session_id, done, total):
    now = time.time()
    state = _load_state()
    s = state.get(session_id)
    if s is None:
        s = {"start": now, "first_done": done}
        state[session_id] = s
        _save_state(state)
    elapsed = max(1.0, now - s.get("start", now))
    completed = max(0, done - s.get("first_done", 0))
    remaining = max(0, total - done)
    if total == 0:
        return "-", fmt_dur(elapsed)
    if remaining == 0:
        return "done", fmt_dur(elapsed)
    if completed <= 0:
        return "estimating", fmt_dur(elapsed)
    rate = completed / elapsed
    return "~" + fmt_dur(remaining / rate), fmt_dur(elapsed)


def fmt_dur(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"


def age_text(ts_iso):
    if not ts_iso:
        return ""
    try:
        t = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return f"{fmt_dur((datetime.now(timezone.utc) - t).total_seconds())} ago"
    except (ValueError, TypeError):
        return ""


# ==========================================================================
# UI layer: native Cocoa floating panel
# ==========================================================================
def make_label(text, x, y, w, h, size, color, bold=False, wrap=False):
    lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    lbl.setStringValue_(text)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    lbl.setTextColor_(hex_color(color))
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    lbl.setFont_(font)
    if wrap:
        lbl.setLineBreakMode_(NSLineBreakByWordWrapping)
        lbl.cell().setWraps_(True)
    return lbl


class Controller(NSObject):
    def initWithFilter_interval_(self, cwd_filter, interval):
        self = objc.super(Controller, self).init()
        if self is None:
            return None
        self.cwd_filter = cwd_filter
        self.interval = interval
        self._build_window()
        return self

    def _build_window(self):
        W, H = 320, 440
        style = NS_TITLED | NS_CLOSABLE | NS_MINIATURIZABLE
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(60, 200, W, H), style, NSBackingStoreBuffered, False)
        win.setTitle_("Claude Progress")
        win.setBackgroundColor_(hex_color(BG))
        win.setLevel_(NSFloatingWindowLevel)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary)
        win.setMovableByWindowBackground_(True)

        cv = win.contentView()

        def T(y):  # convert "distance from top" to AppKit bottom-left y
            return H - y

        self.title_lbl = make_label("● CLAUDE CODE", 14, T(34), W - 28, 20,
                                     13, ACCENT, bold=True)
        cv.addSubview_(self.title_lbl)
        self.session_lbl = make_label("locating session...", 14, T(54), W - 28, 16,
                                      10, MUTED)
        cv.addSubview_(self.session_lbl)

        cv.addSubview_(make_label("NOW", 14, T(84), W - 28, 14, 9, MUTED, bold=True))
        self.act_head = make_label("-", 14, T(106), W - 28, 18, 11, FG, bold=True)
        cv.addSubview_(self.act_head)
        self.act_detail = make_label("", 14, T(180), W - 28, 66, 10, MUTED, wrap=True)
        cv.addSubview_(self.act_detail)

        cv.addSubview_(make_label("GOAL PROGRESS", 14, T(206), W - 28, 14, 9,
                                  MUTED, bold=True))
        self.pct_lbl = make_label("-", 14, T(244), W - 28, 32, 26, FG, bold=True)
        cv.addSubview_(self.pct_lbl)

        # custom progress bar: track view + fill view
        self.track = NSView.alloc().initWithFrame_(NSMakeRect(14, T(262), W - 28, 12))
        self.track.setWantsLayer_(True)
        self.track.layer().setBackgroundColor_(hex_color(TRACK).CGColor())
        self.track.layer().setCornerRadius_(6.0)
        cv.addSubview_(self.track)
        self.fill = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 2, 12))
        self.fill.setWantsLayer_(True)
        self.fill.layer().setBackgroundColor_(hex_color(ACCENT).CGColor())
        self.fill.layer().setCornerRadius_(6.0)
        self.track.addSubview_(self.fill)

        self.count_lbl = make_label("", 14, T(284), W - 28, 16, 10, MUTED)
        cv.addSubview_(self.count_lbl)

        cv.addSubview_(make_label("ESTIMATE", 14, T(320), W - 28, 14, 9,
                                  MUTED, bold=True))
        self.eta_lbl = make_label("-", 14, T(352), 160, 22, 16, GOOD, bold=True)
        cv.addSubview_(self.eta_lbl)
        self.elapsed_lbl = make_label("", W - 130, T(350), 116, 18, 11, MUTED)
        cv.addSubview_(self.elapsed_lbl)
        cv.addSubview_(make_label("left            elapsed", 14, T(372), W - 28, 14,
                                  9, MUTED))

        win.makeKeyAndOrderFront_(None)
        self.window = win
        self.W = W

    def start(self):
        self.refresh_(None)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.interval, self, b"refresh:", None, True)

    def refresh_(self, _timer):
        path, sid = newest_session(self.cwd_filter)
        if not path:
            self.session_lbl.setStringValue_("no active session found")
            return
        slug = os.path.basename(os.path.dirname(path))
        head, detail, last_ts = current_activity(path)
        todos = load_todos(sid)
        done = sum(1 for t in todos if t["status"] == "completed")
        total = len(todos)
        frac = (done / total) if total else 0.0
        eta, elapsed = estimate_eta(sid, done, total)

        self.session_lbl.setStringValue_(f"{slug[:32]}  ·  {age_text(last_ts)}")
        self.act_head.setStringValue_(head[:80] or "-")
        self.act_detail.setStringValue_(detail)
        if total:
            self.pct_lbl.setStringValue_(f"{int(frac * 100)}%")
            self.count_lbl.setStringValue_(f"{done} of {total} tasks done")
        else:
            self.pct_lbl.setStringValue_("-")
            self.count_lbl.setStringValue_("no todo list in this session")

        track_w = self.W - 28
        fill_w = max(2, int(track_w * frac))
        self.fill.setFrame_(NSMakeRect(0, 0, fill_w, 12))
        color = GOOD if frac >= 1.0 else ACCENT
        self.fill.layer().setBackgroundColor_(hex_color(color).CGColor())

        self.eta_lbl.setStringValue_(eta)
        self.elapsed_lbl.setStringValue_(elapsed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", default=None, help="only track sessions under this path")
    ap.add_argument("--interval", type=float, default=2.0, help="poll seconds")
    args = ap.parse_args()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ctrl = Controller.alloc().initWithFilter_interval_(args.cwd, args.interval)
    ctrl.start()
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()
