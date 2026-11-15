"""Readings of the whole run, kept small enough for runs of days or weeks.

Two levels:
- raw readings of the last RAW_KEEP seconds, for zooming in on recent data
- one summary per clock minute for the whole run: min, max, sum and count of each
  value, plus the energy used in that minute

Graphs that show more than a minute per dot column are drawn from the minute
summaries only. A min/max/average per column is all the graph shows, so they look
the same as with raw data. Zooming in on data older than RAW_KEEP shows one point per
minute instead of one per reading (the UI limits how far you can zoom in there).

add() is called by the reading thread, the rest by the UI thread; a lock keeps them
apart. Queries return copies, so the caller can use them without holding the lock.
"""
import bisect
import threading

KEYS = ("u", "i", "p", "pf", "f")  # values summarised per minute
RAW_KEEP = 24 * 3600               # seconds of raw readings kept (about 1.6MB per hour)
MINUTE = 60

# layout of one minute summary (a flat list keeps it small: about 700 bytes)
_K, _T0, _T1, _N, _WH = range(5)
_LO, _HI, _SUM = 5, 6, 7           # + 3 * index of the key in KEYS


class History:
    def __init__(self, max_gap):
        self.max_gap = max_gap  # longer pauses between readings add no energy
        self.lock = threading.Lock()
        self.raw = []           # (unix time, values dict), oldest first
        self.raw_from = None    # raw readings before this minute start were dropped
        self.minutes = []       # minute summaries, oldest first
        self.count = 0          # readings added so far (the UI redraws when it changes)
        self._prev = None       # (t, P) of the previous reading, for the energy integral

    def add(self, t, values):
        with self.lock:
            k = int(t // MINUTE)
            if not self.minutes or self.minutes[-1][_K] != k:
                m = [k, t, t, 0, 0.0]
                for key in KEYS:
                    m += [values[key], values[key], 0.0]
                self.minutes.append(m)
            m = self.minutes[-1]
            m[_T1] = t
            m[_N] += 1
            for n, key in enumerate(KEYS):
                v = values[key]
                o = 3 * n
                if v < m[_LO + o]:
                    m[_LO + o] = v
                if v > m[_HI + o]:
                    m[_HI + o] = v
                m[_SUM + o] += v

            # energy: trapezoid between this and the previous reading, booked to the
            # minute of its midpoint (the previous minute if the step crosses into this one)
            if self._prev is not None and 0 < t - self._prev[0] <= self.max_gap:
                t0, p0 = self._prev
                wh = (p0 + values["p"]) / 2 * (t - t0) / 3600
                target = m
                if int((t0 + t) / 2 // MINUTE) != k and len(self.minutes) > 1:
                    target = self.minutes[-2]
                target[_WH] += wh
            self._prev = (t, values["p"])

            self.raw.append((t, values))
            self.count += 1
            cutoff = int((t - RAW_KEEP) // MINUTE) * MINUTE  # drop whole minutes only
            if self.raw[0][0] < cutoff:
                del self.raw[:bisect.bisect_left(self.raw, cutoff, key=lambda r: r[0])]
                self.raw_from = cutoff

    def items(self, key, t_start, t_end, dot_seconds):
        """Data of one value inside [t_start, t_end] for the trend graph, oldest first, as
        (t_first, t_last, lo, hi, sum, count). dot_seconds = time per dot column: from a
        minute per column up, only minute summaries are used, below that raw readings
        where they are still kept."""
        o = 3 * KEYS.index(key)
        with self.lock:
            if dot_seconds >= MINUTE or not self.raw:
                raw_from = float("inf")  # everything from the minute summaries
            else:
                raw_from = self.raw_from if self.raw_from is not None else float("-inf")
            out = []
            i0 = bisect.bisect_left(self.minutes, int(t_start // MINUTE), key=lambda m: m[_K])
            for m in self.minutes[i0:]:
                if m[_K] * MINUTE >= min(t_end, raw_from):
                    break
                out.append((m[_T0], m[_T1], m[_LO + o], m[_HI + o], m[_SUM + o], m[_N]))
            if raw_from != float("inf"):
                lo_t = max(t_start, raw_from)
                i0 = bisect.bisect_left(self.raw, lo_t, key=lambda r: r[0])
                i1 = bisect.bisect_right(self.raw, t_end, key=lambda r: r[0])
                out += [(t, t, v[key], v[key], v[key], 1) for t, v in self.raw[i0:i1]]
            return out

    def energy_per_minute(self):
        """{minute index: Wh}; minute index * 60 = start of the minute (unix time)."""
        with self.lock:
            return {m[_K]: m[_WH] for m in self.minutes}
