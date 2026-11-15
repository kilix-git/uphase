#!/usr/bin/env python3
"""pzemlyzer - terminal power analyzer for the PZEM-004T.

Usage:  pzemlyzer   (or: python3 pzemlyzer.py)
Keys:   menus      - the letter in brackets, the number, or arrows (j/k) + Enter (l)
        any screen - q, h or Esc goes back (quits from the main menu)
Settings are saved in ~/.config/pzemlyzer/settings.json
"""
import calendar
import curses
import datetime
import json
import locale
import os
import threading
import time

import serial
import serial.tools.list_ports

import csvlog
import history
import pzem
import trend

POLL_INTERVAL = 1.0  # seconds between readings
SETTINGS_FILE = os.path.expanduser("~/.config/pzemlyzer/settings.json")
OLD_SETTINGS_FILE = os.path.expanduser("~/.config/analyzer/settings.json")  # before the rename
DEFAULTS = {"port": "/dev/ttyUSB0", "turns": 1, "cal_u_pct": 0.0, "cal_i_pct": 0.0, "cal_f_pct": 0.0,
            "log_interval_s": 60, "log_values": ["u", "i", "p", "pf", "f", "e"],
            "log_start_mode": "manual",  # manual | minute | time
            "log_start_time": "",         # "YYYY-MM-DD HH:MM:SS" when mode is "time"
            "log_end_mode": "manual",    # manual | time
            "log_end_time": "",
            "log_dir": "~/pzemlyzer-logs"}  # one file per run, named after its start time
TIME_FMT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_INTERVAL = 99 * 3600 + 59 * 60 + 59  # 99h 59m 59s
MAX_TURNS = 100
MAX_CAL_PCT = 20.0  # calibration correction limit, +/- percent
OLD_MIN_WINDOW = 600  # narrowest zoom on data only kept as minute summaries (see history.py)

ESC = 27
ENTER_KEYS = (curses.KEY_ENTER, 10, 13)
BACKSPACE_KEYS = (curses.KEY_BACKSPACE, 127, 8)


# ---------- settings ----------

def load_settings():
    # one-time move from the old location (the program was called "analyzer" before)
    if not os.path.exists(SETTINGS_FILE) and os.path.exists(OLD_SETTINGS_FILE):
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        os.replace(OLD_SETTINGS_FILE, SETTINGS_FILE)
        try:
            os.rmdir(os.path.dirname(OLD_SETTINGS_FILE))
        except OSError:
            pass
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as fh:
            s.update(json.load(fh))
    except (OSError, ValueError):
        pass  # missing or broken file -> defaults
    return s


def save_settings(s):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as fh:
        json.dump(s, fh, indent=2)


settings = load_settings()


def apply_calibration(v):
    """Correct voltage and current by the percentages from Setup > Calibration.
    Power and energy scale with both (P = U * I * PF); PF is unchanged."""
    ku = 1 + settings["cal_u_pct"] / 100
    ki = 1 + settings["cal_i_pct"] / 100
    v = dict(v)
    v["u"] *= ku
    v["i"] *= ki
    v["p"] *= ku * ki
    v["e"] *= ku * ki
    v["f"] *= 1 + settings["cal_f_pct"] / 100
    return v


def cal_text():
    parts = [f"{name} {settings[key]:+.2f}%" for name, key in
             (("U", "cal_u_pct"), ("I", "cal_i_pct"), ("f", "cal_f_pct")) if settings[key] != 0]
    return ", ".join(parts) or "none"


# ---------- logging run ----------

class LogRun:
    """State of the CSV logging: idle -> (armed ->) running -> idle.
    step() is called by the Monitor thread once per poll, with monitor.lock held."""

    def __init__(self):
        self.state = "idle"
        self.start_at = None   # unix time logging begins (armed) / began (running)
        self.end_at = None     # unix time logging stops by itself, or None
        self.csv = None
        self.path = None
        self.info = ""         # result of the last run, for the Logging page

    def arm(self, now):
        """Start or arm according to the settings. Returns an error text or None."""
        mode = settings["log_start_mode"]
        if mode == "time":
            start = parse_time(settings["log_start_time"])
            if start is None:
                return "No start time set (Logging > Start time)."
            start = start.timestamp()
            if start <= now:
                return f"The start time {settings['log_start_time']} has already passed."
        elif mode == "minute":
            start = (int(now) // 60 + 1) * 60
        else:
            start = now
        end = None
        if settings["log_end_mode"] == "time":
            end_dt = parse_time(settings["log_end_time"])
            if end_dt is None:
                return "No end time set (Logging > End time)."
            end = end_dt.timestamp()
            if end <= max(start, now):
                return f"The end time {settings['log_end_time']} is not after the start."
        folder = os.path.expanduser(settings["log_dir"])
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as ex:
            return f"Cannot create the folder {folder}: {ex.strerror}"
        if not os.access(folder, os.W_OK):
            return f"No permission to write into {folder}."
        self.start_at, self.end_at, self.info = start, end, ""
        self.state = "armed"
        if mode == "manual":
            return self._begin()
        return None

    def _begin(self):
        folder = os.path.expanduser(settings["log_dir"])
        name = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(self.start_at))
        path, n = os.path.join(folder, name + ".csv"), 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, f"{name}_{n}.csv")
        try:
            self.csv = csvlog.CsvLogger(path, settings["log_interval_s"], settings["log_values"],
                                        self.start_at, max_gap=3 * POLL_INTERVAL)
        except OSError as ex:
            self.state, self.info = "idle", f"could not create the file: {ex.strerror}"
            return self.info
        self.path, self.state = path, "running"
        return None

    def stop(self, now, why="stopped"):
        if self.state == "running":
            try:
                self.csv.close(now)
            except OSError:
                pass
            self.info = f"{why} at {time.strftime('%H:%M:%S', time.localtime(now))}, " \
                        f"{self.csv.lines} lines in {os.path.basename(self.path)}"
        elif self.state == "armed":
            self.info = "armed start cancelled"
        self.state, self.csv = "idle", None

    def step(self, now, values):
        if self.state == "armed" and now >= self.start_at:
            self._begin()
        if self.state != "running":
            return
        try:
            if values is not None:
                self.csv.add(now, values)
            else:
                self.csv.tick(now)
            if self.end_at is not None and now >= self.end_at:
                self.stop(self.end_at, why="finished")
        except OSError as ex:
            self.stop(now, why=f"ERROR ({ex.strerror}), stopped")

    def summary(self):
        if self.state == "armed":
            return "armed - starts " + time.strftime(TIME_FMT, time.localtime(self.start_at))
        if self.state == "running":
            end = "" if self.end_at is None else \
                ", ends " + time.strftime("%H:%M:%S", time.localtime(self.end_at))
            return f"running - {self.csv.lines} lines{end}"
        return self.info


log_run = LogRun()


# ---------- background reading ----------

class Monitor(threading.Thread):
    """Reads the PZEM every POLL_INTERVAL seconds for as long as the program runs
    and keeps the readings in `history` (see history.py), so the trend graphs cover
    the whole run."""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()  # held while talking to the serial port
        self.start_time = time.time()
        self.history = history.History(max_gap=3 * POLL_INTERVAL)  # good readings only
        self.latest = None            # values dict of the last reading, or None after an error
        self.status = "connecting..."
        self.last_ok = None           # unix time of the last good reading
        self.ser = None
        self.ser_port = None

    def _read_once(self):
        with self.lock:
            values = self._read_locked()
            log_run.step(time.time(), values)

    def _read_locked(self):
        """One reading; returns the values or None. Caller holds self.lock."""
        if True:
            port, turns = settings["port"], settings["turns"]
            try:
                if self.ser is not None and self.ser_port != port:
                    self.ser.close()
                    self.ser = None
                if self.ser is None:
                    self.ser, self.ser_port = pzem.open_port(port), port
                values = apply_calibration(pzem.read_values(self.ser, turns))
            except serial.SerialException:
                if self.ser is not None:
                    self.ser.close()
                self.ser = None
                self.latest, self.status = None, f"USB adapter not found on {port}"
                return None
            except IOError as ex:
                self.latest, self.status = None, str(ex)
                return None
            now = time.time()
            self.history.add(now, values)
            self.latest, self.status, self.last_ok = values, "OK", now
            return values

    def clear(self, new_turns=None, reset_energy=False):
        """Forget all readings and restart the graphs from now. Optionally change
        the CT turns at the same moment (so readings with old and new turns never
        mix) and/or zero the PZEM's energy counter. Returns a message for the user."""
        with self.lock:  # not in the middle of a reading
            if new_turns is not None:
                settings["turns"] = new_turns
                save_settings(settings)
            self.history = history.History(max_gap=3 * POLL_INTERVAL)
            self.start_time = time.time()
            if not reset_energy:
                return "Data cleared."
            err = self._reset_counter_locked()
            if err is None:
                return "Data cleared, energy counter in the PZEM reset to 0."
            return f"Data cleared, but the PZEM energy counter was NOT reset ({err})."

    def _reset_counter_locked(self):
        """Zero the PZEM's energy counter. Caller holds self.lock. Returns an error or None."""
        try:
            if self.ser is None:
                self.ser, self.ser_port = pzem.open_port(settings["port"]), settings["port"]
            pzem.reset_energy(self.ser)
            return None
        except IOError as ex:  # includes serial.SerialException
            return str(ex)

    def reset_counter(self):
        with self.lock:
            return self._reset_counter_locked()

    def run(self):
        next_poll = time.monotonic()
        while True:
            try:
                self._read_once()
            except Exception as ex:  # never let the reader thread die silently
                self.latest, self.status = None, f"unexpected error: {type(ex).__name__}: {ex}"
                with self.lock:
                    if self.ser is not None:
                        self.ser.close()
                    self.ser = None
            next_poll += POLL_INTERVAL
            time.sleep(max(0.0, next_poll - time.monotonic()))


monitor = Monitor()


# ---------- generic UI helpers ----------

def is_back(key):
    return key in (ord("q"), ord("Q"), ord("h"), ESC)


def nav(key):
    """Vim keys in lists: j = down, k = up, l = Enter (h = back is handled by is_back)."""
    return {ord("j"): curses.KEY_DOWN, ord("k"): curses.KEY_UP, ord("l"): 10}.get(key, key)


def draw_log_indicator(win):
    """'● LOG' at the top right: steady while logging, blinking (1s) while armed."""
    cols = win.getmaxyx()[1]
    if log_run.state == "idle":
        win.addstr(0, cols - 8, "       ")
        return
    dot = "●" if log_run.state == "running" or int(time.time()) % 2 == 0 else " "
    win.addstr(0, cols - 8, f"{dot} LOG ", curses.color_pair(2) | curses.A_BOLD)


def draw_title(win, title):
    win.erase()
    win.addstr(0, 2, title, curses.A_BOLD)
    draw_log_indicator(win)
    win.hline(1, 0, curses.ACS_HLINE, win.getmaxyx()[1])


_timeout = -1  # the getch timeout the current screen wants (-1 = wait for a key)


def set_timeout(stdscr, ms):
    global _timeout
    _timeout = ms
    stdscr.timeout(ms)


def get_key(stdscr, live=False):
    """Waits for a key, keeping the LOG indicator blinking meanwhile.
    live=True: also returns -1 once a second so the caller can redraw changing text."""
    stdscr.timeout(250)
    next_tick = time.monotonic() + 1.0
    try:
        while True:
            key = stdscr.getch()
            if key != -1:
                return key
            if live and time.monotonic() >= next_tick:
                return -1
            y, x = stdscr.getyx()
            draw_log_indicator(stdscr)
            stdscr.move(y, x)  # leave the text cursor where an editor put it
            stdscr.refresh()
    finally:
        stdscr.timeout(_timeout)


def menu(stdscr, title, items, back_hint="q/h = back", h_backs=True):
    """items: list of (hotkey, label) or (hotkey, label, value_function).
    Returns the index of the chosen item, or None for back/quit."""
    sel = 0
    while True:
        draw_title(stdscr, title)
        for n, item in enumerate(items):
            hotkey, label = item[0], item[1]
            attr = curses.A_REVERSE if n == sel else curses.A_NORMAL
            stdscr.addstr(3 + 2 * n, 4, f" {n + 1}. {label} ({hotkey}) ", attr)
            if len(item) > 2:
                stdscr.addstr(3 + 2 * n, 30, str(item[2]())[: stdscr.getmaxyx()[1] - 31], curses.A_BOLD)
        stdscr.addstr(4 + 2 * len(items), 4,
                      f"arrows/jk + Enter/l, 1-{len(items)}, or the letter;  {back_hint}", curses.A_DIM)
        stdscr.refresh()

        key = nav(get_key(stdscr, live=True))
        if key == -1:
            continue  # redraw: values shown in the menu may have changed
        if key == ord("h") and not h_backs:
            continue  # main menu: h must not quit the program by accident
        if is_back(key):
            return None
        if key == curses.KEY_UP:
            sel = (sel - 1) % len(items)
        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % len(items)
        elif key in ENTER_KEYS:
            return sel
        elif ord("1") <= key < ord("1") + len(items):
            return key - ord("1")
        else:
            for n, item in enumerate(items):
                if key in (ord(item[0]), ord(item[0].upper())):
                    return n


def edit_line(stdscr, y, x, initial, width=30, allowed=None):
    """Minimal one-line text editor. Enter returns the text, Esc returns None.
    allowed: optional string of permitted characters."""
    text = initial
    curses.curs_set(1)
    try:
        while True:
            stdscr.addstr(y, x, "[" + " " * width + "]")
            stdscr.addstr(y, x + 1, text[-width:], curses.A_BOLD)
            stdscr.move(y, x + 1 + min(len(text), width))
            stdscr.refresh()
            key = get_key(stdscr)
            if key == ESC:
                return None
            if key in ENTER_KEYS:
                return text.strip()
            if key in BACKSPACE_KEYS:
                text = text[:-1]
            elif 32 <= key < 127 and (allowed is None or chr(key) in allowed):
                text += chr(key)
    finally:
        curses.curs_set(0)


def message(stdscr, y, text, bold=False):
    stdscr.move(y, 0)
    stdscr.clrtoeol()
    stdscr.addstr(y, 4, text[: stdscr.getmaxyx()[1] - 5], curses.A_BOLD if bold else curses.A_NORMAL)


def wait_key(stdscr, y):
    stdscr.addstr(y, 4, "Press any key to go back.", curses.A_DIM)
    stdscr.refresh()
    get_key(stdscr)


# ---------- Measurement ----------

# (values key, hotkey, label, unit, format, meter resolution = smallest y-axis span of the graph)
QUANTITIES = [
    ("u", "v", "Voltage", "V", "{:.1f}", 0.1),
    ("i", "c", "Current", "A", "{:.3f}", 0.001),
    ("p", "a", "Active power", "W", "{:.1f}", 0.1),
    ("pf", "p", "Power factor", "", "{:.2f}", 0.01),
    ("f", "f", "Frequency", "Hz", "{:.1f}", 0.1),
    ("e", "e", "Energy", "Wh", "{:.0f}", 1.0),
]
# energy screen: bar width per interval, chosen automatically so all bars fit
ENERGY_INTERVALS = [(60, "1min"), (300, "5min"), (900, "15min"), (1800, "30min"),
                    (3600, "1h"), (4 * 3600, "4h"), (24 * 3600, "1d")]


def status_lines(stdscr, y):
    message(stdscr, y, f"Status: {monitor.status}", bold=monitor.status != "OK")
    if monitor.last_ok:
        stdscr.addstr(y + 1, 4, "Last good reading: " + time.strftime("%H:%M:%S", time.localtime(monitor.last_ok)),
                      curses.A_DIM)


def measurement(stdscr):
    sel = 0
    set_timeout(stdscr, 200)  # redraw 5x per second so the values stay live
    try:
        while True:
            values = monitor.latest
            draw_title(stdscr, "Measurement")
            for n, (k, hotkey, label, unit, fmt, _) in enumerate(QUANTITIES):
                attr = curses.A_REVERSE if n == sel else curses.A_NORMAL
                stdscr.addstr(3 + n, 4, f" {n + 1}. {label + ' (' + hotkey + ')':<18}", attr)
                text = fmt.format(values[k]) if values else "---"
                stdscr.addstr(f"{text:>10}", curses.A_BOLD)
                stdscr.addstr(unit)
            y = 4 + len(QUANTITIES)
            turns = settings["turns"]
            if turns > 1:
                stdscr.addstr(y, 4, f"CT turns: {turns} (I, P, E divided by {turns})", curses.A_DIM)
            status_lines(stdscr, y + 2)
            stdscr.addstr(y + 5, 4, "letter, 1-6 or arrows/jk + Enter/l = trend graph", curses.A_DIM)
            stdscr.addstr(y + 6, 4, "r = clear data;  q/h = back", curses.A_DIM)
            stdscr.refresh()

            key = nav(stdscr.getch())
            if is_back(key):
                return
            choice = None
            if key in (ord("r"), ord("R")):
                confirm_clear(stdscr)
            elif key == curses.KEY_UP:
                sel = (sel - 1) % len(QUANTITIES)
            elif key == curses.KEY_DOWN:
                sel = (sel + 1) % len(QUANTITIES)
            elif key in ENTER_KEYS:
                choice = sel
            elif ord("1") <= key < ord("1") + len(QUANTITIES):
                choice = key - ord("1")
            else:
                for n, q in enumerate(QUANTITIES):
                    if key in (ord(q[1]), ord(q[1].upper())):
                        choice = n
            if choice is not None:
                sel = choice
                trend_screen(stdscr, QUANTITIES[choice])
    finally:
        set_timeout(stdscr, -1)


def confirm_clear(stdscr):
    """Asks on the bottom line; clears the history on Enter. Returns True if cleared."""
    rows_scr = stdscr.getmaxyx()[0]
    message(stdscr, rows_scr - 1, "Clear graph data? (energy counter kept)  ENTER = yes, other key = no",
            bold=True)
    stdscr.refresh()
    key = get_key(stdscr)
    if key not in ENTER_KEYS:
        return False
    text = monitor.clear()
    message(stdscr, rows_scr - 1, text, bold="NOT" in text)
    stdscr.refresh()
    time.sleep(1.0 if "NOT" not in text else 3.0)
    return True


def confirm_zero_counter(stdscr):
    """Energy screen: zero the PZEM's own energy counter (graphs are kept)."""
    rows_scr = stdscr.getmaxyx()[0]
    message(stdscr, rows_scr - 1, "Zero the PZEM energy counter? (graphs kept)  ENTER = yes, other key = no",
            bold=True)
    stdscr.refresh()
    if get_key(stdscr) not in ENTER_KEYS:
        return
    err = monitor.reset_counter()
    text = "PZEM energy counter reset to 0." if err is None else f"Counter NOT reset: {err}"
    message(stdscr, rows_scr - 1, text, bold=err is not None)
    stdscr.refresh()
    time.sleep(1.0 if err is None else 3.0)


def nice_range(lo, hi, min_span, upper=None):
    """Y-axis limits: the measured min..max fill the graph, with 2% headroom at the top
    and bottom. min_span (the meter's resolution) only matters when the values are flat."""
    mid, span = (lo + hi) / 2, max(hi - lo, min_span) * 1.04
    v_lo, v_hi = mid - span / 2, mid + span / 2
    if lo >= 0 > v_lo:  # never show a negative axis for values that cannot be negative
        v_lo, v_hi = 0.0, span
    if upper is not None and hi <= upper < v_hi:  # e.g. power factor never above 1
        v_lo, v_hi = max(upper - span, 0.0), upper
    return v_lo, v_hi


class Zoom:
    """Time window of the trend graphs, shared by all of them.

    view: None = the whole run, else (start, end) in unix time. follow = the view is at
    the right edge and moves along with new data. sel = the highlighted area being chosen
    (before Enter). hint = the area you just zoomed out of, highlighted until the next key.
    stack = earlier views, so zooming out returns exactly to where you were."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.view, self.follow, self.sel, self.hint, self.stack = None, False, None, None, []

    @staticmethod
    def full():
        t0 = monitor.start_time
        return t0, max(time.time(), t0 + 60)  # the first minute fills from the left

    def window(self):
        f0, f1 = self.full()
        if self.view is None:
            return f0, f1
        v0, v1 = self.view
        if self.follow:
            w = v1 - v0
            return max(f0, f1 - w), max(f0, f1 - w) + w
        return v0, v1

    def factor(self):
        f0, f1 = self.full()
        w0, w1 = self.window()
        return (f1 - f0) / (w1 - w0)

    def _clamp(self, a, b, lo, hi):
        """Shift (a, b) to lie inside (lo, hi) without changing its width (if it fits)."""
        w = min(b - a, hi - lo)
        a = min(max(a, lo), hi - w)
        return a, a + w

    def zoom_in(self, min_width):
        w0, w1 = self.window()
        a, b = self.sel or (w0, w1)
        c, w = (a + b) / 2, max((b - a) / 2, min_width)
        if w >= (w1 - w0) * 0.999:
            return  # already at maximum zoom
        self.sel, self.hint = self._clamp(c - w / 2, c + w / 2, w0, w1), None

    def zoom_out(self):
        w0, w1 = self.window()
        if self.sel is not None:  # while choosing: grow the selection back, then drop it
            a, b = self.sel
            c, w = (a + b) / 2, (b - a) * 2
            self.sel = None if w >= (w1 - w0) * 0.999 else self._clamp(c - w / 2, c + w / 2, w0, w1)
            return
        if self.view is None:
            self.hint = None  # fully zoomed out: '-' just clears the highlight
            return
        self.hint = (w0, w1)
        if self.stack:
            self.view, self.follow = self.stack.pop()
        else:
            f0, f1 = self.full()
            c, w = (w0 + w1) / 2, (w1 - w0) * 2
            if w >= (f1 - f0) * 0.999:
                self.view, self.follow = None, False
            else:
                self.view = self._clamp(c - w / 2, c + w / 2, f0, f1)
                self.follow = self.view[1] >= f1 - 0.5
        if self.view is None:
            self.stack = []

    def confirm(self):
        if self.sel is None:
            return
        f0, f1 = self.full()
        self.stack.append((self.view, self.follow))
        self.view, self.sel, self.hint = self.sel, None, None
        self.follow = self.view[1] >= f1 - 0.5

    def limit_old(self, raw_from):
        """Data before raw_from is only kept as one point per minute. A view or
        selection that reaches into it is widened to at least OLD_MIN_WINDOW, so the
        graph never pretends to show detail that is no longer there."""
        if raw_from is None:
            return
        f0, f1 = self.full()
        if self.view is not None:
            w0, w1 = self.window()
            if w0 < raw_from and w1 - w0 < OLD_MIN_WINDOW:
                c = (w0 + w1) / 2
                self.view = self._clamp(c - OLD_MIN_WINDOW / 2, c + OLD_MIN_WINDOW / 2, f0, f1)
                self.follow = self.view[1] >= f1 - 0.5
        if self.sel is not None:
            a, b = self.sel
            if a < raw_from and b - a < OLD_MIN_WINDOW:
                w0, w1 = self.window()
                c = (a + b) / 2
                self.sel = self._clamp(c - OLD_MIN_WINDOW / 2, c + OLD_MIN_WINDOW / 2, w0, w1)
                if self.sel[1] - self.sel[0] >= (w1 - w0) * 0.999:
                    self.sel = None  # the selection would be the whole window: nothing to zoom

    def move(self, fraction):
        """Move the selection (inside the visible window) or pan the view (inside the run)
        by fraction of its width; negative = towards older data."""
        self.hint = None
        if self.sel is not None:
            w0, w1 = self.window()
            a, b = self.sel
            d = (b - a) * fraction
            self.sel = self._clamp(a + d, b + d, w0, w1)
        elif self.view is not None:
            f0, f1 = self.full()
            a, b = self.window()
            d = (b - a) * fraction
            self.view = self._clamp(a + d, b + d, f0, f1)
            self.follow = self.view[1] >= f1 - 0.5


zoom = Zoom()


def plot_geometry(stdscr):
    """(top, left, plot_rows, plot_cols, label_w) of the graph area."""
    rows_scr, cols_scr = stdscr.getmaxyx()
    label_w = 8
    top, left = 4, 2 + label_w
    return top, left, rows_scr - top - 6, cols_scr - left - 3, label_w


def trend_screen(stdscr, quantity):
    k, _, label, unit, fmt, min_span = quantity
    shown = None  # (number of samples, screen size) last drawn - redraw only on change
    while True:
        rows_scr, cols_scr = stdscr.getmaxyx()
        n_hist = monitor.history.count
        if shown != (n_hist, rows_scr, cols_scr, monitor.status):
            shown = (n_hist, rows_scr, cols_scr, monitor.status)
            if k == "e":
                draw_energy(stdscr)
            else:
                draw_trend(stdscr, k, label, unit, fmt, min_span)
        else:
            draw_log_indicator(stdscr)  # keep it blinking between data updates
            stdscr.refresh()
        key = stdscr.getch()
        if key == -1:
            continue
        if k != "e" and handle_zoom_key(stdscr, key):
            shown = None
            continue
        if is_back(key):
            return
        if key in (ord("r"), ord("R")):
            if confirm_clear(stdscr):
                zoom.reset()
            shown = None
        elif k == "e" and key in (ord("z"), ord("Z")):
            confirm_zero_counter(stdscr)
            shown = None
        elif key == curses.KEY_RESIZE:
            shown = None


def handle_zoom_key(stdscr, key):
    """Zoom and pan keys of the trend graphs. Returns True if the key was used."""
    if key in (ESC, ord("q"), ord("Q")) and zoom.sel is not None:
        zoom.sel = None  # first Esc / q only cancels the selection
        return True
    if key in (ord("="), ord("+")):
        plot_cols = plot_geometry(stdscr)[3]
        min_width = max(plot_cols / 4, 5) * POLL_INTERVAL  # max zoom: 1 reading per 4 columns
        raw_from = monitor.history.raw_from
        if raw_from is not None and (zoom.sel or zoom.window())[0] < raw_from:
            min_width = max(min_width, OLD_MIN_WINDOW)  # minute summaries only
        zoom.zoom_in(min_width=min_width)
    elif key == ord("-"):
        zoom.zoom_out()
    elif key in ENTER_KEYS:
        zoom.confirm()
    elif key in (curses.KEY_LEFT, ord("h")):
        zoom.move(-1 / 8)
    elif key in (curses.KEY_RIGHT, ord("l")):
        zoom.move(1 / 8)
    elif key in (curses.KEY_SLEFT, ord("H"), curses.KEY_PPAGE):
        zoom.move(-1)
    elif key in (curses.KEY_SRIGHT, ord("L"), curses.KEY_NPAGE):
        zoom.move(1)
    else:
        if zoom.hint is not None:
            zoom.hint = None
        return False
    return True


def draw_box(stdscr, top, left, rows, cols):
    """Frame around a plot area of rows x cols starting at (top + 1, left + 1)."""
    stdscr.attron(curses.A_DIM)
    stdscr.addch(top, left, curses.ACS_ULCORNER)
    stdscr.hline(top, left + 1, curses.ACS_HLINE, cols)
    stdscr.addch(top, left + cols + 1, curses.ACS_URCORNER)
    stdscr.vline(top + 1, left, curses.ACS_VLINE, rows)
    stdscr.vline(top + 1, left + cols + 1, curses.ACS_VLINE, rows)
    stdscr.addch(top + rows + 1, left, curses.ACS_LLCORNER)
    stdscr.hline(top + rows + 1, left + 1, curses.ACS_HLINE, cols)
    stdscr.addch(top + rows + 1, left + cols + 1, curses.ACS_LRCORNER)
    stdscr.attroff(curses.A_DIM)


def fmt_wh(v):
    return f"{v:.0f}" if v >= 100 else f"{v:.1f}" if v >= 10 else f"{v:.2f}" if v >= 1 else f"{v:.3f}"


def draw_energy(stdscr):
    """Bar chart: energy used in each clock-aligned interval, from integrated active power."""
    rows_scr, cols_scr = stdscr.getmaxyx()
    draw_title(stdscr, "Measurement > Energy")
    per_minute = monitor.history.energy_per_minute()  # re-binned to the bar interval below
    total = sum(per_minute.values())

    values = monitor.latest
    stdscr.addstr(2, 4, "This run ")
    stdscr.addstr(f"{fmt_wh(total)}Wh", curses.A_BOLD)
    stdscr.addstr("    PZEM counter " + (f"{values['e']:.0f}Wh" if values else "---"))

    label_w, bar_w, gap = 8, 2, 1
    top, left = 4, 2 + label_w
    plot_rows = rows_scr - top - 6
    plot_cols = cols_scr - left - 3
    n_bars = plot_cols // (bar_w + gap)
    if plot_rows < 3 or n_bars < 3:
        message(stdscr, top, "Window too small for the graph.", bold=True)
    else:
        now, t_start = time.time(), monitor.start_time
        # smallest interval for which the whole run fits on the screen
        interval, iv_name = ENERGY_INTERVALS[-1]
        for sec, name in ENERGY_INTERVALS:
            if int(now // sec) - int(t_start // sec) + 1 <= n_bars:
                interval, iv_name = sec, name
                break
        k0, k1 = int(t_start // interval), int(now // interval)
        k0 = max(k0, k1 - n_bars + 1)  # only if even one day per bar is too short: show the latest days
        sums = {}
        for minute_k, wh in per_minute.items():
            k = minute_k * history.MINUTE // interval
            sums[k] = sums.get(k, 0.0) + wh
        vals = [sums.get(k) for k in range(k0, k1 + 1)]
        v_max = max([v for v in vals if v is not None] + [0.0])
        v_max = max(v_max * 1.1, 0.01)

        draw_box(stdscr, top, left, plot_rows, plot_cols)
        lines = trend.bars(vals, plot_rows, v_max, bar_w, gap)
        for n, line in enumerate(lines):
            stdscr.addstr(top + 1 + n, left + 1, line[:plot_cols], curses.color_pair(1))
        if len(vals) > 0 and vals[-1] is not None:  # interval in progress: drawn dim
            x = left + 1 + (len(vals) - 1) * (bar_w + gap)
            for n, line in enumerate(lines):
                stdscr.addstr(top + 1 + n, x, line[(len(vals) - 1) * (bar_w + gap):][:bar_w], curses.A_DIM)
        for row, v in ((0, v_max), (plot_rows // 2, v_max / 2), (plot_rows - 1, 0.0)):
            stdscr.addstr(top + 1 + row, 1, f"{fmt_wh(v):>{label_w}}"[-label_w:], curses.A_DIM)
        stdscr.addstr(top, 1, "Wh", curses.A_DIM)
        t_fmt = lambda t: time.strftime("%H:%M", time.localtime(t))
        stdscr.addstr(top + plot_rows + 2, left, t_fmt(k0 * interval), curses.A_DIM)
        stdscr.addstr(top + plot_rows + 2, left + 8, f"one bar = {iv_name}, last bar still running",
                      curses.A_DIM)
        if vals and vals[-1] is not None:
            avg_w = vals[-1] * 3600 / max(now - max(k1 * interval, t_start), 1)
            stdscr.addstr(3, 4, f"Current {iv_name} interval: {fmt_wh(vals[-1])}Wh so far"
                                f" (avg {avg_w:.1f}W)", curses.A_DIM)

    message(stdscr, rows_scr - 2, f"Status: {monitor.status}", bold=monitor.status != "OK")
    stdscr.addstr(rows_scr - 1, 4, "r = clear data;  z = zero PZEM counter;  q/h/Esc = back", curses.A_DIM)
    stdscr.refresh()


def draw_trend(stdscr, k, label, unit, fmt, min_span):
    rows_scr, cols_scr = stdscr.getmaxyx()
    raw_from = monitor.history.raw_from
    zoom.limit_old(raw_from)  # also after panning, and when raw data ages into summaries
    t_start, t_end = zoom.window()
    plot_cols = plot_geometry(stdscr)[3]
    dot_seconds = (t_end - t_start) / max(2 * plot_cols, 1)
    samples = monitor.history.items(k, t_start, t_end, dot_seconds)
    minute_res = raw_from is not None and t_start < raw_from and dot_seconds < history.MINUTE
    zoomed = zoom.view is not None
    draw_title(stdscr, f"Measurement > {label}")

    values = monitor.latest
    now_text = (fmt.format(values[k]) if values else "---") + unit
    stdscr.addstr(2, 4, "Now ")
    stdscr.addstr(now_text, curses.A_BOLD)
    if samples:
        lo, hi = min(s[2] for s in samples), max(s[3] for s in samples)
        avg = sum(s[4] for s in samples) / sum(s[5] for s in samples)
        stdscr.addstr(f"    min {fmt.format(lo)}   max {fmt.format(hi)}   avg {fmt.format(avg)}")
        if zoomed:
            stdscr.addstr("  (in view)", curses.A_DIM)

    t_fmt = lambda t: time.strftime("%H:%M:%S", time.localtime(t))
    if zoom.sel is not None:
        a, b = zoom.sel
        info = f"selection {t_fmt(a)} - {t_fmt(b)} ({trend.fmt_elapsed(b - a)})   Enter = zoom in, Esc = cancel"
        stdscr.addstr(3, 4, info[: cols_scr - 5], curses.color_pair(4))
    elif zoomed:
        info = f"zoom {zoom.factor():.0f}x   {t_fmt(t_start)} - {t_fmt(t_end)} ({trend.fmt_elapsed(t_end - t_start)})"
        info += "   following" if zoom.follow else ""
        info += "   1min resolution" if minute_res else ""
        stdscr.addstr(3, 4, info[: cols_scr - 5], curses.A_BOLD)

    top, left, plot_rows, plot_cols, label_w = plot_geometry(stdscr)
    if plot_rows < 3 or plot_cols < 10:
        message(stdscr, top, "Window too small for the graph.", bold=True)
    else:
        draw_box(stdscr, top, left, plot_rows, plot_cols)
        marks = trend.time_grid(t_start - monitor.start_time, t_end - t_start, plot_cols)

        # highlighted columns: the selection being chosen, or the area just zoomed out of
        hl = zoom.sel or zoom.hint
        hl_cols = range(0)
        if hl is not None:
            c0 = int((hl[0] - t_start) / (t_end - t_start) * plot_cols)
            c1 = int((hl[1] - t_start) / (t_end - t_start) * plot_cols + 0.999)
            hl_cols = range(max(c0, 0), min(c1, plot_cols))

        if samples:
            v_lo, v_hi = nice_range(lo, hi, min_span, upper=1.0 if k == "pf" else None)
            lines, env_lines = trend.trend(samples, plot_cols, plot_rows, t_start, t_end, v_lo, v_hi,
                                           max_gap=3 * POLL_INTERVAL)
            # dotted reference lines: max and min (sparse), halfway between them (denser),
            # plus a quarter line above and below the middle if there is room for them
            mid = (hi + lo) / 2
            q_hi, q_lo = lo + 0.75 * (hi - lo), lo + 0.25 * (hi - lo)
            to_row = lambda v: trend.value_to_dot_y(v, plot_rows, v_lo, v_hi) // 4
            label_rows = [to_row(v) for v in (hi, q_hi, mid, q_lo, lo)]
            roomy = all(b - a >= 2 for a, b in zip(label_rows, label_rows[1:]))  # a free row between labels
            levels = [(hi, 4), (mid, 2), (lo, 4)] + ([(q_hi, 4), (q_lo, 4)] if roomy else [])
            g_lines, used = trend.guides(plot_cols, plot_rows, v_lo, v_hi, levels,
                                         [x for _, x, _, _ in marks])
            r_max, r_mid, r_min = used[:3]
            labelled = [(r_max, hi), (r_min, lo)] + (list(zip(used[3:], (q_hi, q_lo))) if roomy else [])
        else:
            empty = [" " * plot_cols] * plot_rows
            lines = env_lines = empty
            g_lines, _ = trend.guides(plot_cols, plot_rows, 0, 1, [], [x for _, x, _, _ in marks])
        # per cell: average line (bright) > min-max envelope (faint) > reference lines (dim)
        green, green_hl, plain_hl = curses.color_pair(1), curses.color_pair(3), curses.color_pair(4)
        for n, (line, e_line, g_line) in enumerate(zip(lines, env_lines, g_lines)):
            y = top + 1 + n
            for x, (ch, e, g) in enumerate(zip(line, e_line, g_line)):
                h = x in hl_cols
                if ch != " ":
                    stdscr.addstr(y, left + 1 + x, ch, (green_hl if h else green) | curses.A_BOLD)
                elif e != " ":
                    stdscr.addstr(y, left + 1 + x, e, (green_hl if h else green | curses.A_DIM))
                elif g != " " or h:
                    stdscr.addstr(y, left + 1 + x, g, plain_hl if h else curses.A_DIM)
        if samples:
            # labels on the left at the height of each line; the middle wins a shared row
            for row, v in labelled + [(r_mid, mid)]:
                stdscr.addstr(top + 1 + row, 1, f"{fmt.format(v):>{label_w}}"[-label_w:], curses.A_DIM)
        else:
            stdscr.addstr(top + plot_rows // 2, left + 3, "no readings in this time window", curses.A_DIM)

        y_lab = top + plot_rows + 2
        stdscr.addstr(y_lab, left, t_fmt(t_start), curses.A_DIM)
        right_lab = left + plot_cols + 2 - 8
        stdscr.addstr(y_lab, right_lab, t_fmt(t_end), curses.A_DIM)
        # time since start under each vertical line, where it does not touch the end labels
        for _, _, col, text in marks:
            x = left + 1 + col
            stdscr.addch(top + plot_rows + 1, x, curses.ACS_BTEE, curses.A_DIM)
            lx = x - len(text) // 2
            if lx > left + 8 and lx + len(text) < right_lab - 1:
                stdscr.addstr(y_lab, lx, text, curses.A_DIM)

    message(stdscr, rows_scr - 2, f"Status: {monitor.status}", bold=monitor.status != "OK")
    stdscr.addstr(rows_scr - 1, 4, "= / - = zoom in/out  arrows/hl = move  r = clear  q/Esc = back"[: cols_scr - 5],
                  curses.A_DIM)
    stdscr.refresh()


# ---------- Setup ----------

def test_port(port):
    """Try one reading. Returns (ok, text)."""
    try:
        with monitor.lock, pzem.open_port(port) as ser:
            v = pzem.read_values(ser)
        return True, f"PZEM responds: {v['u']:.1f}V, {v['f']:.1f}Hz"
    except serial.SerialException as ex:
        return False, f"cannot open port: {ex}"
    except IOError as ex:
        return False, str(ex)


def pick_port(stdscr, ports, sel):
    """Draws the port list and waits for a choice.
    Returns (row, y_below_list), or (None, None) for back. Row len(ports) = custom."""
    devices = [p.device for p in ports]
    width = stdscr.getmaxyx()[1]
    while True:
        draw_title(stdscr, "Setup > Device port")
        stdscr.addstr(3, 4, "Serial ports found on this computer:")
        y = 4
        for n, p in enumerate(ports):
            desc = "" if p.description in ("n/a", p.device) else p.description.split(" - ")[0]
            mark = "*" if p.device == settings["port"] else " "
            attr = curses.A_REVERSE if n == sel else curses.A_NORMAL
            stdscr.addstr(y, 4, f"{mark}{n + 1}. {p.device:<16} {desc} "[: width - 5], attr)
            y += 1
        if not ports:
            stdscr.addstr(y, 6, "(none - is the USB adapter plugged in?)", curses.A_DIM)
            y += 1
        if settings["port"] not in devices:
            stdscr.addstr(y, 4, f"*   current: {settings['port']} (not found)"[: width - 5], curses.A_DIM)
            y += 1
        attr = curses.A_REVERSE if sel == len(ports) else curses.A_NORMAL
        stdscr.addstr(y + 1, 4, " 0. Custom - type the port name ", attr)
        stdscr.addstr(y + 3, 4, "number or arrows/jk + Enter/l;  * = current;  q/h = back", curses.A_DIM)
        stdscr.refresh()

        key = nav(get_key(stdscr))
        if is_back(key):
            return None, None
        if key == curses.KEY_UP:
            sel = (sel - 1) % (len(ports) + 1)
        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % (len(ports) + 1)
        elif key in ENTER_KEYS:
            return sel, y + 5
        elif key == ord("0"):
            return len(ports), y + 5
        elif ord("1") <= key < ord("1") + len(ports):
            return key - ord("1"), y + 5


def setup_port(stdscr):
    ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)[:9]
    devices = [p.device for p in ports]
    sel = devices.index(settings["port"]) if settings["port"] in devices else len(devices)
    while True:
        sel, msg_y = pick_port(stdscr, ports, sel)
        if sel is None:
            return
        if sel < len(ports):
            new = devices[sel]
        else:
            stdscr.addstr(msg_y, 4, "Port:")
            stdscr.addstr(msg_y + 1, 4, "Enter = test, Esc = cancel", curses.A_DIM)
            new = edit_line(stdscr, msg_y, 10, settings["port"])
            if not new:  # Esc or empty -> back to the list
                continue
            message(stdscr, msg_y + 1, "")
            msg_y += 2

        message(stdscr, msg_y, f"Testing {new} ...")
        stdscr.refresh()
        ok, text = test_port(new)
        message(stdscr, msg_y, text, bold=not ok)
        if ok:
            settings["port"] = new
            save_settings(settings)
            message(stdscr, msg_y + 1, f"Saved {new}.")
            wait_key(stdscr, msg_y + 3)
            return
        stdscr.addstr(msg_y + 2, 4, "press ENTER to accept or any other key to edit")
        stdscr.refresh()
        if get_key(stdscr) in ENTER_KEYS:
            settings["port"] = new
            save_settings(settings)
            return
        # any other key: back to the same list, same item highlighted


def setup_turns(stdscr):
    while True:
        draw_title(stdscr, "Setup > CT turns")
        stdscr.addstr(3, 4, "How many times the conductor passes through the CT hole.")
        stdscr.addstr(4, 4, "A straight wire is 1. Each wrap around the core adds 1 more.")
        stdscr.addstr(5, 4, "Current, power and energy are divided by this number.")
        stdscr.addstr(6, 4, "Changing it clears all measured data (graphs start from zero).", curses.A_BOLD)
        stdscr.addstr(8, 4, "Enter = save, Esc = back to Setup", curses.A_DIM)
        stdscr.addstr(10, 4, "Turns:")

        new = edit_line(stdscr, 10, 11, str(settings["turns"]), width=5, allowed="0123456789")
        if new is None:
            return
        if not new or not 1 <= int(new) <= MAX_TURNS:
            message(stdscr, 12, f"Must be a whole number from 1 to {MAX_TURNS} - not saved.", bold=True)
        elif int(new) == settings["turns"]:
            message(stdscr, 12, f"Unchanged: {new} turn(s). Data kept.")
        else:
            if monitor.history.count:
                message(stdscr, 12, f"Change {settings['turns']} -> {int(new)} turn(s) and CLEAR ALL DATA?",
                        bold=True)
                message(stdscr, 13, "ENTER = yes, any other key = cancel")
                stdscr.refresh()
                if get_key(stdscr) not in ENTER_KEYS:
                    continue  # cancelled: back to this screen, nothing changed
                message(stdscr, 13, "")
            text = monitor.clear(new_turns=int(new))
            message(stdscr, 12, f"Saved: {settings['turns']} turn(s).")
            message(stdscr, 13, text, bold="NOT" in text)
        wait_key(stdscr, 15)
        return


def setup_calibration(stdscr):
    items = [("v", "Voltage", "cal_u_pct"), ("c", "Current", "cal_i_pct"), ("f", "Frequency", "cal_f_pct")]
    sel = 0
    while True:
        draw_title(stdscr, "Setup > Calibration")
        text = [
            "Corrects the PZEM's voltage, current and frequency by a fixed percentage:",
            "   -0.43  ->  shown value = 99.57% of what the PZEM measures",
            "   +1.2   ->  shown value = 101.2% of what the PZEM measures",
            "    0     ->  no correction",
            f"Allowed range: -{MAX_CAL_PCT:g}% to +{MAX_CAL_PCT:g}%.",
            "Active power and energy get both the U and I corrections (P = U x I x PF).",
            "Power factor is not changed.",
            "Already recorded graph data is not recalculated.",
        ]
        for n, line in enumerate(text):
            stdscr.addstr(3 + n, 4, line)
        y0 = 4 + len(text)
        for n, (hotkey, label, key) in enumerate(items):
            attr = curses.A_REVERSE if n == sel else curses.A_NORMAL
            stdscr.addstr(y0 + n, 4, f" {n + 1}. {label} ({hotkey}) ", attr)
            stdscr.addstr(y0 + n, 24, f"{settings[key]:+.2f}%", curses.A_BOLD)
        stdscr.addstr(y0 + len(items) + 1, 4, f"letter, 1-{len(items)} or arrows/jk + Enter/l = edit;  q/h = back",
                      curses.A_DIM)
        stdscr.refresh()

        k = nav(get_key(stdscr))
        if is_back(k):
            return
        choice = None
        if k == curses.KEY_UP:
            sel = (sel - 1) % len(items)
        elif k == curses.KEY_DOWN:
            sel = (sel + 1) % len(items)
        elif k in ENTER_KEYS:
            choice = sel
        elif ord("1") <= k < ord("1") + len(items):
            choice = k - ord("1")
        else:
            for n, item in enumerate(items):
                if k in (ord(item[0]), ord(item[0].upper())):
                    choice = n
        if choice is None:
            continue
        sel = choice
        _, label, key = items[choice]
        y = y0 + len(items) + 3
        stdscr.addstr(y, 4, f"{label} correction in %:")
        stdscr.addstr(y + 1, 4, f"Enter = save, Esc = cancel;  allowed -{MAX_CAL_PCT:g} to +{MAX_CAL_PCT:g}",
                      curses.A_DIM)
        new = edit_line(stdscr, y, 30, f"{settings[key]:g}", width=8, allowed="+-.,0123456789")
        if new is None:
            continue
        try:
            pct = float(new.replace(",", ".") or "0")
        except ValueError:
            pct = None
        if pct is None or not -MAX_CAL_PCT <= pct <= MAX_CAL_PCT:
            message(stdscr, y + 1, f"Not a number from -{MAX_CAL_PCT:g} to +{MAX_CAL_PCT:g} - not saved.", bold=True)
            wait_key(stdscr, y + 3)
            continue
        settings[key] = pct
        save_settings(settings)


def setup_clear_all(stdscr):
    draw_title(stdscr, "Setup > Clear all data")
    stdscr.addstr(3, 4, "This will clear:")
    stdscr.addstr(4, 6, "- all trend graphs (voltage, current, power, ...)")
    stdscr.addstr(5, 6, "- the energy counter inside the PZEM power meter (back to 0Wh)")
    stdscr.addstr(7, 4, "The energy counter cannot be restored afterwards.", curses.A_BOLD)
    stdscr.addstr(9, 4, "ENTER = clear everything, any other key = cancel")
    stdscr.refresh()
    if get_key(stdscr) not in ENTER_KEYS:
        return
    text = monitor.clear(reset_energy=True)
    message(stdscr, 11, text, bold="NOT" in text)
    wait_key(stdscr, 13)


def setup(stdscr):
    items = [
        ("a", "Clear all data"),
        ("b", "Calibration", cal_text),
        ("c", "CT turns", lambda: settings["turns"]),
        ("d", "Device port", lambda: settings["port"]),
    ]
    screens = [setup_clear_all, setup_calibration, setup_turns, setup_port]
    while True:
        choice = menu(stdscr, "Setup", items)
        if choice is None:
            return
        screens[choice](stdscr)


# ---------- Logging ----------

def hms(total):
    return total // 3600, total % 3600 // 60, total % 60


def fmt_interval(total):
    h, m, sec = hms(total)
    parts = [f"{h}h"] * (h > 0) + [f"{m}m"] * (h > 0 or m > 0) + [f"{sec}s"]
    return " ".join(parts)


def edit_interval(stdscr, y, x, total):
    """Interval editor with three fields (h, m, s).
    Digits are typed in like on a calculator: they enter on the right and push the
    earlier ones to the left; the number is taken as seconds (1, 0, 5 -> 105s -> 1m 45s).
    Left/Right or h/l select a field, Up/Down or k/j change it, Backspace removes the
    last digit. Returns seconds on Enter, None on Esc / q."""
    typed = ""   # digits typed since the last arrow / start; "" = not typing
    field = 2    # 0 = hours, 1 = minutes, 2 = seconds
    step = (3600, 60, 1)
    while True:
        h, m, sec = hms(total)
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, x, "[ ")
        for n, (val, unit) in enumerate(((h, "h"), (m, "m"), (sec, "s"))):
            attr = curses.A_REVERSE | curses.A_BOLD if n == field else curses.A_BOLD
            stdscr.addstr(f"{val:2d}", attr)
            stdscr.addstr(f"{unit}  " if n < 2 else f"{unit} ]")
        stdscr.addstr(f"   = {total}s", curses.A_DIM)
        stdscr.refresh()

        key = get_key(stdscr)
        if key in (ESC, ord("q"), ord("Q")):
            return None
        if key in ENTER_KEYS:
            return total
        if ord("0") <= key <= ord("9"):
            candidate = int(typed + chr(key))
            if candidate <= MAX_LOG_INTERVAL:
                typed += chr(key)
                total = candidate
        elif key in BACKSPACE_KEYS:
            typed = typed[:-1] if typed else str(total)[:-1]
            total = int(typed or "0")
        elif key in (curses.KEY_LEFT, ord("h")):
            field, typed = max(field - 1, 0), ""
        elif key in (curses.KEY_RIGHT, ord("l")):
            field, typed = min(field + 1, 2), ""
        elif key in (curses.KEY_UP, ord("k")):
            total, typed = min(total + step[field], MAX_LOG_INTERVAL), ""
        elif key in (curses.KEY_DOWN, ord("j")):
            total, typed = max(total - step[field], 0), ""


def logging_interval(stdscr):
    while True:
        draw_title(stdscr, "Logging > Interval")
        text = [
            "How often a line is written to the log file.",
            "Type the number of seconds; digits enter from the right:",
            "   1  ->  1s      1 0  ->  10s      1 0 5  ->  105s = 1m 45s",
            "Left/Right or h/l select h / m / s,  Up/Down or k/j change it.",
            "Backspace deletes the last digit.",
        ]
        for n, line in enumerate(text):
            stdscr.addstr(3 + n, 4, line)
        stdscr.addstr(9, 4, f"Allowed: 1s to {fmt_interval(MAX_LOG_INTERVAL)}.  Enter = save, Esc/q = cancel",
                      curses.A_DIM)
        stdscr.addstr(11, 4, "Interval:")
        curses.curs_set(0)
        new = edit_interval(stdscr, 11, 14, settings["log_interval_s"])
        if new is None:
            return
        if new < 1:
            message(stdscr, 13, "The interval must be at least 1 second - not saved.", bold=True)
            wait_key(stdscr, 15)
            continue
        settings["log_interval_s"] = new
        save_settings(settings)
        message(stdscr, 13, f"Saved: one line every {fmt_interval(new)}.")
        wait_key(stdscr, 15)
        return


SHORT_NAMES = {"u": "U", "i": "I", "p": "P", "pf": "PF", "f": "f", "e": "E"}


def log_values_text():
    chosen = [q[0] for q in QUANTITIES if q[0] in settings["log_values"]]
    if len(chosen) == len(QUANTITIES):
        return "all"
    return " ".join(SHORT_NAMES[k] for k in chosen) or "none"


def logging_values(stdscr):
    """Checkbox list: which quantities go into the CSV file. Saved on every change."""
    sel = 0
    note = ""
    while True:
        draw_title(stdscr, "Logging > Values")
        stdscr.addstr(3, 4, "Choose which values are written to the CSV file.")
        stdscr.addstr(4, 4, "Every line also gets a date and time column.")
        for n, (k, hotkey, label, unit, _, _) in enumerate(QUANTITIES):
            box = "[x]" if k in settings["log_values"] else "[ ]"
            attr = curses.A_REVERSE if n == sel else curses.A_NORMAL
            unit_txt = f" [{unit}]" if unit else ""
            stdscr.addstr(6 + n, 4, f" {box} {n + 1}. {label}{unit_txt} ({hotkey}) ", attr)
        y = 7 + len(QUANTITIES)
        stdscr.addstr(y, 4, "letter or 1-6 = switch on/off;  arrows/jk + Space/Enter/l = switch", curses.A_DIM)
        stdscr.addstr(y + 1, 4, "q/h = back (changes are saved immediately)", curses.A_DIM)
        if note:
            message(stdscr, y + 3, note, bold=True)
        stdscr.refresh()

        key = nav(get_key(stdscr))
        note = ""
        if is_back(key):
            return
        toggle = None
        if key == curses.KEY_UP:
            sel = (sel - 1) % len(QUANTITIES)
        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % len(QUANTITIES)
        elif key in ENTER_KEYS or key == ord(" "):
            toggle = sel
        elif ord("1") <= key < ord("1") + len(QUANTITIES):
            toggle = key - ord("1")
        else:
            for n, q in enumerate(QUANTITIES):
                if key in (ord(q[1]), ord(q[1].upper())):
                    toggle = n
        if toggle is None:
            continue
        sel = toggle
        k = QUANTITIES[toggle][0]
        chosen = set(settings["log_values"])
        if k in chosen:
            if len(chosen) == 1:
                note = "At least one value must stay selected."
                continue
            chosen.remove(k)
        else:
            chosen.add(k)
        settings["log_values"] = [q[0] for q in QUANTITIES if q[0] in chosen]  # keep screen order
        save_settings(settings)


def not_yet(stdscr, title):
    draw_title(stdscr, title)
    stdscr.addstr(3, 4, "Not implemented yet.")
    wait_key(stdscr, 5)


def radio_menu(stdscr, title, options, current, intro=()):
    """options: list of (hotkey, label, mode). Marks the current mode with *.
    Returns the chosen mode, or None for back."""
    sel = next((n for n, o in enumerate(options) if o[2] == current), 0)
    while True:
        draw_title(stdscr, title)
        for n, line in enumerate(intro):
            stdscr.addstr(3 + n, 4, line)
        y0 = 3 + len(intro) + (1 if intro else 0)
        for n, (hotkey, label, mode) in enumerate(options):
            mark = "*" if mode == current else " "
            attr = curses.A_REVERSE if n == sel else curses.A_NORMAL
            stdscr.addstr(y0 + n, 4, f"{mark}{n + 1}. {label} ({hotkey}) ", attr)
        stdscr.addstr(y0 + len(options) + 1, 4,
                      f"letter, 1-{len(options)} or arrows/jk + Enter/l;  * = current;  q/h = back", curses.A_DIM)
        stdscr.refresh()
        key = nav(get_key(stdscr))
        if is_back(key):
            return None
        if key == curses.KEY_UP:
            sel = (sel - 1) % len(options)
        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % len(options)
        elif key in ENTER_KEYS:
            return options[sel][2]
        elif ord("1") <= key < ord("1") + len(options):
            return options[key - ord("1")][2]
        else:
            for o in options:
                if key in (ord(o[0]), ord(o[0].upper())):
                    return o[2]


def edit_datetime(stdscr, y, x, dt):
    """Date/time editor: YYYY-MM-DD HH:MM:SS, one field selected at a time.
    Digits enter the selected field from the right (calculator style); a digit that
    would make the field too big starts the field again. Left/Right or h/l select a
    field, Up/Down or k/j change it (wrapping around).
    Returns a datetime on Enter, None on Esc / q."""
    vals = [dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second]
    widths = [4, 2, 2, 2, 2, 2]
    seps = ["-", "-", "  ", ":", ":", ""]
    field = 3      # start on the hour
    typed = False  # True while digits are being typed into the current field
    note = ""

    def limits(n):
        year = min(max(vals[0], 2000), 2099)
        return [(2000, 2099), (1, 12), (1, calendar.monthrange(year, vals[1])[1]),
                (0, 23), (0, 59), (0, 59)][n]

    while True:
        if field != 2 or not typed:
            vals[2] = min(vals[2], limits(2)[1])  # 31 -> 30 after switching to a shorter month
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, x, "[ ")
        for n in range(6):
            attr = curses.A_REVERSE | curses.A_BOLD if n == field else curses.A_BOLD
            stdscr.addstr(f"{vals[n]:0{widths[n]}d}", attr)
            stdscr.addstr(seps[n])
        stdscr.addstr(" ]")
        message(stdscr, y + 1, note, bold=True)
        note = ""
        stdscr.refresh()

        key = get_key(stdscr)
        lo, hi = limits(field)
        if key in (ESC, ord("q"), ord("Q")):
            return None
        if key in ENTER_KEYS:
            bad = [n for n in range(6) if not limits(n)[0] <= vals[n] <= limits(n)[1]]
            if bad:
                field, typed = bad[0], False
                note = "Year must be 2000-2099." if bad[0] == 0 else "Invalid value."
                continue
            return datetime.datetime(*vals)
        if ord("0") <= key <= ord("9"):
            d = chr(key)
            cand = int(((str(vals[field]) if typed else "") + d)[-widths[field]:])
            if field != 0 and cand > hi:
                cand = int(d)
            vals[field], typed = cand, True
        elif key in BACKSPACE_KEYS:
            vals[field], typed = vals[field] // 10, True
        elif key in (curses.KEY_LEFT, ord("h"), curses.KEY_RIGHT, ord("l")):
            step = -1 if key in (curses.KEY_LEFT, ord("h")) else 1
            field, typed = min(max(field + step, 0), 5), False
        elif key in (curses.KEY_UP, ord("k"), curses.KEY_DOWN, ord("j")):
            step = 1 if key in (curses.KEY_UP, ord("k")) else -1
            v = min(max(vals[field], lo), hi) + step
            vals[field], typed = (lo if v > hi else hi if v < lo else v), False


def parse_time(text):
    try:
        return datetime.datetime.strptime(text, TIME_FMT)
    except ValueError:
        return None


def set_time_screen(stdscr, title, key, default, check=None):
    """Edits settings[key] (a time string). check(dt) returns an error text or None.
    Returns True if saved."""
    dt = parse_time(settings[key]) or default
    while True:
        draw_title(stdscr, title)
        stdscr.addstr(3, 4, "Date and time: year-month-day  hour:minute:second (24h).")
        stdscr.addstr(4, 4, "Left/Right or h/l select a field,  Up/Down or k/j change it,")
        stdscr.addstr(5, 4, "or type the digits of the selected field.")
        stdscr.addstr(7, 4, "Enter = save, Esc/q = cancel", curses.A_DIM)
        stdscr.addstr(9, 4, "Time:")
        new = edit_datetime(stdscr, 9, 10, dt)
        if new is None:
            return False
        err = check(new) if check else None
        if err:
            message(stdscr, 11, err + " - not saved.", bold=True)
            wait_key(stdscr, 13)
            dt = new
            continue
        settings[key] = new.strftime(TIME_FMT)
        return True


def next_full_hour():
    now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
    return now + datetime.timedelta(hours=1)


def start_text():
    mode = settings["log_start_mode"]
    return {"manual": "manual", "minute": "manual, on the full minute"}.get(mode, settings["log_start_time"])


def end_text():
    return "manual" if settings["log_end_mode"] == "manual" else settings["log_end_time"]


def end_before_start(end):
    if settings["log_start_mode"] == "time":
        start = parse_time(settings["log_start_time"])
        if start and end <= start:
            return f"End time must be after the start time ({settings['log_start_time']})"
    return None


def logging_start(stdscr):
    options = [("m", "Manual - starts when you start it", "manual"),
               ("t", "Set time - starts by itself at a date and time", "time"),
               ("n", "Manual, on the full minute - waits for the next :00s", "minute")]
    while True:
        mode = radio_menu(stdscr, "Logging > Start time", options, settings["log_start_mode"])
        if mode is None:
            return
        if mode == "time":
            def check(dt):
                if settings["log_end_mode"] == "time":
                    end = parse_time(settings["log_end_time"])
                    if end and end <= dt:
                        return f"Start time must be before the end time ({settings['log_end_time']})"
                return None
            if not set_time_screen(stdscr, "Logging > Start time > Set time", "log_start_time",
                                   next_full_hour(), check):
                continue  # cancelled: back to the options
        settings["log_start_mode"] = mode
        save_settings(settings)
        return


def logging_end(stdscr):
    options = [("m", "Manual - runs until you stop it", "manual"),
               ("t", "Set time - stops by itself at a date and time", "time")]
    while True:
        mode = radio_menu(stdscr, "Logging > End time", options, settings["log_end_mode"])
        if mode is None:
            return
        if mode == "time":
            start = parse_time(settings["log_start_time"]) if settings["log_start_mode"] == "time" else None
            default = (start or next_full_hour()) + datetime.timedelta(hours=1)
            if not set_time_screen(stdscr, "Logging > End time > Set time", "log_end_time",
                                   default, end_before_start):
                continue
        settings["log_end_mode"] = mode
        save_settings(settings)
        return


def logging_dir(stdscr):
    while True:
        draw_title(stdscr, "Logging > File location")
        stdscr.addstr(3, 4, "Folder for the log files. Every logging run creates a new file")
        stdscr.addstr(4, 4, "named after its start time, e.g. 2026-11-04_213000.csv")
        stdscr.addstr(5, 4, "~ means your home folder.")
        stdscr.addstr(7, 4, "Enter = save, Esc = cancel", curses.A_DIM)
        stdscr.addstr(9, 4, "Folder:")
        new = edit_line(stdscr, 9, 12, settings["log_dir"], width=50)
        if not new:
            return
        path = os.path.expanduser(new)
        if not os.path.isdir(path):
            message(stdscr, 11, f"{path} does not exist.", bold=True)
            message(stdscr, 12, "ENTER = create it, any other key = edit again")
            stdscr.refresh()
            if get_key(stdscr) not in ENTER_KEYS:
                continue
            try:
                os.makedirs(path)
            except OSError as ex:
                message(stdscr, 12, f"Cannot create it: {ex.strerror}", bold=True)
                wait_key(stdscr, 14)
                continue
        if not os.access(path, os.W_OK):
            message(stdscr, 11, f"No permission to write into {path}.", bold=True)
            message(stdscr, 12, "")
            wait_key(stdscr, 14)
            continue
        settings["log_dir"] = new
        save_settings(settings)
        message(stdscr, 11, f"Saved: {path}")
        message(stdscr, 12, "")
        wait_key(stdscr, 14)
        return


def start_label():
    return "Arm logging" if settings["log_start_mode"] == "time" else "Start logging"


def info_screen(stdscr, title, lines, bold=False):
    draw_title(stdscr, title)
    for n, line in enumerate(lines):
        stdscr.addstr(3 + n, 4, line[: stdscr.getmaxyx()[1] - 5], curses.A_BOLD if bold and n == 0 else 0)
    wait_key(stdscr, 4 + len(lines))


def logging_start_run(stdscr):
    title = "Logging > " + start_label()
    if log_run.state != "idle":
        info_screen(stdscr, title, [f"Logging is already {log_run.state}.", "Stop it first (x)."], bold=True)
        return
    with monitor.lock:
        err = log_run.arm(time.time())
    if err:
        info_screen(stdscr, title, ["Not started: " + err], bold=True)
        return
    if log_run.state == "running":
        lines = ["Logging started.", f"File: {log_run.path}"]
    else:
        lines = ["Logging armed.", f"It starts by itself at {time.strftime(TIME_FMT, time.localtime(log_run.start_at))}",
                 f"File will be created in {os.path.expanduser(settings['log_dir'])}"]
    if log_run.end_at:
        lines.append(f"It stops by itself at {time.strftime(TIME_FMT, time.localtime(log_run.end_at))}")
    lines.append("The LOG mark at the top right: blinking = armed, steady = logging.")
    info_screen(stdscr, title, lines)


def logging_stop_run(stdscr):
    title = "Logging > Stop logging"
    if log_run.state == "idle":
        info_screen(stdscr, title, ["Logging is not running."])
        return
    draw_title(stdscr, title)
    what = "Stop logging" if log_run.state == "running" else "Cancel the armed start"
    stdscr.addstr(3, 4, f"{what}?", curses.A_BOLD)
    stdscr.addstr(4, 4, log_run.summary())
    stdscr.addstr(6, 4, "ENTER = yes, any other key = no")
    stdscr.refresh()
    if get_key(stdscr) not in ENTER_KEYS:
        return
    with monitor.lock:
        log_run.stop(time.time())
    info_screen(stdscr, title, [log_run.info])


def logging_screen(stdscr):
    items = [
        ("i", "Interval", lambda: fmt_interval(settings["log_interval_s"])),
        ("v", "Values", log_values_text),
        ("s", "Start time", start_text),
        ("e", "End time", end_text),
        ("f", "File location", lambda: settings["log_dir"]),
        ("a", "Start logging", log_run.summary),
        ("x", "Stop logging"),
    ]
    screens = [logging_interval, logging_values, logging_start, logging_end, logging_dir,
               logging_start_run, logging_stop_run]
    while True:
        items[5] = ("a", start_label(), log_run.summary)
        choice = menu(stdscr, "Logging", items)
        if choice is None:
            return
        if choice < 5 and log_run.state != "idle":
            info_screen(stdscr, "Logging", [f"Logging is {log_run.state} - settings cannot be changed now.",
                                            "Stop logging first (x)."], bold=True)
            continue
        screens[choice](stdscr)


# ---------- main ----------

MAIN_MENU = [("m", "Measurement"), ("g", "Logging"), ("s", "Setup")]
MAIN_SCREENS = [measurement, logging_screen, setup]


class SafeWindow:
    """Wraps the curses screen so text that falls outside a small terminal is skipped
    instead of stopping the program with a curses error."""

    def __init__(self, win):
        self._win = win

    def __getattr__(self, name):
        return getattr(self._win, name)

    def _safe(name):
        def method(self, *args):
            try:
                return getattr(self._win, name)(*args)
            except curses.error:
                return None
        return method

    addstr = _safe("addstr")
    addch = _safe("addch")
    hline = _safe("hline")
    vline = _safe("vline")
    move = _safe("move")


def app(stdscr):
    stdscr = SafeWindow(stdscr)
    curses.curs_set(0)
    curses.set_escdelay(25)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLUE)  # data inside the zoom highlight
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)  # empty cells of the highlight
    monitor.start()
    while True:
        choice = menu(stdscr, "pzemlyzer", MAIN_MENU, back_hint="q = quit", h_backs=False)
        if choice is None:
            if log_run.state == "idle":
                return
            what = "running" if log_run.state == "running" else "armed"
            rows_scr = stdscr.getmaxyx()[0]
            message(stdscr, rows_scr - 2, f"Logging is {what}. Quitting stops it.", bold=True)
            message(stdscr, rows_scr - 1, "ENTER = stop logging and quit, any other key = stay")
            stdscr.refresh()
            if get_key(stdscr) in ENTER_KEYS:
                with monitor.lock:
                    log_run.stop(time.time())
                return
            continue
        MAIN_SCREENS[choice](stdscr)


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")  # needed for the Braille characters of the graphs
    try:
        curses.wrapper(app)
    except KeyboardInterrupt:
        pass
