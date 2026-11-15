"""Text trend plot using Braille characters (each character cell = 2 x 4 dots)."""

# dot (column, row) inside a cell -> bit of the Braille character U+2800 + bits
_DOT_BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
             (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}


class Canvas:
    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.w, self.h = 2 * cols, 4 * rows  # size in dots
        self.cells = [[0] * cols for _ in range(rows)]

    def dot(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.cells[y // 4][x // 2] |= _DOT_BITS[(x % 2, y % 4)]

    def vline(self, x, y1, y2):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            self.dot(x, y)

    def lines(self):
        return ["".join(chr(0x2800 + c) if c else " " for c in row) for row in self.cells]


def trend(items, cols, rows, t_start, t_end, v_min, v_max, max_gap):
    """items: time-ordered (t_first, t_last, lo, hi, sum, count) - a single reading
    (t, t, v, v, v, 1) or a summary of several (see history.py).
    Returns (line, envelope): two lists of `rows` strings.

    Each dot column covers a slice of time. `line` is the average of the readings in
    each slice, joined into a continuous line (not across gaps longer than max_gap
    seconds - lost communication shows as a gap). `envelope` is a faint dotted bar from
    the lowest to the highest reading of each slice, so spikes and dips stay visible
    even when one column holds many readings."""
    line, env = Canvas(cols, rows), Canvas(cols, rows)
    span_t = max(t_end - t_start, 1e-9)
    span_v = max(v_max - v_min, 1e-9)

    def to_y(v):
        y = round((v_max - v) / span_v * (line.h - 1))
        return min(max(y, 0), line.h - 1)

    buckets = {}  # x -> [lo, hi, sum, count, t_first, t_last]
    for t0, t1, lo, hi, total, n in items:
        x = min(max(int(((t0 + t1) / 2 - t_start) / span_t * line.w), 0), line.w - 1)
        b = buckets.get(x)
        if b is None:
            buckets[x] = [lo, hi, total, n, t0, t1]
        else:
            b[0], b[1], b[2], b[3], b[5] = min(b[0], lo), max(b[1], hi), b[2] + total, b[3] + n, t1

    prev = None  # (x, y of the average, t_last)
    for x in sorted(buckets):
        lo, hi, total, n, t_first, t_last = buckets[x]
        y_avg = to_y(total / n)
        y_top, y_bot = to_y(hi), to_y(lo)
        for y in range(y_top, y_bot + 1):  # faint: only every other dot, plus both ends
            if y in (y_top, y_bot) or y % 2 == 0:
                env.dot(x, y)
        if prev is not None and t_first - prev[2] <= max_gap:
            px, py, _ = prev
            y_prev = py
            for xi in range(px + 1, x + 1):  # straight line from the previous average
                yi = round(py + (y_avg - py) * (xi - px) / (x - px))
                line.vline(xi, y_prev, yi)
                y_prev = yi
        else:
            line.dot(x, y_avg)
        prev = (x, y_avg, t_last)
    return line.lines(), env.lines()


_EIGHTHS = " ▁▂▃▄▅▆▇█"


def bars(values, rows, v_max, bar_w=2, gap=1):
    """Vertical bar chart with 1/8-character resolution. values: list of numbers or
    None (no data). Returns a list of `rows` strings, one bar = bar_w columns + gap."""
    lines = []
    span = max(v_max, 1e-12)
    heights = [None if v is None else max(0, round(v / span * rows * 8)) for v in values]
    for r in range(rows):  # r = 0 is the top row
        floor = (rows - 1 - r) * 8  # eighths below this row
        line = []
        for h in heights:
            if h is None:
                ch = " "
            else:
                ch = _EIGHTHS[min(max(h - floor, 0), 8)]
            line.append(ch * bar_w + " " * gap)
        lines.append("".join(line))
    return lines


def value_to_dot_y(v, rows, v_min, v_max):
    h = 4 * rows
    y = round((v_max - v) / max(v_max - v_min, 1e-9) * (h - 1))
    return min(max(y, 0), h - 1)


def guides(cols, rows, v_min, v_max, levels, x_dots=()):
    """Dotted reference lines. levels: horizontal lines as (value, spacing in dots);
    spacing 2 = a dot in every character cell, 4 = every other cell.
    x_dots: dot columns of vertical time lines (a dot on every other dot row).
    Returns (lines, rows_used) - rows_used[n] = text row of levels[n]."""
    c = Canvas(cols, rows)
    used = []
    for v, spacing in levels:
        y = value_to_dot_y(v, rows, v_min, v_max)
        for x in range(0, c.w, spacing):
            c.dot(x, y)
        used.append(y // 4)
    for x in x_dots:
        for y in range(0, c.h, 2):
            c.dot(x, y)
    return c.lines(), used


# time grid steps in seconds, from fine to coarse
GRID_STEPS = [5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1200, 1800,
              3600, 2 * 3600, 3 * 3600, 6 * 3600, 12 * 3600, 24 * 3600]


def fmt_elapsed(sec):
    """Compact elapsed time: 20s, 1m30s, 15m, 1h, 1h30m, 1d6h."""
    sec = int(round(sec))
    d, rest = divmod(sec, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    parts = [(d, "d"), (h, "h"), (m, "m"), (s, "s")]
    parts = [f"{v}{u}" for v, u in parts if v]
    return "".join(parts[:2]) or "0s"


def time_grid(rel0, duration, cols):
    """Vertical time lines for a window starting rel0 seconds after the run start and
    lasting `duration` seconds. Lines sit at whole multiples of the step counted from
    the run start, so they stay put while panning. Picks the finest step whose labels
    still fit with room between them.
    Returns [(seconds since run start, dot column, char column, label), ...]."""
    def marks_for(step):
        k = int(rel0 // step) + 1
        out = []
        while k * step < rel0 + duration * 0.999:
            x = int((k * step - rel0) / duration * 2 * cols)
            out.append((k * step, x, x // 2, fmt_elapsed(k * step)))
            k += 1
        return out

    for step in GRID_STEPS:
        marks = marks_for(step)
        if not marks:
            continue
        widest = max(len(m[3]) for m in marks)
        if cols * step / duration >= widest + 3:  # chars between two lines
            return marks
    return []
