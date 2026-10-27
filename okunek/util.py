"""Мелкие общие функции."""
import os
import re


def fmt(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}" if s > 0 else "—"


def trunc(s, n):
    return s if len(s) <= n else s[:n - 1] + "…"


def hx(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


_mix_cache = {}


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    k = (a, b, round(t, 2))
    r = _mix_cache.get(k)
    if r is None:
        x, y = hx(a), hx(b)
        r = "#%02x%02x%02x" % tuple(round(x[i] + (y[i] - x[i]) * k[2]) for i in range(3))
        if len(_mix_cache) > 4000:
            _mix_cache.clear()
        _mix_cache[k] = r
    return r


def rr(c, x1, y1, x2, y2, r, **kw):
    """Скруглённый прямоугольник на Canvas."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def nowin():
    return 0x08000000 if os.name == "nt" else 0


def human_num(n):
    n = float(n or 0)
    for lim, suf in ((1e9, " млрд"), (1e6, " млн"), (1e3, " тыс")):
        if n >= lim:
            v = n / lim
            return (f"{v:.1f}".rstrip("0").rstrip(".") + suf)
    return str(int(n))


def safe_name(s, n=150):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()[:n]


def dbg(*a):
    """print, который не падает на консолях без поддержки кириллицы (cp1252 и т. п.)."""
    try:
        print(*a)
    except Exception:  # noqa: BLE001
        pass
