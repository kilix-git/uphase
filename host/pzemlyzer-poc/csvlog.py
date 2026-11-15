"""CSV logging: one line per interval with average, minimum and maximum of each
chosen value, plus the energy used in that interval.

Intervals are counted from the logging start time: start + k * interval.
Each line is stamped with the END time of its interval.
"""
import csv
import time

# (values key, CSV name, unit, decimals)
COLUMNS = [
    ("u", "U", "V", 1),
    ("i", "I", "A", 3),
    ("p", "P", "W", 1),
    ("pf", "PF", "", 3),
    ("f", "f", "Hz", 2),
    ("e", "E", "Wh", 3),
]


class CsvLogger:
    def __init__(self, path, interval, keys, start_time, max_gap=3.0):
        self.interval = interval
        self.keys = [c for c in COLUMNS if c[0] in keys]
        self.start = start_time
        self.max_gap = max_gap  # longer pauses between readings add no energy
        self.k = 0              # number of the interval being collected
        self.prev = None        # (t, P) of the previous reading, for the energy integral
        self.lines = 0
        self._reset()
        self.fh = open(path, "w", newline="")
        self.w = csv.writer(self.fh)
        header = ["time", "readings"]
        for _, name, unit, _ in self.keys:
            u = f" [{unit}]" if unit else ""
            if name == "E":
                header.append(f"E{u}")
            else:
                header += [f"{name}_avg{u}", f"{name}_min{u}", f"{name}_max{u}"]
        self.w.writerow(header)
        self.fh.flush()

    def _reset(self):
        self.n = 0
        self.sum = {}
        self.min = {}
        self.max = {}
        self.sum_ui = 0.0  # for the power factor average: sum(P) / sum(U*I)
        self.energy = 0.0

    def _end(self, k):
        return self.start + (k + 1) * self.interval

    def _write(self, t_end=None):
        t_end = self._end(self.k) if t_end is None else min(t_end, self._end(self.k))
        t_end = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_end))
        row = [t_end, self.n]
        for key, name, _, dec in self.keys:
            if name == "E":
                row.append(f"{self.energy:.{dec}f}")
            elif self.n == 0:
                row += ["", "", ""]
            else:
                if key == "pf" and self.sum_ui > 0:
                    avg = min(self.sum["p"] / self.sum_ui, 1.0)  # true average PF = total P / total S
                else:
                    avg = self.sum[key] / self.n
                row += [f"{avg:.{dec}f}", f"{self.min[key]:.{dec}f}", f"{self.max[key]:.{dec}f}"]
        self.w.writerow(row)
        self.fh.flush()  # a crash or power cut loses at most the current interval
        self.lines += 1
        self._reset()

    def tick(self, t):
        """Write every interval that has ended by time t - also when there were no
        readings (readings = 0), so communication outages show up in the file."""
        while t >= self._end(self.k):
            self._write()
            self.k += 1

    def add(self, t, v):
        """One reading: t = unix time, v = values dict (u, i, p, pf, f)."""
        if t < self.start:
            return
        self.tick(t)
        if self.prev is not None and 0 < t - self.prev[0] <= self.max_gap:
            self.energy += (self.prev[1] + v["p"]) / 2 * (t - self.prev[0]) / 3600
        self.prev = (t, v["p"])
        self.n += 1
        for key in ("u", "i", "p", "pf", "f"):
            x = v[key]
            self.sum[key] = self.sum.get(key, 0.0) + x
            self.min[key] = min(self.min.get(key, x), x)
            self.max[key] = max(self.max.get(key, x), x)
        self.sum_ui += v["u"] * v["i"]

    def close(self, t_stop):
        """Write the intervals up to t_stop, then the unfinished last one stamped with
        the stop time, and close the file."""
        self.tick(t_stop)
        if t_stop > self.start + self.k * self.interval:  # current interval has begun
            self._write(t_stop)
        self.fh.close()
