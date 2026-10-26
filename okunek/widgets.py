"""Виджеты на Canvas: плавные анимации (~60 fps только пока что-то движется), виртуальные списки."""
import math
import tkinter as tk
from tkinter import font as tkfont

from .config import F, FB, FI, FS, SANS, SYM, UNKNOWN
from .util import fmt, human_num, mix, rr, trunc


# ═════════════════════ базовые анимированные виджеты ═════════════════════
class Animated(tk.Canvas):
    """Плавное приближение значений hv (наведение) и pr (нажатие) к целям th/tp."""

    def __init__(s, app, parent, pbg, **kw):
        super().__init__(parent, highlightthickness=0, bd=0, **kw)
        s.app, s.pbg = app, pbg
        s.W, s.H = int(kw.get("width", 10)), int(kw.get("height", 10))
        s._job, s.hv, s.th, s.pr, s.tp = None, 0.0, 0.0, 0.0, 0.0
        app.rec.append(s)
        s.configure(bg=app.C[pbg])
        s.bind("<Configure>", lambda e: (setattr(s, "W", e.width), setattr(s, "H", e.height), s.draw()))

    def go(s, **kw):
        for k, v in kw.items():
            setattr(s, k, v)
        if not s._job:
            s._job = s.after(1, s._step)

    def _step(s):
        s._job = None
        if not s.winfo_exists():
            return
        moving = False
        for a, t in (("hv", "th"), ("pr", "tp")):
            d = getattr(s, t) - getattr(s, a)
            if abs(d) > 0.015:
                setattr(s, a, getattr(s, a) + d * 0.3)
                moving = True
            else:
                setattr(s, a, getattr(s, t))
        s.draw()
        if moving:
            s._job = s.after(14, s._step)

    def recolor(s):
        s.configure(bg=s.app.C[s.pbg])
        s.draw()

    def draw(s):
        pass


class AButton(Animated):
    """primary (акцент, «пружинит»), pill (чип), nav (пункт меню), ghost (иконка)."""

    def __init__(s, app, parent, text="", cmd=None, w=None, h=36, kind="ghost", font=F, pbg="panel", align="center", r=None):
        super().__init__(app, parent, pbg, width=w or 10, height=h, cursor="hand2")
        s.text, s.cmd, s.kind, s.font, s.align, s.r, s.active = text, cmd, kind, font, align, r, False
        s.bind("<Enter>", lambda e: s.go(th=1.0))
        s.bind("<Leave>", lambda e: s.go(th=0.0, tp=0.0))
        s.bind("<ButtonPress-1>", lambda e: s.go(tp=1.0))
        s.bind("<ButtonRelease-1>", s._up)

    def _up(s, e):
        s.go(tp=0.0)
        if 0 <= e.x <= s.W and 0 <= e.y <= s.H and s.cmd:
            s.cmd()

    def set_text(s, t):
        if t != s.text:
            s.text = t
            s.draw()

    def set_active(s, a):
        a = bool(a)
        if a != s.active:
            s.active = a
            s.draw()

    def draw(s):
        s.delete("all")
        w, h, C, k, hv = s.W, s.H, s.app.C, s.kind, s.hv
        if w < 6:
            return
        grow = 0
        if k == "primary":
            bg, fg, grow = mix(C["accent"], "#ffffff", .2 * hv), C["atext"], 2.5 * hv
        elif k == "pill":
            bg, fg = (mix(C["text"], C["accent"], .3 * hv), C["bg"]) if s.active else (mix(C["elev"], C["text"], .12 * hv), C["text"])
        elif k == "nav":
            bg = mix(C[s.pbg], C["elev"], 1 if s.active else hv)
            fg = mix(C["muted"], C["text"], 1 if s.active else hv)
        else:
            bg = mix(C[s.pbg], C["elev"], hv)
            fg = mix(C["accent"] if s.active else C["muted"], C["accent"] if s.active else C["text"], hv)
        ins = 2.2 * s.pr - grow
        r = s.r if s.r is not None else (8 if k == "nav" else h / 2)
        rr(s, ins, ins, w - ins, h - ins, r, fill=bg, outline="")
        s.create_text(w / 2 if s.align == "center" else 14, h / 2, text=s.text, fill=fg, font=s.font,
                      anchor="center" if s.align == "center" else "w")


class Slider(Animated):
    """Тонкая дорожка, ручка появляется при наведении."""

    def __init__(s, app, parent, cmd=None, rel=None, pbg="bg", h=18, w=None):
        super().__init__(app, parent, pbg, width=w or 10, height=h, cursor="hand2")
        s.cmd, s.rel, s.v, s.drag = cmd, rel, 0.0, False
        s.bind("<Enter>", lambda e: s.go(th=1.0))
        s.bind("<Leave>", lambda e: s.go(th=1.0 if s.drag else 0.0))
        s.bind("<ButtonPress-1>", s._press)
        s.bind("<B1-Motion>", s._move)
        s.bind("<ButtonRelease-1>", s._up)

    def _pos(s, e):
        s.v = min(1.0, max(0.0, (e.x - 7) / max(1, s.W - 14)))
        s.draw()
        if s.cmd:
            s.cmd(s.v)

    def _press(s, e):
        s.drag = True
        s.go(th=1.0)
        s._pos(e)

    def _move(s, e):
        if s.drag:
            s._pos(e)

    def _up(s, e):
        s.drag = False
        if not (0 <= e.x <= s.W and 0 <= e.y <= s.H):
            s.go(th=0.0)
        if s.rel:
            s.rel(s.v)

    def set(s, v):
        if not s.drag:
            v = min(1.0, max(0.0, v))
            if abs(v - s.v) > 0.0004:
                s.v = v
                s.draw()

    def draw(s):
        s.delete("all")
        w, h, C = s.W, s.H, s.app.C
        cy = h / 2
        if w < 20:
            return
        x = 7 + s.v * (w - 14)
        rr(s, 7, cy - 2, w - 7, cy + 2, 2, fill=mix(C[s.pbg], C["text"], .22), outline="")
        if x > 9:
            rr(s, 7, cy - 2, x, cy + 2, 2, fill=mix(C["text"], C["accent"], s.hv), outline="")
        if s.hv > .05:
            s.create_oval(x - 6 * s.hv, cy - 6 * s.hv, x + 6 * s.hv, cy + 6 * s.hv, fill=C["text"], outline="")


class PillEntry(Animated):
    """Поле поиска: скругление, подсветка при фокусе, подсказка."""

    def __init__(s, app, parent, var, on_enter=None, h=44, pbg="panel", ph="Исполнитель, песня или ссылка…"):
        super().__init__(app, parent, pbg, height=h)
        s.var, s.foc = var, False
        s.e = tk.Entry(s, textvariable=var, relief="flat", bd=0, font=(SANS, 11), highlightthickness=0)
        s.ew = s.create_window(46, h / 2, window=s.e, anchor="w")
        s.pl = tk.Label(s, text=ph, font=(SANS, 11), bd=0, cursor="xterm")
        s.pw = s.create_window(46, h / 2, window=s.pl, anchor="w")
        s.pl.bind("<Button-1>", lambda e: s.e.focus_set())
        s.e.bind("<FocusIn>", lambda e: (setattr(s, "foc", True), s.go(th=1.0), s.hint()))
        s.e.bind("<FocusOut>", lambda e: (setattr(s, "foc", False), s.go(th=0.0), s.hint()))
        if on_enter:
            s.e.bind("<Return>", lambda e: on_enter())
        var.trace_add("write", lambda *_: s.hint())
        s.recolor()

    def hint(s):
        s.itemconfigure(s.pw, state="hidden" if (s.var.get() or s.foc) else "normal")

    def draw(s):
        C = s.app.C
        s.delete("bg")
        s.delete("ic")
        if s.W < 80:
            return
        bg = mix(C["elev"], C["text"], .05 * (1 - s.hv))
        rr(s, 1, 1, s.W - 1, s.H - 1, s.H / 2, fill=bg, outline=mix(bg, C["accent"], s.hv), width=2, tags="bg")
        s.create_text(24, s.H / 2, text="⌕", font=(SYM, 16), fill=mix(C["muted"], C["text"], s.hv), tags="ic")
        s.tag_lower("bg")
        s.itemconfigure(s.ew, width=max(20, s.W - 70))
        s.e.configure(bg=bg)
        s.pl.configure(bg=bg)

    def recolor(s):
        C = s.app.C
        s.configure(bg=C[s.pbg])
        s.e.configure(fg=C["text"], insertbackground=C["text"], selectbackground=C["accent"], selectforeground=C["atext"])
        s.pl.configure(fg=C["muted"])
        s.draw()
        s.hint()


# ═════════════════════ плавная прокрутка (общая основа списков) ═════════════════════
class SmoothCanvas(tk.Canvas):
    """Пиксельная прокрутка с инерцией, плавное появление содержимого, тонкий скроллбар."""

    def __init__(s, app, parent, pbg="panel"):
        super().__init__(parent, highlightthickness=0, bd=0, bg=app.C[pbg], takefocus=1)
        s.app, s.pbg = app, pbg
        s.y = s.ty = 0.0
        s.W = s.H = 1
        s.fade = 1.0
        s._job = None
        s._sbd = None  # смещение захвата ползунка при перетаскивании
        app.rec.append(s)
        s.bind("<Configure>", s._cfg)
        s.bind("<MouseWheel>", s._wheel)
        s.bind("<Button-4>", lambda e: s._scroll_by(-110))
        s.bind("<Button-5>", lambda e: s._scroll_by(110))
        s.bind("<B1-Motion>", s._sb_move, add="+")
        s.bind("<ButtonRelease-1>", lambda e: setattr(s, "_sbd", None), add="+")

    # --- переопределяются
    def content_h(s):
        return 0

    def paint(s):
        pass

    # --- прокрутка
    def max_y(s):
        return max(0.0, s.content_h() - s.H)

    def _cfg(s, e):
        s.W, s.H = e.width, e.height
        s.ty = min(s.ty, s.max_y())
        s.y = min(s.y, s.max_y())
        s.redraw()

    def _wheel(s, e):
        s._scroll_by(-e.delta / 120 * 110)

    def _scroll_by(s, d):
        s.ty = min(s.max_y(), max(0.0, s.ty + d))
        s.kick()

    def scroll_to(s, y, smooth=True):
        s.ty = min(s.max_y(), max(0.0, y))
        if not smooth:
            s.y = s.ty
        s.kick()

    def kick(s):
        if not s._job:
            s._job = s.after(1, s._anim)

    def _anim(s):
        s._job = None
        if not s.winfo_exists():
            return
        moving = False
        d = s.ty - s.y
        if abs(d) > 0.5:
            s.y += d * 0.26
            moving = True
        else:
            s.y = s.ty
        if s.fade < 1:
            s.fade = min(1.0, s.fade + 0.1)
            moving = True
        s.redraw()
        if moving:
            s._job = s.after(14, s._anim)

    def start_fade(s):
        s.fade = 0.0
        s.kick()

    def redraw(s):
        if s.W < 4:
            return
        s.delete("all")
        s.paint()
        s._scrollbar()

    def recolor(s):
        s.configure(bg=s.app.C[s.pbg])
        s.redraw()

    # --- скроллбар
    def _thumb(s):
        ch = s.content_h()
        if ch <= s.H + 1:
            return None
        th = max(36, s.H * s.H / ch)
        top = (s.H - th) * (s.y / max(1, ch - s.H))
        return top, top + th

    def _scrollbar(s):
        t = s._thumb()
        if t:
            C = s.app.C
            rr(s, s.W - 9, t[0] + 2, s.W - 4, t[1] - 2, 2.5, fill=mix(C[s.pbg], C["muted"], .45 if s._sbd is not None else .28), outline="")

    def sb_hit(s, e):
        """Нажатие на скроллбар (правые 14 px). True — событие обработано."""
        t = s._thumb()
        if not t or e.x < s.W - 14:
            return False
        if t[0] <= e.y <= t[1]:
            s._sbd = e.y - t[0]
        else:  # клик по дорожке — прыжок
            s._sbd = (t[1] - t[0]) / 2
            s._sb_move(e)
        return True

    def _sb_move(s, e):
        if s._sbd is None:
            return
        t = s._thumb()
        if not t:
            return
        span = s.H - (t[1] - t[0])
        frac = min(1.0, max(0.0, (e.y - s._sbd) / max(1, span)))
        s.y = s.ty = frac * s.max_y()
        s.redraw()


_fonts = {}


def _font(spec):
    f = _fonts.get(spec)
    if f is None:
        f = _fonts[spec] = tkfont.Font(family=spec[0], size=spec[1], weight=spec[2] if len(spec) > 2 else "normal")
    return f


def fit(text, spec, maxw):
    """Обрезает строку «…» по ширине в пикселях."""
    f = _font(spec)
    if maxw <= 20:
        return ""
    if f.measure(text) <= maxw:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.measure(text[:mid] + "…") <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


# ═════════════════════ список треков ═════════════════════
class TrackList(SmoothCanvas):
    ROW = 58
    TF, AF = (SANS, 10, "bold"), (SANS, 9)

    def __init__(s, app, parent, pbg="panel"):
        super().__init__(app, parent, pbg)
        s.items, s.sel, s.anchor, s.hov, s.part = [], set(), -1, -1, ""
        s.cur_id, s.eq_on, s.phase, s.empty = None, False, 0, ""
        s.on_play = s.on_menu = s.on_fav = s.on_artist = s.on_album = s.on_delete = lambda *a: None
        s.bind("<Motion>", s._motion)
        s.bind("<Leave>", lambda e: s._set_hover(-1, ""))
        s.bind("<Button-1>", s._click)
        s.bind("<Double-Button-1>", s._dbl)
        s.bind("<Button-3>", s._ctx)
        s.bind("<Delete>", lambda e: s.on_delete(s.selected()))
        s.bind("<Return>", lambda e: s.selected() and s.on_play(s.selected()[0]))
        s.bind("<Up>", lambda e: s._key(-1))
        s.bind("<Down>", lambda e: s._key(1))
        s.bind("<Control-a>", lambda e: (setattr(s, "sel", {t["id"] for t in s.items}), s.redraw()))
        s.after(160, s._eq_loop)

    # --- данные
    def set_items(s, items, keep=False):
        s.items = items
        ids = {t["id"] for t in items}
        s.sel &= ids
        s.hov = -1
        if not keep:
            s.y = s.ty = 0.0
            s.start_fade()
        s.ty = min(s.ty, s.max_y())
        s.y = min(s.y, s.max_y())
        s.redraw()

    def selected(s):
        return [t for t in s.items if t["id"] in s.sel]

    def set_playing(s, tid, playing):
        if tid != s.cur_id or playing != s.eq_on:
            s.cur_id, s.eq_on = tid, playing
            s.redraw()

    def content_h(s):
        return len(s.items) * s.ROW + 14

    def reveal(s, tid):
        for i, t in enumerate(s.items):
            if t["id"] == tid:
                top = i * s.ROW
                if top < s.y or top + s.ROW > s.y + s.H:
                    s.scroll_to(top - s.H / 3)
                return

    # --- анимация эквалайзера
    def _eq_loop(s):
        try:
            if s.eq_on and s.cur_id and s.winfo_viewable():
                s.phase += 1
                a, b = int(s.y // s.ROW), int((s.y + s.H) // s.ROW)
                if any(t["id"] == s.cur_id for t in s.items[a:b + 1]) and not s._job:
                    s.redraw()
        finally:
            s.after(140, s._eq_loop)

    # --- отрисовка
    def paint(s):
        C, W, H, R = s.app.C, s.W, s.H, s.ROW
        if not s.items:
            if s.empty:
                s.create_text(W / 2, H / 3, text=s.empty, fill=C["muted"], font=(SANS, 12), justify="center", width=max(100, W - 80))
            return
        n = len(s.items)
        a, b = max(0, int(s.y // R)), min(n - 1, int((s.y + H) // R))
        fd = s.fade
        wide = W > 860
        rcol = 128  # ширина правой части (♥ + время)
        album_x = int(W * 0.56)
        for i in range(a, b + 1):
            t = s.items[i]
            # лёгкий «каскад» при смене списка: ряды появляются один за другим
            f = min(1.0, max(0.0, fd * 1.8 - (i - a) * 0.05)) if fd < 1 else 1.0
            top = i * R - s.y
            sel, hov, play = t["id"] in s.sel, i == s.hov, t["id"] == s.cur_id
            if sel or hov:
                rr(s, 6, top + 2, W - 14, top + R - 2, 10, fill=mix(C[s.pbg], C["elev"], (1 if sel else .6) * f), outline="")
            # обложка
            img = s.app.thumb(t, 44)
            if img:
                s.create_image(16, top + 7, image=img, anchor="nw")
            else:
                rr(s, 16, top + 7, 60, top + 51, 8, fill=mix(C[s.pbg], C["elev"], f), outline="")
            if play:
                rr(s, 16, top + 7, 60, top + 51, 8, fill="#000000", outline="", stipple="gray50")
                for k in range(3):
                    h = 6 + 16 * (0.5 + 0.5 * math.sin(s.phase * 0.9 + k * 2.1)) if s.eq_on else 8
                    x = 28 + k * 8
                    s.create_rectangle(x, top + 40 - h, x + 5, top + 40, fill=C["accent"], outline="")
            tx = 74
            maxw = W - tx - rcol - (int(W * 0.30) if wide else 12)
            col = C["accent"] if play else C["text"]
            title = fit(t["title"], s.TF, maxw - 26)
            s.create_text(tx, top + 21, text=title, anchor="w", fill=mix(C[s.pbg], col, f), font=s.TF)
            if t.get("exp"):
                ex = tx + _font(s.TF).measure(title) + 8
                rr(s, ex, top + 14, ex + 15, top + 28, 3, fill=mix(C[s.pbg], C["muted"], .5 * f), outline="")
                s.create_text(ex + 7.5, top + 21, text="E", font=(SANS, 7, "bold"), fill=C[s.pbg])
            art = t.get("artist") or UNKNOWN
            hot = i == s.hov and s.part == "artist"
            acol = C["text"] if hot else C["muted"]
            atxt = fit(art, s.AF, maxw)
            s.create_text(tx, top + 40, text=atxt, anchor="w", fill=mix(C[s.pbg], acol, f), font=s.AF)
            if hot:
                aw = _font(s.AF).measure(atxt)
                s.create_line(tx, top + 47, tx + aw, top + 47, fill=C["text"])
            if wide and t.get("album"):
                hot = i == s.hov and s.part == "album"
                alt = fit(t["album"], s.AF, int(W * 0.30) - 10)
                s.create_text(album_x, top + R / 2, text=alt, anchor="w", fill=mix(C[s.pbg], C["text"] if hot else C["muted"], f), font=s.AF)
                if hot:
                    s.create_line(album_x, top + R / 2 + 8, album_x + _font(s.AF).measure(alt), top + R / 2 + 8, fill=C["text"])
            # правая часть
            if t.get("fav") or hov or sel:
                hc = C["accent"] if t.get("fav") else (C["text"] if (hov and s.part == "heart") else C["muted"])
                s.create_text(W - 82, top + R / 2, text="♥" if t.get("fav") else "♡", font=FI, fill=hc)
            s.create_text(W - 30, top + R / 2, text=fmt(t.get("dur")), anchor="e", fill=mix(C[s.pbg], C["muted"], f), font=s.AF)

    # --- события
    def _hit(s, e):
        i = int((e.y + s.y) // s.ROW)
        if not (0 <= i < len(s.items)) or e.x >= s.W - 14:
            return -1, ""
        t = s.items[i]
        W, R = s.W, s.ROW
        ry = (e.y + s.y) - i * R
        if abs(e.x - (W - 82)) < 16:
            return i, "heart"
        tx = 74
        if 28 <= ry <= 50 and tx <= e.x <= tx + _font(s.AF).measure(trunc(t.get("artist") or UNKNOWN, 60)) and (t.get("artist") or UNKNOWN) != UNKNOWN:
            return i, "artist"
        if W > 860 and t.get("album") and int(W * 0.56) <= e.x <= int(W * 0.56) + _font(s.AF).measure(trunc(t["album"], 40)) and t.get("alid"):
            return i, "album"
        return i, "row"

    def _set_hover(s, i, part):
        if (i, part) != (s.hov, s.part):
            s.hov, s.part = i, part
            s.configure(cursor="hand2" if part in ("heart", "artist", "album") else "arrow")
            if not s._job:
                s.redraw()

    def _motion(s, e):
        s._set_hover(*s._hit(e))

    def _click(s, e):
        s.focus_set()
        if s.sb_hit(e):
            return
        i, part = s._hit(e)
        if i < 0:
            s.sel.clear()
            s.redraw()
            return
        t = s.items[i]
        if part == "heart":
            s.on_fav(t)
        elif part == "artist":
            s.on_artist(t)
        elif part == "album":
            s.on_album(t)
        else:
            if e.state & 0x1 and s.anchor >= 0:  # Shift — диапазон
                lo, hi = sorted((s.anchor, i))
                s.sel = {x["id"] for x in s.items[lo:hi + 1]}
            elif e.state & 0x4:  # Ctrl — добавить/убрать
                s.sel ^= {t["id"]}
                s.anchor = i
            else:
                s.sel = {t["id"]}
                s.anchor = i
            s.redraw()

    def _dbl(s, e):
        i, part = s._hit(e)
        if i >= 0 and part == "row":
            s.on_play(s.items[i])

    def _ctx(s, e):
        i, _ = s._hit(e)
        if i < 0:
            return
        if s.items[i]["id"] not in s.sel:
            s.sel = {s.items[i]["id"]}
            s.anchor = i
            s.redraw()
        s.on_menu(e, s.selected())

    def _key(s, d):
        if not s.items:
            return
        i = max(0, min(len(s.items) - 1, (s.anchor if s.anchor >= 0 else -1) + d))
        s.anchor, s.sel = i, {s.items[i]["id"]}
        top = i * s.ROW
        if top < s.y:
            s.scroll_to(top)
        elif top + s.ROW > s.y + s.H:
            s.scroll_to(top + s.ROW - s.H)
        s.redraw()


# ═════════════════════ сетка карточек (альбомы) ═════════════════════
class CardGrid(SmoothCanvas):
    CW, CH, GAP = 172, 238, 8

    def __init__(s, app, parent, pbg="panel"):
        super().__init__(app, parent, pbg)
        s.items, s.hov, s.empty = [], -1, ""
        s.on_click = lambda it: None
        s.bind("<Motion>", s._motion)
        s.bind("<Leave>", lambda e: s._hover(-1))
        s.bind("<Button-1>", s._press)

    def cols(s):
        return max(1, (s.W - 20) // (s.CW + s.GAP))

    def content_h(s):
        n = len(s.items)
        return ((n + s.cols() - 1) // s.cols()) * (s.CH + s.GAP) + 16 if n else 0

    def set_items(s, items):
        s.items, s.hov = items, -1
        s.y = s.ty = 0.0
        s.start_fade()
        s.redraw()

    def _idx(s, e):
        if e.x >= s.W - 14:
            return -1
        c = s.cols()
        col = int((e.x - 10) // (s.CW + s.GAP))
        row = int((e.y + s.y - 8) // (s.CH + s.GAP))
        i = row * c + col
        return i if 0 <= col < c and 0 <= i < len(s.items) else -1

    def _hover(s, i):
        if i != s.hov:
            s.hov = i
            s.configure(cursor="hand2" if i >= 0 else "arrow")
            if not s._job:
                s.redraw()

    def _motion(s, e):
        s._hover(s._idx(e))

    def _press(s, e):
        if s.sb_hit(e):
            return
        i = s._idx(e)
        if i >= 0:
            s.on_click(s.items[i])

    def paint(s):
        C, c = s.app.C, s.cols()
        if not s.items:
            if s.empty:
                s.create_text(s.W / 2, s.H / 3, text=s.empty, fill=C["muted"], font=(SANS, 12), width=max(100, s.W - 80))
            return
        a = max(0, int((s.y - 8) // (s.CH + s.GAP))) * c
        b = min(len(s.items), (int((s.y + s.H) // (s.CH + s.GAP)) + 1) * c)
        for i in range(a, b):
            it = s.items[i]
            row, col = divmod(i, c)
            x, y = 10 + col * (s.CW + s.GAP), 8 + row * (s.CH + s.GAP) - s.y
            f = min(1.0, max(0.0, s.fade * 1.6 - (i - a) * 0.04)) if s.fade < 1 else 1.0
            if i == s.hov:
                rr(s, x, y, x + s.CW, y + s.CH, 14, fill=mix(C[s.pbg], C["elev"], .8 * f), outline="")
            img = s.app.img(it.get("cover"), 148, 12)
            if img:
                s.create_image(x + 12, y + 12 + (-3 if i == s.hov else 0), image=img, anchor="nw")
            else:
                rr(s, x + 12, y + 12, x + 160, y + 160, 12, fill=mix(C[s.pbg], C["elev"], f), outline="")
            s.create_text(x + 14, y + 172, text=fit(it["title"], FB, s.CW - 28), anchor="nw", fill=mix(C[s.pbg], C["text"], f), font=FB)
            s.create_text(x + 14, y + 194, text=fit(it.get("sub", ""), FS, s.CW - 28), anchor="nw", fill=mix(C[s.pbg], C["muted"], f), font=FS)


# ═════════════════════ полоса исполнителей в результатах поиска ═════════════════════
class ArtistStrip(tk.Canvas):
    H = 92
    CW = 250

    def __init__(s, app, parent, pbg="panel"):
        super().__init__(parent, highlightthickness=0, bd=0, height=s.H, bg=app.C[pbg])
        s.app, s.pbg, s.items, s.hov = app, pbg, [], -1
        s.on_click = lambda a: None
        app.rec.append(s)
        s.bind("<Configure>", lambda e: s.draw())
        s.bind("<Motion>", lambda e: s._hover(s._idx(e)))
        s.bind("<Leave>", lambda e: s._hover(-1))
        s.bind("<Button-1>", lambda e: s._idx(e) >= 0 and s.on_click(s.items[s._idx(e)]))

    def set_items(s, items):
        s.items, s.hov = items, -1
        s.draw()

    def _idx(s, e):
        i = int((e.x - 18) // (s.CW + 10))
        return i if 0 <= i < len(s.items) and (e.x - 18) % (s.CW + 10) <= s.CW else -1

    def _hover(s, i):
        if i != s.hov:
            s.hov = i
            s.configure(cursor="hand2" if i >= 0 else "arrow")
            s.draw()

    def recolor(s):
        s.configure(bg=s.app.C[s.pbg])
        s.draw()

    def draw(s):
        s.delete("all")
        C = s.app.C
        for i, a in enumerate(s.items):
            x = 18 + i * (s.CW + 10)
            if x + s.CW > s.winfo_width() + 2 and i:
                break
            rr(s, x, 6, x + s.CW, s.H - 6, 16, fill=mix(C[s.pbg], C["elev"], .9 if i == s.hov else .45), outline="")
            img = s.app.img(a.get("pic_s"), 60, 30, circle=True)
            if img:
                s.create_image(x + 12, s.H / 2, image=img, anchor="w")
            else:
                s.create_oval(x + 12, s.H / 2 - 30, x + 72, s.H / 2 + 30, fill=C["elev"], outline="")
            s.create_text(x + 84, s.H / 2 - 11, text=fit(a["name"], FB, s.CW - 100), anchor="w", fill=C["text"], font=FB)
            s.create_text(x + 84, s.H / 2 + 11, text=f"Исполнитель · {human_num(a.get('fans'))} фанатов", anchor="w", fill=C["muted"], font=FS)
