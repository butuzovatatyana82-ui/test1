"""Okunek Music — главное окно: библиотека, поиск, карточки исполнителей, воспроизведение."""
import base64
import bisect
import hashlib
import io
import json
import os
import queue
import random
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from . import engine, filters as flt, updater
from .assets import ICON, LOGO
from .config import (APP, APP_NAME, COV, EXTS, F, FB, FH, FI, FIL, FS, SANS, SOURCES, THEMES, UNKNOWN, UPDATE_REPO, VERSION)
from .net import Deezer, fetch_lyrics, http_get, lastfm_stats, parse_lrc
from .store import Store
from .util import fmt, human_num, mix, safe_name, trunc
from .widgets import AButton, ArtistStrip, CardGrid, PillEntry, Slider, TrackList

try:
    from mutagen import File as MFile
except Exception:  # noqa: BLE001
    MFile = None
try:
    from PIL import Image, ImageDraw, ImageTk
except Exception:  # noqa: BLE001
    Image = ImageDraw = ImageTk = None

POOL = ThreadPoolExecutor(max_workers=8)
IMGPOOL = ThreadPoolExecutor(max_workers=4)


def embedded_art(p):
    try:
        a = MFile(p)
        if a is None:
            return None
        if getattr(a, "pictures", None):
            return a.pictures[0].data
        for k in (a.tags or {}).keys():
            if str(k).startswith("APIC"):
                return a.tags[k].data
        if a.tags and "covr" in a.tags:
            return bytes(a.tags["covr"][0])
    except Exception:  # noqa: BLE001
        pass
    return None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.store = Store()
        self.set = self.store.settings
        self.C = THEMES.get(self.set["theme"], THEMES["Okunek"])
        self.dz = Deezer()
        self.q, self.reg, self.rec = queue.Queue(), [], []
        # навигация и списки
        self.view, self.hist, self.rec_ids, self.results, self._pool = "lib", [], [], [], []
        self.artist, self.album, self.strip_items = None, None, []
        self.stitle, self.sq, self.pending, self.words = "Поиск", 0, 0, []
        self.scache, self._seen_lib, self._nav, self._ft, self._sv, self._st_job = {}, set(), None, None, None, None
        # воспроизведение
        self.queue, self.qi, self.cur = [], -1, None
        self.busy = self.loading = self.failed = False
        self.tok, self.fb_tok, self.fails, self.t0, self.t_start, self.limit = 0, -1, 0, 0, 0, 90
        self.vol_applied = True
        self.ltimes, self.lidx = [], -1
        # картинки
        self.icache, self.ipend, self.noimg, self._idirty, self.imgs = OrderedDict(), set(), set(), False, {}

        self.title(APP_NAME)
        self.geometry("1320x800")
        self.minsize(1080, 640)
        try:
            self.icon = tk.PhotoImage(data=ICON)
            self.iconphoto(True, self.icon)
        except Exception:  # noqa: BLE001
            pass
        self.vlc = engine.vlc
        self.inst = self.pl = None
        self.init_player()
        self.build()
        self.apply_theme()
        self.set_vol(self.set["vol"] or 80)
        self.go("lib")
        self.update_ctl()
        self.after(120, self.tick)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind_all("<space>", lambda e: None if isinstance(e.widget, (tk.Entry, tk.Text)) else self.toggle())
        self.bind_all("<Control-f>", lambda e: self.search.e.focus_set())
        self.bind_all("<Control-Right>", lambda e: self.step(1))
        self.bind_all("<Control-Left>", lambda e: self.step(-1))
        self.bind_all("<Alt-Left>", lambda e: self.back())
        self.after(1500, self.background_tasks)

    # ═════════════ плеер ═════════════
    def init_player(self):
        if not self.vlc:
            return
        try:
            self.inst = self.vlc.Instance("--no-video", "--quiet", "--network-caching=2000", "--http-reconnect")
            self.pl = self.inst.media_player_new()
        except Exception:  # noqa: BLE001
            self.inst = self.pl = None

    def need_vlc(self):
        if messagebox.askyesno("Нет VLC", "Для воспроизведения нужен VLC. Скачать портативную версию автоматически (≈ 45 МБ)?", parent=self):
            self.status("Скачиваю VLC…")

            def work():
                try:
                    v = engine.install_vlc(lambda m: self.post(lambda: self.status(m)),
                                           lambda p: self.post(lambda: self.status(f"Скачиваю VLC… {int(p * 100)}%")))
                    self.post(lambda: self.vlc_ready(v))
                except Exception as ex:  # noqa: BLE001
                    self.post(lambda ex=ex: messagebox.showerror("VLC", str(ex)[:300], parent=self))
            POOL.submit(work)

    def vlc_ready(self, v):
        self.vlc = v
        self.init_player()
        self.set_vol(self.set["vol"])
        self.status("VLC готов" if self.pl else "Не удалось запустить VLC")

    # ═════════════ служебное ═════════════
    def post(self, fn):
        self.q.put(fn)

    def save(self, now=False):
        if now:
            self._flush()
        elif not self._sv:
            self._sv = self.after(700, self._flush)

    def _flush(self):
        self._sv = None
        try:
            self.store.save()
        except Exception as e:  # noqa: BLE001
            self.status(f"Не удалось сохранить: {e}")

    def log(self):
        tb = traceback.format_exc()
        print(tb)
        try:
            os.makedirs(APP, exist_ok=True)
            with open(os.path.join(APP, "log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + tb + "\n")
        except Exception:  # noqa: BLE001
            pass
        self.status("Внутренняя ошибка (см. log.txt в папке данных)")

    def status(self, t, keep=False):
        self.stat.configure(text=t)
        if self._st_job:
            self.after_cancel(self._st_job)
            self._st_job = None
        if not keep and t:
            self._st_job = self.after(9000, lambda: self.stat.configure(text=""))

    def close(self):
        self.save(True)
        try:
            from .config import CACHE
            for f in os.listdir(CACHE):
                fp = os.path.join(CACHE, f)
                if time.time() - os.path.getmtime(fp) > 3 * 86400:
                    os.remove(fp)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.pl:
                self.pl.stop()
        except Exception:  # noqa: BLE001
            pass
        POOL.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    # ═════════════ фоновые задачи: движок и обновления ═════════════
    def background_tasks(self):
        def work():
            log = lambda m: self.post(lambda: self.status(m))  # noqa: E731
            if engine.update_ytdlp(log=log) == "new":
                self.post(lambda: self.status("Движок поиска обновлён — применится при следующем запуске"))
            if os.name == "nt" and not engine.find_js():
                engine.ensure_deno(log)
                self.post(lambda: self.status("JS-движок для YouTube готов"))
            if self.set.get("auto_update") and UPDATE_REPO:
                try:
                    u = updater.check()
                    if u:
                        self.post(lambda: self.offer_update(u))
                except Exception as ex:  # noqa: BLE001
                    print("update check:", ex)
        POOL.submit(work)

    def offer_update(self, u):
        if messagebox.askyesno("Обновление", f"Доступна версия {u['version']} (у вас {VERSION}).\n\n{u['notes']}\n\nУстановить сейчас? Плеер перезапустится сам.", parent=self):
            self.status("Скачиваю обновление…", True)

            def work():
                try:
                    updater.install(u["url"], lambda p: self.post(lambda: self.status(f"Скачиваю обновление… {int(p * 100)}%", True)))
                    self.post(self.close)
                except Exception as ex:  # noqa: BLE001
                    self.post(lambda ex=ex: messagebox.showerror("Обновление", str(ex)[:300], parent=self))
            POOL.submit(work)

    def manual_update(self):
        if not UPDATE_REPO:
            messagebox.showinfo("Обновления", "Адрес обновлений не задан. Укажите UPDATE_REPO в okunek/config.py (см. README.md).", parent=self)
            return
        self.status("Проверяю обновления…")

        def work():
            try:
                u = updater.check()
                self.post(lambda: self.offer_update(u) if u else self.status("У вас последняя версия"))
            except Exception as ex:  # noqa: BLE001
                self.post(lambda ex=ex: self.status("Не удалось проверить: " + str(ex)[:60]))
        POOL.submit(work)

    def refresh_components(self):
        self.status("Обновляю компоненты…", True)

        def work():
            log = lambda m: self.post(lambda: self.status(m, True))  # noqa: E731
            r = engine.update_ytdlp(True, log)
            d = engine.ensure_deno(log)
            self.post(lambda: messagebox.showinfo("Компоненты", f"yt-dlp: {'обновлён (применится после перезапуска)' if r == 'new' else 'актуален' if r == 'same' else 'ошибка сети'}\nDeno: {'есть' if d else 'нет'}", parent=self))
            self.post(lambda: self.status(""))
        POOL.submit(work)

    # ═════════════ картинки ═════════════
    def _cover_file(self, src):
        key = hashlib.sha1(src.encode()).hexdigest()[:18]
        p = os.path.join(COV, key + ".jpg")
        if os.path.exists(p):
            return p
        data = embedded_art(src[6:]) if src.startswith("local:") else http_get(src, 12, 2)
        if not data:
            return None
        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((320, 320), Image.LANCZOS)
        os.makedirs(COV, exist_ok=True)
        im.save(p, "JPEG", quality=88)
        return p

    def img(self, src, size, r=0, circle=False):
        """PhotoImage из кэша; если ещё нет — запускает фоновую загрузку и возвращает None."""
        if not src or not Image:
            return None
        key = (src, size, r, circle)
        v = self.icache.get(key)
        if v is not None:
            self.icache.move_to_end(key)
            return v
        if key in self.ipend or src in self.noimg:
            return None
        self.ipend.add(key)

        def work():
            pil = None
            try:
                p = self._cover_file(src)
                if p:
                    im = Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS)
                    m = Image.new("L", (size * 3, size * 3), 0)  # 3× — сглаженные края скругления
                    d = ImageDraw.Draw(m)
                    (d.ellipse((0, 0, size * 3 - 1, size * 3 - 1), fill=255) if circle else d.rounded_rectangle((0, 0, size * 3 - 1, size * 3 - 1), r * 3, fill=255))
                    im.putalpha(m.resize((size, size), Image.LANCZOS))
                    pil = im
            except Exception:  # noqa: BLE001
                pass
            self.post(lambda: self._img_done(key, pil))
        IMGPOOL.submit(work)
        return None

    def _img_done(self, key, pil):
        self.ipend.discard(key)
        if pil is None:
            self.noimg.add(key[0])
            return
        self.icache[key] = ImageTk.PhotoImage(pil)
        while len(self.icache) > 900:
            self.icache.popitem(last=False)
        if not self._idirty:
            self._idirty = True
            self.after(50, self._img_flush)

    def _img_flush(self):
        self._idirty = False
        for w in (self.tl, self.cards, self.strip):
            if w.winfo_ismapped():
                w.redraw() if hasattr(w, "redraw") else w.draw()
        self.hero_draw()
        self.set_covers()

    def thumb(self, t, size):
        src = t.get("cover") or (f"local:{t['src']}" if t.get("kind") == "local" else None)
        return self.img(src, size, 8)

    def placeholder(self, size, r):
        key = ("ph", size, r, self.set["theme"])
        v = self.icache.get(key)
        if v is None and Image:
            C = self.C
            im = Image.new("RGBA", (size, size), mix(C["elev"], C["elev"], 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((0, 0, size - 1, size - 1), r, fill=C["elev"])
            q = size // 5
            d.ellipse((size // 2 - q, size // 2 - q, size // 2 + q, size // 2 + q), fill=mix(C["elev"], C["muted"], .5))
            v = self.icache[key] = ImageTk.PhotoImage(im)
        return v

    def set_covers(self):
        if not Image:
            return
        src = None
        if self.cur:
            src = self.cur.get("cover") or (f"local:{self.cur['src']}" if self.cur.get("kind") == "local" else None)
        s = self.img(src, 60, 8) or self.placeholder(60, 8)
        b = self.img(src, 250, 14) or self.placeholder(250, 14)
        self.cov.configure(image=s)
        self.pcov.configure(image=b)
        self.cov.image, self.pcov.image = s, b

    # ═════════════ конструкторы виджетов ═════════════
    def R(self, w, **roles):
        self.reg.append((w, roles))
        return w

    def Fr(self, parent, bg="panel", **kw):
        return self.R(tk.Frame(parent, bd=0, highlightthickness=0, **kw), bg=bg)

    def L(self, parent, bg="panel", fg="text", **kw):
        return self.R(tk.Label(parent, bd=0, **kw), bg=bg, fg=fg)

    def Bt(self, parent, text, cmd, **kw):
        return AButton(self, parent, text, cmd, **kw)

    def build(self):
        bar = self.Fr(self, "bg")
        bar.pack(side="bottom", fill="x")
        self.side = self.Fr(self, "panel", width=268)
        self.side.pack(side="left", fill="y", padx=(8, 0), pady=8)
        self.side.pack_propagate(False)
        self.lp = self.Fr(self, "panel", width=340)
        self.lp.pack_propagate(False)
        self.main = self.Fr(self, "panel")
        self.main.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        if self.set["lyrics"]:
            self.lp.pack(side="right", fill="y", padx=(0, 8), pady=8, before=self.main)

        # боковая панель
        self.logo = None
        try:
            if Image:
                im = Image.open(io.BytesIO(base64.b64decode(LOGO))).convert("RGBA")
                w = 150
                self.logo = ImageTk.PhotoImage(im.resize((w, round(im.height * w / im.width)), Image.LANCZOS))
            else:
                self.logo = tk.PhotoImage(data=LOGO)
        except Exception:  # noqa: BLE001
            pass
        if self.logo:
            self.L(self.side, image=self.logo).pack(pady=(16, 8))
        self.nav = self.Fr(self.side)
        self.nav.pack(fill="x", padx=10)
        pr = self.Fr(self.side)
        pr.pack(fill="x", padx=18, pady=(14, 2))
        self.L(pr, fg="muted", text="ПЛЕЙЛИСТЫ", font=(SANS, 9, "bold")).pack(side="left")
        self.Bt(pr, "＋", self.new_pl, w=30, h=30, font=FI).pack(side="right")
        self.pnav = self.Fr(self.side)
        self.pnav.pack(fill="both", expand=True, padx=10)
        sb = self.Fr(self.side)
        sb.pack(fill="x", padx=14, pady=(4, 14))
        self.bth = self.Bt(sb, "", self.theme_menu, h=34, kind="pill", font=F)
        self.bth.pack(side="left", fill="x", expand=True)
        self.Bt(sb, "⚙", self.settings_menu, w=36, h=34, font=FI).pack(side="left", padx=(6, 0))

        # центр: поиск
        self.top = self.Fr(self.main)
        self.top.pack(fill="x", padx=18, pady=(16, 0))
        self.bback = self.Bt(self.top, "‹", self.back, w=40, h=40, font=(SANS, 20), kind="pill")
        self.flt = tk.StringVar()
        self.flt.trace_add("write", lambda *_: self.defer_render())
        self.search = PillEntry(self, self.top, self.flt, on_enter=lambda: self.web_search(self.flt.get().strip()))
        self.search.pack(side="left", fill="x", expand=True)
        self.Bt(self.top, "Найти", lambda: self.web_search(self.flt.get().strip()), w=86, h=40, kind="primary", font=FB).pack(side="left", padx=(10, 0))
        self.chu = self.Bt(self.top, "Без цензуры", self.toggle_unc, w=116, h=34, kind="pill")
        self.chu.pack(side="left", padx=(10, 0))
        self.cor = self.Bt(self.top, "Оригиналы", self.toggle_orig, w=110, h=34, kind="pill")
        self.cor.pack(side="left", padx=(6, 0))
        self.chs = self.Bt(self.top, "", self.src_menu, w=190, h=34, kind="pill")
        self.chs.pack(side="left", padx=(6, 0))

        self.hero = tk.Canvas(self.main, height=156, highlightthickness=0, bd=0)
        self.hero.pack(fill="x", pady=(12, 0))
        self.hero.bind("<Configure>", lambda e: self.hero_draw())

        self.actwrap = self.Fr(self.main)
        self.actwrap.pack(fill="x", padx=18, pady=(2, 6))
        self.stat = self.L(self.actwrap, fg="muted", font=F, anchor="e")
        self.stat.pack(side="right")
        self.bplay = self.Bt(self.actwrap, "▶", self.play_first, w=52, h=52, kind="primary", font=FIL)
        self.bplay.pack(side="left")
        self.act_lib = self.Fr(self.actwrap)
        self.act_lib.pack(side="left")
        for t, c in (("Похожее на мои вкусы", self.discover), ("+ Файлы", self.add_files), ("+ Папка", self.add_folder)):
            self.Bt(self.act_lib, t, c, h=34, kind="pill", w=len(t) * 8 + 36).pack(side="left", padx=(10, 0))
        self.act_art = self.Fr(self.actwrap)
        self.tabs = {}
        for key, name in (("top", "Популярное"), ("all", "Все песни"), ("albums", "Альбомы")):
            b = self.Bt(self.act_art, name, lambda k=key: self.set_tab(k), h=34, kind="pill", w=len(name) * 9 + 34)
            b.pack(side="left", padx=(10, 0))
            self.tabs[key] = b
        self.Bt(self.act_art, "🔀 Перемешать", self.play_shuffled, h=34, kind="pill", w=140).pack(side="left", padx=(10, 0))

        self.body = self.Fr(self.main)
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.strip = ArtistStrip(self, self.body)
        self.strip.on_click = lambda a: self.open_artist(a["id"], a)
        self.tl = TrackList(self, self.body)
        self.tl.on_play = lambda t: self.play_track(t, self.items())
        self.tl.on_menu = self.popup
        self.tl.on_fav = lambda t: self.toggle_fav([t])
        self.tl.on_artist = self.open_artist_for
        self.tl.on_album = self.open_album_for
        self.tl.on_delete = self.remove
        self.cards = CardGrid(self, self.body)
        self.cards.on_click = lambda it: self.open_album(it["id"], it)
        self.tl.pack(fill="both", expand=True)

        # правая панель: обложка и текст
        self.pcov = self.L(self.lp)
        self.pcov.pack(pady=(18, 8))
        self.ptitle = self.L(self.lp, font=(SANS, 13, "bold"), wraplength=300, justify="center")
        self.ptitle.pack(padx=14)
        self.txt = self.R(tk.Text(self.lp, wrap="word", bd=0, highlightthickness=0, padx=18, pady=10, font=(SANS, 12), cursor="arrow", state="disabled", spacing1=5, spacing3=5),
                          bg="panel", fg="muted", selectbackground="elev")
        self.txt.pack(fill="both", expand=True, pady=(8, 8))

        # нижняя панель
        bar.columnconfigure((0, 2), weight=1, uniform="a")
        bar.columnconfigure(1, weight=2)
        lf = self.Fr(bar, "bg")
        lf.grid(row=0, column=0, sticky="w", padx=14, pady=10)
        self.cov = self.L(lf, "bg")
        self.cov.pack(side="left", padx=(0, 12))
        tf = self.Fr(lf, "bg")
        tf.pack(side="left")
        self.now = self.L(tf, "bg", font=FB, anchor="w", justify="left")
        self.now.pack(anchor="w")
        self.nowa = self.L(tf, "bg", "muted", font=FS, anchor="w", cursor="hand2")
        self.nowa.pack(anchor="w")
        self.nowa.bind("<Button-1>", lambda e: self.cur and self.open_artist_for(self.cur))
        self.bheart = self.Bt(lf, "♡", self.heart, w=34, h=34, font=FI, pbg="bg")
        self.bheart.pack(side="left", padx=(10, 0))
        mid = self.Fr(bar, "bg")
        mid.grid(row=0, column=1, pady=8)
        row = self.Fr(mid, "bg")
        row.pack()
        self.bsh = self.Bt(row, "🔀", self.toggle_shuffle, w=40, h=40, font=FI, pbg="bg")
        self.bsh.pack(side="left", padx=3)
        self.Bt(row, "⏮", lambda: self.step(-1), w=40, h=40, font=FIL, pbg="bg").pack(side="left", padx=3)
        self.bpp = self.Bt(row, "▶", self.toggle, w=46, h=46, kind="primary", font=FIL, pbg="bg")
        self.bpp.pack(side="left", padx=8)
        self.Bt(row, "⏭", lambda: self.step(1), w=40, h=40, font=FIL, pbg="bg").pack(side="left", padx=3)
        self.brp = self.Bt(row, "🔁", self.cycle_rep, w=40, h=40, font=FI, pbg="bg")
        self.brp.pack(side="left", padx=3)
        sk = self.Fr(mid, "bg")
        sk.pack(fill="x")
        self.cu = self.L(sk, "bg", "muted", text="0:00", width=5, font=FS)
        self.cu.pack(side="left")
        self.seek = Slider(self, sk, cmd=lambda v: self.cu.configure(text=fmt(v * self.pl.get_length() / 1000) if self.pl else "0:00"), rel=self.on_seek, pbg="bg", w=380)
        self.seek.pack(side="left", fill="x", expand=True)
        self.du = self.L(sk, "bg", "muted", text="0:00", width=5, font=FS)
        self.du.pack(side="left")
        vf = self.Fr(bar, "bg")
        vf.grid(row=0, column=2, sticky="e", padx=14)
        self.blyr = self.Bt(vf, "Текст", self.toggle_lyrics, w=70, h=32, kind="pill", pbg="bg")
        self.blyr.pack(side="left", padx=(0, 6))
        self.Bt(vf, "☰", lambda: self.go("queue"), w=36, h=36, font=FI, pbg="bg").pack(side="left", padx=(0, 10))
        self.L(vf, "bg", "muted", text="🔊", font=FI).pack(side="left")
        self.vol = Slider(self, vf, cmd=lambda v: self.set_vol(v * 100), rel=lambda v: self.save(), pbg="bg", w=110)
        self.vol.pack(side="left")

    def apply_theme(self):
        C = self.C
        self.configure(bg=C["bg"])
        self.reg = [(w, r) for w, r in self.reg if w.winfo_exists()]
        self.rec = [w for w in self.rec if w.winfo_exists()]
        for w, r in self.reg:
            w.configure(**{k: C[v] for k, v in r.items()})
        for w in self.rec:
            w.recolor()
        self.txt.tag_configure("cur", foreground=C["text"], font=(SANS, 15, "bold"))
        self.hero.configure(bg=C["panel"])
        self._nav = None
        self.hero_draw()
        self.refresh_nav()
        self.update_ctl()
        self.set_covers()
        self.bth.set_text("Тема: " + self.set["theme"] + " ▾")

    # ═════════════ шапка (hero) ═════════════
    def hero_info(self):
        v = self.view
        if v == "artist" and self.artist:
            a, i = self.artist, self.artist.get("info") or {}
            parts = []
            if i:
                parts.append(f"{human_num(i.get('fans'))} фанатов на Deezer")
                parts.append(f"{i.get('albums', 0)} релизов")
            st = a.get("stats", {})
            if st.get("lfm"):
                parts.append(f"{human_num(st['lfm']['listeners'])} слушателей Last.fm")
            if st.get("avg") is not None:
                parts.append(f"≈ {human_num(st['avg'])} просмотров на трек (YouTube, топ)" if st["avg"] else "просмотры не найдены")
            elif i:
                parts.append("считаю среднее число прослушиваний…")
            return (a["name"], "  ·  ".join(parts) if parts else "Загружаю…", i.get("pic") or a.get("pic"), True)
        if v == "album" and self.album:
            al = self.album
            return (al["title"], f"{al.get('artist', '')}  ·  {(al.get('date') or '')[:4]}  ·  {len(al['tracks'])} треков".replace("  ·  ·", "  ·"), al.get("cover"), False)
        names = {"lib": "Все треки", "fav": "Любимые", "rec": "Рекомендации", "search": self.stitle, "queue": "Очередь"}
        p = self.store.playlist(v[3:]) if v.startswith("pl:") else None
        n = len(self.tl.items) if hasattr(self, "tl") else 0
        return (p["name"] if p else names.get(v, ""), f"{n} треков", None, False)

    def hero_draw(self):
        h, c = self.hero, self.C
        w = h.winfo_width()
        if w < 10:
            return
        H = 156
        title, sub, src, circle = self.hero_info()
        h.delete("all")
        top = mix(c["panel"], c["accent"], .5)
        for y in range(0, H, 2):
            h.create_rectangle(0, y, w, y + 2, fill=mix(top, c["panel"], (y / H) ** .8), outline="")
        x = 28
        if self.view in ("artist", "album"):
            img = self.img(src, 112, 56 if circle else 14, circle) if src else None
            if img:
                h.create_image(28, H / 2, image=img, anchor="w")
            else:
                h.create_oval(28, H / 2 - 56, 140, H / 2 + 56, fill=c["elev"], outline="") if circle else h.create_rectangle(28, H / 2 - 56, 140, H / 2 + 56, fill=c["elev"], outline="")
            x = 160
        kind = {"artist": "ИСПОЛНИТЕЛЬ", "album": "АЛЬБОМ"}.get(self.view, "")
        if kind:
            h.create_text(x, 34, text=kind, anchor="w", font=(SANS, 9, "bold"), fill=mix(c["text"], c["panel"], .25))
        h.create_text(x, H / 2 - 4, text=trunc(title, 34), anchor="w", font=FH if len(title) < 22 else (SANS, 24, "bold"), fill=c["text"])
        h.create_text(x + 2, H / 2 + 34, text=trunc(sub, 120), anchor="w", font=F, fill=mix(c["text"], c["panel"], .3))

    # ═════════════ меню ═════════════
    def menu(self):
        C = self.C
        return tk.Menu(self, tearoff=0, bg=C["elev"], fg=C["text"], activebackground=C["accent"], activeforeground=C["atext"], bd=0, relief="flat", font=F)

    def theme_menu(self):
        m = self.menu()
        for n in THEMES:
            m.add_command(label=("✓  " if n == self.set["theme"] else "     ") + n, command=lambda n=n: self.set_theme(n))
        m.tk_popup(self.bth.winfo_rootx(), self.bth.winfo_rooty() - 6 - 30 * len(THEMES))

    def set_theme(self, n):
        self.set["theme"] = n
        self.C = THEMES[n]
        self.apply_theme()
        self.save()

    def src_menu(self):
        m = self.menu()
        for n in SOURCES:
            m.add_command(label=("✓  " if n == self.set["src"] else "     ") + n, command=lambda n=n: self.set_src(n))
        m.tk_popup(self.chs.winfo_rootx(), self.chs.winfo_rooty() + 38)

    def set_src(self, n):
        self.set["src"] = n
        self.save()
        self.update_ctl()
        self.status(f"Источник: {n}")

    def settings_menu(self):
        m = self.menu()
        items = (("Папка загрузок…", self.pick_dl), ("Импорт плейлиста…", self.import_pl),
                 ("Ключ Last.fm (для числа слушателей)…", self.ask_lastfm), (None, None),
                 ("Проверить обновления программы", self.manual_update), ("Обновить компоненты (поиск, YouTube)", self.refresh_components),
                 ("Скачать / переустановить VLC", self.need_vlc), (None, None),
                 ("Диагностика", self.diagnose), ("Открыть папку данных", self.open_data))
        for lb, c in items:
            m.add_separator() if lb is None else m.add_command(label=lb, command=c)
        m.tk_popup(self.bth.winfo_rootx(), self.bth.winfo_rooty() - 260)

    def open_data(self):
        if os.name == "nt" and os.path.isdir(APP):
            os.startfile(APP)  # noqa: S606

    def ask_lastfm(self):
        k = simpledialog.askstring("Last.fm", "Бесплатный API-ключ с last.fm/api (необязательно).\nДаёт число слушателей и прослушиваний в карточке исполнителя:", initialvalue=self.set.get("lastfm_key", ""), parent=self)
        if k is not None:
            self.set["lastfm_key"] = k.strip()
            self.save()

    def toggle_unc(self):
        self.set["uncens"] = not self.set["uncens"]
        self.save()
        self.update_ctl()
        self.status("Без «чистых» версий: " + ("вкл" if self.set["uncens"] else "выкл"))

    def toggle_orig(self):
        self.set["originals"] = not self.set["originals"]
        self.save()
        self.update_ctl()
        self.status("Только оригиналы (без ремиксов, мэшапов, каверов, лайвов): " + ("вкл" if self.set["originals"] else "выкл"))

    def pick_dl(self):
        d = filedialog.askdirectory(title="Куда скачивать", initialdir=self.set["dl"])
        if d:
            self.set["dl"] = d
            self.save()
            self.status("Загрузки: " + d)

    # ═════════════ списки и навигация ═════════════
    def items(self):
        v, s = self.view, self.store
        if v == "lib":
            lst = s.tracks
        elif v == "fav":
            lst = [t for t in s.tracks if t["fav"]]
        elif v == "rec":
            lst = [t for t in map(s.get, self.rec_ids) if t]
        elif v == "search":
            lst = self.results
        elif v == "queue":
            lst = self.queue
        elif v == "artist":
            a = self.artist
            lst = (a["top"] if a["tab"] == "top" else a["all"] or []) if a else []
        elif v == "album":
            lst = self.album["tracks"] if self.album else []
        else:
            p = s.playlist(v[3:])
            lst = [t for t in map(s.get, p["ids"]) if t] if p else []
        k = "" if v == "search" else self.flt.get().strip().lower()
        return [t for t in lst if k in (t["title"] + " " + t["artist"]).lower()] if k else list(lst)

    def defer_render(self):
        if self._ft:
            self.after_cancel(self._ft)
        self._ft = self.after(160, lambda: self.render(keep=False))

    def layout_body(self, strip, mode):
        for w in (self.strip, self.tl, self.cards):
            w.pack_forget()
        if strip:
            self.strip.pack(fill="x", pady=(0, 4))
        (self.cards if mode == "grid" else self.tl).pack(fill="both", expand=True)

    def render(self, keep=False):
        v = self.view
        art, alb = v == "artist", v == "album"
        grid = art and self.artist and self.artist["tab"] == "albums"
        self.layout_body(v == "search" and bool(self.strip_items), "grid" if grid else "list")
        for f in (self.act_lib, self.act_art):
            f.pack_forget()
        (self.act_art if art else self.act_lib).pack(side="left")
        if art:
            for k, b in self.tabs.items():
                b.set_active(self.artist["tab"] == k)
        if self.hist and not self.bback.winfo_ismapped():
            self.bback.pack(side="left", padx=(0, 10), before=self.search)
        elif not self.hist and self.bback.winfo_ismapped():
            self.bback.pack_forget()
        if grid:
            al = self.artist["albums"]
            self.cards.empty = "Загружаю альбомы…" if al is None else "Альбомы не найдены"
            self.cards.set_items([dict(id=a["id"], title=a["title"], cover=a["cover"], date=a["date"], type=a["type"], artist=self.artist["name"],
                                      sub=f"{(a['date'] or '')[:4]} · {dict(album='Альбом', single='Сингл', ep='EP').get(a['type'], a['type'])}") for a in (al or [])])
        else:
            self.tl.empty = self.empty_text()
            self.tl.set_items(self.items(), keep)
        self.tl.set_playing(self.cur["id"] if self.cur else None, self.is_playing())
        self.hero_draw()
        self.refresh_nav()

    def empty_text(self):
        v = self.view
        if v == "search":
            return "Ищу…" if self.pending > 0 else "Введите исполнителя или песню выше и нажмите Enter.\nМожно вставить ссылку на любой трек или плейлист."
        if v == "artist":
            a = self.artist
            if a["tab"] == "all" and a["all"] is None:
                return a.get("progress") or "Собираю дискографию…"
            if a["tab"] == "top" and not a["top"]:
                return "Загружаю…" if not a.get("loaded") else "Треков не найдено"
        if v == "album" and self.album and not self.album["tracks"]:
            return "Загружаю…"
        if v == "lib":
            return "Библиотека пуста.\nДобавьте файлы или папку, либо найдите музыку поиском."
        if v == "fav":
            return "Нажмите ♡ у трека, чтобы он появился здесь."
        return "Здесь пока пусто."

    def fill(self, keep=True):  # совместимое имя: перерисовать список, не сбрасывая прокрутку
        self.render(keep)

    def refresh(self):
        self._nav = None
        self.render(True)

    def refresh_nav(self):
        sig = (self.view, len(self.store.tracks), len(self.queue), tuple((p["id"], p["name"], len(p["ids"])) for p in self.store.d["pls"]), self.set["theme"])
        if sig == self._nav:
            return
        self._nav = sig
        for fr in (self.nav, self.pnav):
            for w in fr.winfo_children():
                w.destroy()
        self.rec = [w for w in self.rec if w.winfo_exists()]

        def nb(parent, text, v, pid=None):
            b = self.Bt(parent, text, lambda: self.go(v), h=38, kind="nav", align="w", font=FB if self.view == v else F)
            b.set_active(self.view == v)
            b.pack(fill="x", pady=1)
            if pid:
                b.bind("<Button-3>", lambda e: self.pl_menu(e, pid))
        for t, v in (("⌕   Результаты поиска", "search"), (f"♫   Все треки  ·  {len(self.store.tracks)}", "lib"), ("✦   Рекомендации", "rec"),
                     ("♥   Любимые", "fav"), (f"☰   Очередь  ·  {len(self.queue)}", "queue")):
            nb(self.nav, t, v)
        for p in self.store.d["pls"]:
            nb(self.pnav, f"▸   {trunc(p['name'], 22)}  ·  {len(p['ids'])}", "pl:" + p["id"], p["id"])

    def go(self, v):
        """Переход из бокового меню: сбрасывает историю «назад»."""
        self.view = v
        self.hist = []
        if v == "rec":
            self.make_recs()
        self._nav = None
        self.render()

    def push(self):
        self.hist.append((self.view, self.artist, self.album))
        self.hist = self.hist[-20:]

    def back(self):
        if self.hist:
            self.view, self.artist, self.album = self.hist.pop()
            self._nav = None
            self.render()

    # ═════════════ плейлисты ═════════════
    def new_pl(self):
        n = simpledialog.askstring("Новый плейлист", "Название:", parent=self)
        if n and n.strip():
            p = self.store.new_playlist(n.strip())
            self.save()
            self.go("pl:" + p["id"])

    def pl_menu(self, e, pid):
        m = self.menu()
        for lb, c in (("Переименовать", self.rename_pl), ("Экспорт в файл…", self.export_pl), ("Удалить плейлист", self.del_pl)):
            m.add_command(label=lb, command=lambda c=c: c(pid))
        m.tk_popup(e.x_root, e.y_root)

    def rename_pl(self, pid):
        p = self.store.playlist(pid)
        n = simpledialog.askstring("Переименовать", "Новое название:", initialvalue=p["name"], parent=self)
        if n and n.strip():
            p["name"] = n.strip()
            self.save()
            self.refresh()

    def del_pl(self, pid):
        if messagebox.askyesno("Удалить плейлист", "Удалить плейлист? Сами треки останутся в библиотеке.", parent=self):
            self.store.d["pls"] = [p for p in self.store.d["pls"] if p["id"] != pid]
            if self.view == "pl:" + pid:
                self.view = "lib"
            self.save()
            self.refresh()

    def export_pl(self, pid):
        p = self.store.playlist(pid)
        f = filedialog.asksaveasfilename(defaultextension=".json", initialfile=p["name"] + ".json", filetypes=[("Плейлист Okunek", "*.json")])
        if not f:
            return
        ks = ("kind", "src", "title", "artist", "dur", "cover", "exp", "album", "aid", "alid", "did", "cat", "tags")
        data = {"okunek_playlist": 1, "name": p["name"], "tracks": [{k: t.get(k) for k in ks} for t in map(self.store.get, p["ids"]) if t]}
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        self.status("Плейлист сохранён: " + os.path.basename(f))

    def import_pl(self):
        f = filedialog.askopenfilename(filetypes=[("Плейлист Okunek", "*.json")])
        if not f:
            return
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            assert data.get("okunek_playlist")
        except Exception:  # noqa: BLE001
            messagebox.showerror("Импорт", "Это не файл плейлиста Okunek.", parent=self)
            return
        p = self.store.new_playlist(data.get("name", "Импорт"))
        for x in data["tracks"]:
            x = {k: v for k, v in x.items() if v is not None}
            tid = "dz" + x["src"][3:] if x.get("kind") == "cat" else hashlib.sha1(x["src"].encode()).hexdigest()[:16]
            t = self.store.ensure(dict(id=tid, plays=0, fav=False, last=0, **x))
            if t["id"] not in p["ids"]:
                p["ids"].append(t["id"])
        self.save()
        self.go("pl:" + p["id"])

    def ensure_lib(self, t):
        return self.store.ensure(t)

    def add_to_pl(self, p, ts):
        for t in ts:
            t = self.ensure_lib(t)
            if t["id"] not in p["ids"]:
                p["ids"].append(t["id"])
        self.save()
        self.refresh()
        self.status(f"Добавлено в «{p['name']}»")

    # ═════════════ действия над треками ═════════════
    def toggle_fav(self, ts):
        for t in ts:
            x = self.ensure_lib(t)
            x["fav"] = not x["fav"]
            t["fav"] = x["fav"]
        self.save()
        self.refresh()
        self.update_ctl()

    def heart(self):
        if self.cur:
            self.toggle_fav([self.cur])

    def remove(self, ts):
        if not ts:
            return
        ids = {t["id"] for t in ts}
        v = self.view
        if v.startswith("pl:"):
            p = self.store.playlist(v[3:])
            p["ids"] = [i for i in p["ids"] if i not in ids]
        elif v == "queue":
            ct = self.queue[self.qi] if 0 <= self.qi < len(self.queue) else None
            self.queue = [t for t in self.queue if t["id"] not in ids]
            self.qi = self.queue.index(ct) if ct in self.queue else min(self.qi, len(self.queue) - 1)
        elif v in ("search", "artist", "album"):
            return
        else:
            if not messagebox.askyesno("Удалить", f"Удалить из библиотеки: {len(ts)} шт.?", parent=self):
                return
            self.store.remove(ids)
        self.save()
        self.refresh()

    def enqueue(self, ts, nxt):
        if not self.cur:
            self.play_track(ts[0], ts)
            return
        if nxt:
            self.queue[self.qi + 1:self.qi + 1] = ts
        else:
            self.queue.extend(ts)
        self.refresh()
        self.status(f"В очереди: {len(self.queue) - self.qi - 1}")

    def edit_meta(self, t):
        t = self.ensure_lib(t)
        n = simpledialog.askstring("Название", "Название трека:", initialvalue=t["title"], parent=self)
        if n is None:
            return
        a = simpledialog.askstring("Исполнитель", "Исполнитель:", initialvalue=t["artist"], parent=self)
        if n.strip():
            t["title"] = n.strip()
        if a and a.strip():
            t["artist"] = a.strip()
        self.save()
        self.refresh()

    def popup(self, e, ts):
        if not ts:
            return
        t0 = ts[0]
        m = self.menu()
        m.add_command(label="Играть", command=lambda: self.play_track(t0, self.items()))
        m.add_command(label="Играть следующим", command=lambda: self.enqueue(ts, True))
        m.add_command(label="В очередь", command=lambda: self.enqueue(ts, False))
        m.add_command(label="Любимое ♥", command=lambda: self.toggle_fav(ts))
        sub = self.menu()
        for p in self.store.d["pls"]:
            sub.add_command(label=p["name"], command=lambda p=p: self.add_to_pl(p, ts))
        if not self.store.d["pls"]:
            sub.add_command(label="(сначала создайте плейлист)", state="disabled")
        m.add_cascade(label="В плейлист", menu=sub)
        m.add_separator()
        if t0.get("artist") and t0["artist"] != UNKNOWN:
            m.add_command(label=f"Об исполнителе: {trunc(t0['artist'], 28)}", command=lambda: self.open_artist_for(t0))
        if t0.get("alid"):
            m.add_command(label=f"Открыть альбом: {trunc(t0.get('album', ''), 28)}", command=lambda: self.open_album_for(t0))
        m.add_command(label="Найти версию без цензуры", command=lambda: self.find_explicit(t0))
        m.add_command(label="Изменить название / исполнителя", command=lambda: self.edit_meta(t0))
        if any(t["kind"] != "local" for t in ts):
            m.add_command(label="Скачать", command=lambda: self.download(ts))
        if self.view in ("search", "artist", "album"):
            m.add_command(label="В библиотеку", command=lambda: ([self.ensure_lib(t) for t in ts], self.save(), self.refresh(), self.status("Добавлено в библиотеку")))
        else:
            m.add_command(label="Убрать" if self.view == "queue" or self.view.startswith("pl:") else "Удалить из библиотеки", command=lambda: self.remove(ts))
        m.tk_popup(e.x_root, e.y_root)

    # ═════════════ локальные файлы ═════════════
    def local_track(self, p):
        base = os.path.splitext(os.path.basename(p))[0].replace("_", " ").strip()
        title, artist, dur, album = base, UNKNOWN, 0, ""
        if " - " in base:
            artist, title = [x.strip() for x in base.split(" - ", 1)]
        if MFile:
            try:
                a = MFile(p, easy=True)
                if a is not None:
                    title = (a.get("title") or [title])[0]
                    artist = (a.get("artist") or [artist])[0]
                    album = (a.get("album") or [""])[0]
                    dur = a.info.length
            except Exception:  # noqa: BLE001
                pass
        return dict(id=uuid.uuid4().hex, kind="local", src=p, title=title, artist=artist, album=album, dur=dur, plays=0, fav=False, last=0, exp=bool(flt.GOOD.search(base)))

    def add_paths(self, paths):
        have = set(self.store.by_src)
        todo = [p for p in paths if p.lower().endswith(EXTS) and p not in have]
        self.status(f"Читаю теги: {len(todo)}…", True)

        def work():
            ts = [self.local_track(p) for p in todo]
            self.post(lambda: self._added(ts))
        POOL.submit(work)

    def _added(self, ts):
        for t in ts:
            self.ensure_lib(t)
        self.save()
        self.refresh()
        self.status(f"Добавлено треков: {len(ts)}")

    def add_files(self):
        self.add_paths(filedialog.askopenfilenames(title="Выберите музыку", filetypes=[("Аудио", " ".join("*" + e for e in EXTS))]))

    def add_folder(self):
        d = filedialog.askdirectory(title="Папка с музыкой")
        if d:
            self.add_paths([os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs])

    # ═════════════ поиск ═════════════
    def web_search(self, text):
        if not text:
            self.status("Введите запрос и нажмите Enter")
            return
        if flt.is_url(text):
            self.add_url(text)
            return
        providers = SOURCES[self.set["src"]]
        unc, orig = self.set["uncens"], self.set["originals"]
        jobs = []
        for pi, prov in enumerate(providers):
            if prov == "dz":
                jobs.append(("dz", text, 40))
                continue
            jobs.append((prov, text, 15))
            if pi == 0 or len(providers) == 1:  # дополнительные запросы — только основному источнику
                if unc:
                    jobs.append((prov, text + " explicit", 8))
                if orig:
                    jobs.append((prov, text + " official audio", 8))
        self.run_jobs(jobs, f"Поиск: {text}", text, artists=text)

    def find_explicit(self, t):
        a = "" if t["artist"] == UNKNOWN else flt.primary_artist(t["artist"]) + " "
        q = f"{a}{t['title']}"
        prov = SOURCES[self.set["src"]]
        prov = [p for p in prov if p != "dz"] or ["ytsearch"]
        self.run_jobs([(prov[0], q + " explicit", 14), (prov[0], q + " uncensored", 10), (prov[0], q + " official audio", 8), ("dz", q, 15)],
                      f"Без цензуры: {t['title']}", q, uncens=True)

    def run_jobs(self, jobs, title, query, artists=None, uncens=None, lib_only_new=False):
        if not engine.yt_dlp and any(j[0] != "dz" for j in jobs):
            messagebox.showinfo("Нет yt-dlp", "Движок поиска ещё не загружен. Проверьте интернет и перезапустите плеер (или ⚙ → Обновить компоненты).", parent=self)
            jobs = [j for j in jobs if j[0] == "dz"]
            if not jobs:
                return
        unc = self.set["uncens"] if uncens is None else uncens
        orig = self.set["originals"]
        self.sq += 1
        tok = self.sq
        self.words = flt.query_words([j[1] for j in jobs])
        self.results, self._pool, self.strip_items = [], [], []
        self.pending = len(jobs) + (1 if artists else 0)
        self.stitle = title
        self.status("Ищу…", True)
        self.view, self.hist = "search", []
        lib = set(self.store.by_src) if lib_only_new else set()
        self._nav = None
        self.render()

        def work(job):
            prov, q, n = job
            key = (prov, q, n)
            hit = self.scache.get(key)
            try:
                if hit and time.time() - hit[0] < 900:
                    ts = hit[1]
                else:
                    if prov == "dz":
                        ts = self.dz.search_tracks(q, n)
                    else:
                        ents = engine.search(prov, q, n)
                        ts = [engine.web_track(e, query) for e in ents if e.get("duration") and 30 <= e["duration"] <= 1200]
                    self.scache[key] = (time.time(), ts)
            except Exception as ex:  # noqa: BLE001
                ts = []
                print("search:", ex)
                self.post(lambda ex=ex: self.status("Ошибка поиска: " + str(ex)[:70]))
            self.post(lambda: self.ingest(tok, [dict(t) for t in ts], unc, orig, lib))

        def awork():
            try:
                r = self.dz.search_artists(artists, 4)
                qt = set(flt.norm(artists).split())
                r = [a for a in r if set(flt.norm(a["name"]).split()) & qt]
            except Exception as ex:  # noqa: BLE001
                print("artists:", ex)
                r = []
            self.post(lambda: self.set_strip(tok, r))
        for j in jobs:
            POOL.submit(work, j)
        if artists:
            POOL.submit(awork)

    def set_strip(self, tok, r):
        if tok != self.sq:
            return
        self.pending -= 1
        self.strip_items = r
        self.strip.set_items(r)
        if self.view == "search":
            self.render(True)

    def ingest(self, tok, ts, unc, orig, lib):
        if tok != self.sq:
            return
        for t in ts:
            if not t.get("src") or t["src"] in lib or not flt.passes(t, orig, unc):
                continue
            t["sc"] = flt.score_web(t, self.words, unc, orig)
            self._pool.append(t)
        key = lambda t: flt.track_key(t["artist"], t["title"]) + "|" + ",".join(sorted(set(t.get("tags", ())) & flt.HARD_TAGS))  # noqa: E731
        self.results = sorted(flt.dedupe(self._pool, key), key=lambda t: -t["sc"])
        self.pending -= 1
        self.status(f"Найдено: {len(self.results)}" + ("…" if self.pending > 0 else ""), self.pending > 0)
        if self.view == "search":
            self.render(True)

    def add_url(self, url):
        """Ссылка на трек/плейлист любого сайта, который знает yt-dlp (YouTube, SoundCloud, Bandcamp, Mixcloud, VK …)."""
        if not engine.yt_dlp:
            self.status("Движок yt-dlp ещё не загружен")
            return
        self.status("Читаю ссылку…", True)

        def work():
            try:
                info = engine.ydl(engine.ydl_opts(extract_flat=True, skip_download=True, noplaylist=False), lambda y: y.extract_info(url, download=False))
                ents = info.get("entries") or [info]
                ts = []
                for e in ents:
                    if not e:
                        continue
                    e.setdefault("webpage_url", e.get("url") or url)
                    e.setdefault("duration", e.get("duration") or 0)
                    ts.append(engine.web_track(e, "remix cover live"))  # явная ссылка — пользователь знает, что хочет
                for t in ts:
                    t["tags"] = []
                self.post(lambda: self._url_done(ts, info.get("title") or "Ссылка"))
            except Exception as ex:  # noqa: BLE001
                self.post(lambda ex=ex: self.status("Не удалось открыть ссылку: " + str(ex)[:80]))
        POOL.submit(work)

    def _url_done(self, ts, title):
        self.sq += 1
        self.results, self.stitle, self.strip_items, self.pending = ts, title, [], 0
        self.view, self.hist, self._nav = "search", [], None
        self.render()
        self.status(f"Найдено: {len(ts)}")

    def affinity(self):
        aff = {}
        for t in self.store.tracks:
            aff[t["artist"]] = aff.get(t["artist"], 0) + t["plays"] + (4 if t["fav"] else 0)
        return aff

    def discover(self):
        top = [a for a, v in sorted(self.affinity().items(), key=lambda x: -x[1]) if v > 0 and a != UNKNOWN][:3]
        if not top:
            self.status("Послушайте и отметьте ♥ несколько треков — тогда будет что рекомендовать")
            return
        self.sq += 1
        tok = self.sq
        self.results, self._pool, self.strip_items, self.pending, self.stitle = [], [], [], 1, "Похожее на ваши вкусы"
        self.view, self.hist, self._nav = "search", [], None
        self.render()
        self.status("Подбираю похожих исполнителей…", True)
        have = {flt.track_key(t["artist"], t["title"]) for t in self.store.tracks}
        have_art = {flt.norm(flt.primary_artist(t["artist"])) for t in self.store.tracks}

        def work():
            out = []
            try:
                for name in top:
                    a = self.dz.artist_by_name(name)
                    if not a:
                        continue
                    for rel in self.dz.related(a["id"], 6):
                        if flt.norm(rel["name"]) in have_art:
                            continue
                        out += [t for t in self.dz.top(rel["id"], 5) if flt.is_original(t["tags"]) and flt.track_key(t["artist"], t["title"]) not in have]
            except Exception as ex:  # noqa: BLE001
                print("discover:", ex)
            random.shuffle(out)
            self.post(lambda: self.ingest_discover(tok, out))
        POOL.submit(work)

    def ingest_discover(self, tok, ts):
        if tok != self.sq:
            return
        for t in ts:
            t["sc"] = t.get("rank", 0)
        self.results = flt.dedupe(ts)
        self.pending = 0
        self.status(f"Найдено: {len(self.results)}")
        if self.view == "search":
            self.render(True)

    def make_recs(self):
        aff, now = self.affinity(), time.time()
        sc = sorted(self.store.tracks, key=lambda t: -(aff.get(t["artist"], 0) - t["plays"] * .6 + (1 if now - t["last"] > 86400 else 0) + random.random() * 1.5))
        self.rec_ids = [t["id"] for t in sc[:20]]

    # ═════════════ карточка исполнителя ═════════════
    def open_artist_for(self, t):
        name = flt.primary_artist(t.get("artist") or "")
        if t.get("aid"):
            self.open_artist(t["aid"], dict(name=t["artist"] if flt.norm(name) == flt.norm(t["artist"]) else name))
        elif name and name != UNKNOWN:
            self.open_artist(None, dict(name=name))

    def open_artist(self, aid, info=None):
        info = info or {}
        self.push()
        a = dict(id=aid, name=info.get("name", "…"), pic=info.get("pic"), info=info if info.get("fans") is not None else None,
                 tab="top", top=[], all=None, albums=None, stats={}, loaded=False, tok=uuid.uuid4().hex)
        self.artist, self.view = a, "artist"
        self.flt.set("")
        self._nav = None
        self.render()

        def live():
            return self.artist is a

        def work():
            try:
                i = self.dz.artist(a["id"]) if a["id"] else self.dz.artist_by_name(a["name"])
                if not i:
                    self.post(lambda: self.status("Карточка исполнителя не найдена в каталоге"))
                    a["loaded"], a["albums"] = True, []
                    self.post(lambda: live() and self.render(True))
                    return
                a["id"], a["name"], a["info"] = i["id"], i["name"], i
                self.post(lambda: live() and self.hero_draw())
                top = [t for t in self.dz.top(i["id"], 60) if flt.is_original(t["tags"])]
                top = flt.dedupe(top, scorefn=lambda t: (t.get("exp", False), t.get("rank", 0)))
                top.sort(key=lambda t: -t.get("rank", 0))
                a["top"], a["loaded"] = top[:30], True
                self.post(lambda: live() and self.render(True))
                alb = self.dz.albums(i["id"])
                a["albums"] = alb
                self.post(lambda: live() and (self.render(True) if a["tab"] == "albums" else None))
                st = a["stats"]
                if self.set.get("lastfm_key"):
                    st["lfm"] = lastfm_stats(self.set["lastfm_key"], i["name"])
                st["avg"] = engine.avg_views(a["top"])
                self.post(lambda: live() and self.hero_draw())
            except Exception as ex:  # noqa: BLE001
                print("artist:", ex)
                a["loaded"] = True
                if a["albums"] is None:
                    a["albums"] = []
                self.post(lambda ex=ex: (self.status("Не удалось загрузить исполнителя: " + str(ex)[:60]), live() and self.render(True)))
        POOL.submit(work)

    def set_tab(self, k):
        a = self.artist
        if not a:
            return
        a["tab"] = k
        if k == "all" and a["all"] is None and not a.get("loading_all"):
            a["loading_all"] = True

            def work():
                try:
                    for _ in range(300):  # ждём список релизов (до ~90 с)
                        if a["albums"] is not None or self.artist is not a:
                            break
                        time.sleep(0.3)
                    if a["albums"] is None:
                        a["albums"] = []
                    prog = lambda d, n: (a.__setitem__("progress", f"Собираю дискографию… {d}/{n}"), self.post(lambda: self.artist is a and a["tab"] == "all" and self.render(True)))  # noqa: E731
                    a["all"] = self.dz.all_tracks(a["id"], a["albums"], prog)
                except Exception as ex:  # noqa: BLE001
                    print("all:", ex)
                    a["all"] = []
                self.post(lambda: self.artist is a and self.render(True))
            POOL.submit(work)
        self.render()

    def play_shuffled(self):
        l = list(self.items())
        if l:
            random.shuffle(l)
            self.play_track(l[0], l)

    def open_album_for(self, t):
        if t.get("alid"):
            self.open_album(t["alid"], dict(id=t["alid"], title=t.get("album", ""), cover=t.get("cover"), artist=t.get("artist", "")))

    def open_album(self, alid, meta):
        self.push()
        al = dict(id=alid, title=meta.get("title", ""), cover=meta.get("cover"), date=meta.get("date", ""), artist=meta.get("artist") or (self.artist or {}).get("name", ""), tracks=[])
        self.album, self.view = al, "album"
        self.flt.set("")
        self._nav = None
        self.render()

        def work():
            try:
                ts = self.dz.album_tracks(alid, dict(id=alid, title=al["title"], cover_medium=al["cover"], record_type="album"))
                if al["artist"]:
                    pass
                al["tracks"] = ts
            except Exception as ex:  # noqa: BLE001
                print("album:", ex)
                self.post(lambda: self.status("Не удалось загрузить альбом"))
            self.post(lambda: self.album is al and self.render(True))
        POOL.submit(work)

    # ═════════════ тексты ═════════════
    def set_text(self, s):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", s)
        self.txt.configure(state="disabled")
        self.lidx = -1

    def load_lyrics(self, t):
        self.ltimes = []
        self.set_text("Ищу текст…")

        def work():
            r = fetch_lyrics("" if t["artist"] == UNKNOWN else flt.primary_artist(t["artist"]), t["title"])
            self.post(lambda: self.show_lyrics(t, r))
        POOL.submit(work)

    def show_lyrics(self, t, r):
        if not self.cur or self.cur["id"] != t["id"]:
            return
        if r["synced"]:
            ln = parse_lrc(r["synced"])
            self.ltimes = [x[0] for x in ln]
            self.set_text("\n".join(x[1] for x in ln))
        elif r["plain"]:
            self.ltimes = []
            self.set_text(r["plain"])
        else:
            self.ltimes = []
            self.set_text("Текст не найден.\n\nПоправьте название или исполнителя (правая кнопка → «Изменить…») и запустите трек снова.")

    def toggle_lyrics(self):
        self.set["lyrics"] = not self.set["lyrics"]
        self.save()
        if self.set["lyrics"]:
            self.lp.pack(side="right", fill="y", padx=(0, 8), pady=8, before=self.main)
            if self.cur:
                self.load_lyrics(self.cur)
        else:
            self.lp.pack_forget()
        self.update_ctl()

    # ═════════════ воспроизведение ═════════════
    def is_playing(self):
        try:
            return bool(self.pl and self.pl.is_playing())
        except Exception:  # noqa: BLE001
            return False

    def play_first(self):
        l = self.items()
        if l:
            self.play_track(l[0], l)

    def play_track(self, t, q=None, manual=True):
        if not self.pl:
            self.need_vlc()
            return
        if manual:
            self.fails = 0
        if q is not None:
            self.queue = list(q)
            self.qi = next((i for i, x in enumerate(q) if x["id"] == t["id"]), 0)
        try:
            self.pl.stop()  # сбросить состояние прошлого трека, иначе его «Ended» запустит лишний переход
        except Exception:  # noqa: BLE001
            pass
        self.cur, self.busy, self.loading, self.failed, self.t0, self.limit = t, True, True, False, time.time(), 90
        self.tok += 1
        tok = self.tok
        self.now.configure(text=trunc(t["title"], 34))
        self.nowa.configure(text=trunc(t["artist"], 40) + " · загрузка…")
        self.ptitle.configure(text=f"{t['title']}\n{t['artist']}")
        self.ltimes = []
        self.set_covers()
        if self.set["lyrics"]:
            self.load_lyrics(t)
        self.update_ctl()
        self.tl.set_playing(t["id"], False)
        self.tl.reveal(t["id"])
        if t["kind"] == "local":
            if os.path.exists(t["src"]):
                self.start(t, t["src"], tok)
            else:
                self.fail("Файл не найден: " + t["src"], tok)
            return
        self.status("Получаю звук…", True)

        def work():
            try:
                url, hd = engine.resolve(t, lambda: tok == self.tok)
                self.post(lambda: self.start(t, url, tok, hd))
            except Exception as ex:  # noqa: BLE001
                print("Ошибка:", ex)
                self.post(lambda ex=ex: self.retry_or_fail(str(ex), tok))
        POOL.submit(work)

    def retry_or_fail(self, msg, tok):
        if tok != self.tok or not self.cur:
            return
        if self.cur["kind"] != "local" and self.fb_tok != tok and "оригинальную запись" not in msg:
            self.fb_tok = tok
            self.play_cached(self.cur, tok)
        else:
            self.fail(msg, tok)

    def play_cached(self, t, tok):
        """Запасной путь: скачать трек целиком и играть файл."""
        self.status("Поток не открылся — загружаю трек целиком…", True)
        self.busy, self.loading, self.t0, self.limit = True, True, time.time(), 180

        def work():
            try:
                f = engine.cache_file(t)
                self.post(lambda: self.start(t, f, tok))
            except Exception as ex:  # noqa: BLE001
                print("cache:", ex)
                self.post(lambda ex=ex: self.fail(str(ex), tok))
        POOL.submit(work)

    def fail(self, msg, tok=None):
        if tok is not None and tok != self.tok:
            return
        self.busy, self.loading, self.failed = True, False, True
        self.fails += 1
        self.nowa.configure(text="ошибка воспроизведения")
        self.tl.set_playing(self.cur["id"] if self.cur else None, False)
        if self.fails < 3 and len(self.queue) > 1 and self.qi < len(self.queue) - 1:
            self.status("Не удалось воспроизвести — перехожу к следующему", False)
            self.after(900, lambda: tok == self.tok and self.step(1, True, manual=False))
            return
        self.status("Не удалось воспроизвести трек")
        hint = ""
        if re.search(r"format|JS|javascript|sign in|challenge|n-sig|403|bot", msg, re.I):
            hint = "\n\nПохоже, YouTube не отдал звук. Подождите 10–20 секунд (движок обновляется в фоне) и повторите, либо смените источник на SoundCloud / Каталог."
        messagebox.showerror("Не играет", msg[:300] + hint, parent=self)

    def start(self, t, src, tok, headers=None):
        if tok != self.tok:
            return
        self.loading, self.t_start = False, time.time()
        media = self.inst.media_new(src)
        for k, o in (("User-Agent", ":http-user-agent="), ("Referer", ":http-referrer=")):
            if headers and headers.get(k):
                media.add_option(o + headers[k])
        self.pl.set_media(media)
        if self.pl.play() == -1:
            self.fail("VLC не смог начать воспроизведение. Попробуйте ⚙ → «Скачать / переустановить VLC».", tok)
            return
        self.pl.audio_set_volume(int(self.set["vol"]))
        self.vol_applied = False
        t["plays"] = t.get("plays", 0) + 1
        t["last"] = time.time()
        x = self.store.get(t["id"])
        if x:
            x.update(plays=t["plays"], last=t["last"], alt=t.get("alt"))
            self.save()
        self.busy = False
        self.fails = 0
        self.nowa.configure(text=trunc(t["artist"], 44))
        self.title(f"{t['title']} — {t['artist']}")
        self.status("")
        self.update_ctl()
        self.render(True)
        self.prefetch()

    def prefetch(self):
        """Заранее готовим ссылку на следующий трек — переход мгновенный."""
        i = self.qi + 1
        if 0 <= i < len(self.queue) and self.queue[i]["kind"] != "local":
            t, tok = self.queue[i], self.tok

            def work():
                try:
                    engine.resolve(dict(t), lambda: tok == self.tok)
                except Exception:  # noqa: BLE001
                    pass
            POOL.submit(work)

    def toggle(self):
        if not self.pl:
            self.need_vlc()
            return
        if not self.cur:
            self.play_first()
            return
        if self.failed or self.pl.get_state() in (self.vlc.State.Stopped, self.vlc.State.Ended):
            self.play_track(self.cur)
            return
        self.pl.pause()
        self.after(120, self.update_ctl)

    def step(self, d, auto=False, manual=True):
        n = len(self.queue)
        if not n:
            return
        if self.set["shuffle"] and n > 1:
            i = self.qi
            while i == self.qi:
                i = random.randrange(n)
        else:
            i = self.qi + d
            if i >= n:
                if auto and self.set["rep"] == 0:
                    self.pl.stop()
                    self.busy = True
                    self.update_ctl()
                    self.tl.set_playing(self.cur["id"] if self.cur else None, False)
                    return
                i = 0
            if i < 0:
                i = n - 1
        self.qi = i
        self.play_track(self.queue[i], manual=manual and not auto)

    def toggle_shuffle(self):
        self.set["shuffle"] = not self.set["shuffle"]
        self.save()
        self.update_ctl()

    def cycle_rep(self):
        self.set["rep"] = (self.set["rep"] + 1) % 3
        self.save()
        self.update_ctl()

    def update_ctl(self):
        s = self.set
        self.bsh.set_active(s["shuffle"])
        self.brp.set_active(s["rep"] > 0)
        self.brp.set_text("🔂" if s["rep"] == 2 else "🔁")
        self.blyr.set_active(s["lyrics"])
        self.chu.set_active(s["uncens"])
        self.cor.set_active(s["originals"])
        self.chs.set_text("Источник: " + s["src"] + " ▾")
        self.bpp.set_text("⏸" if self.is_playing() else "▶")
        fav = bool(self.cur and self.cur.get("fav"))
        self.bheart.set_text("♥" if fav else "♡")
        self.bheart.set_active(fav)

    def set_vol(self, v):
        v = int(float(v))
        self.set["vol"] = v
        if hasattr(self, "vol"):
            self.vol.set(v / 100)
        if self.pl:
            self.pl.audio_set_volume(v)

    def on_seek(self, v):
        if self.pl and self.pl.get_length() > 0:
            self.pl.set_position(v)

    def tick(self):  # цикл не умирает из-за ошибки в одном из обработчиков
        try:
            while True:
                try:
                    fn = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    self.log()
            self.tick_player()
        except Exception:  # noqa: BLE001
            self.log()
        self.after(120, self.tick)

    def tick_player(self):
        if not (self.pl and self.cur):
            return
        if self.busy and self.loading and time.time() - self.t0 > self.limit:
            self.loading = False
            self.retry_or_fail("Время ожидания истекло: источник не отдал трек. Попробуйте другой трек или источник.", self.tok)
            return
        if self.busy:
            return
        ln, pos = self.pl.get_length(), max(self.pl.get_time(), 0)
        playing = self.pl.is_playing()
        if ln > 0:
            if not self.cur.get("dur"):
                self.cur["dur"] = ln / 1000
            self.du.configure(text=fmt(ln / 1000))
            if not self.seek.drag:
                self.seek.set(pos / ln)
                self.cu.configure(text=fmt(pos / 1000) if pos else "0:00")
        if playing and not self.vol_applied:  # громкость иногда игнорируется до фактического старта
            self.pl.audio_set_volume(int(self.set["vol"]))
            self.vol_applied = True
        self.bpp.set_text("⏸" if playing else "▶")
        self.tl.set_playing(self.cur["id"], playing)
        if self.ltimes:
            i = bisect.bisect_right(self.ltimes, pos / 1000 + 0.25) - 1
            if i != self.lidx:
                self.lidx = i
                self.txt.tag_remove("cur", "1.0", "end")
                if i >= 0:
                    self.txt.tag_add("cur", f"{i + 1}.0", f"{i + 1}.end")
                    self.txt.see(f"{i + 1}.0")
        if time.time() - self.t_start > 2:
            st = self.pl.get_state()
            if st == self.vlc.State.Error:
                self.busy = True
                self.retry_or_fail("VLC не смог открыть поток или файл.", self.tok)
            elif st == self.vlc.State.Ended:
                self.busy = True
                if self.set["rep"] == 2:
                    self.play_track(self.cur, manual=False)
                else:
                    self.step(1, True)

    # ═════════════ загрузка файлов ═════════════
    def download(self, ts):
        ts = [t for t in ts if t["kind"] != "local"]
        if not ts:
            return
        if not engine.yt_dlp:
            messagebox.showinfo("Нет yt-dlp", "Движок ещё не загружен.", parent=self)
            return
        ff = bool(shutil.which("ffmpeg"))
        folder = self.set["dl"]

        def work():
            for t in ts:
                safe = safe_name(f"{t['artist']} - {t['title']}")
                self.post(lambda s=safe: self.status("Скачиваю: " + s[:46] + "…", True))
                try:
                    path = engine.download_track(t, folder, safe, ff)
                    self.post(lambda t=t, p=path: self.downloaded(t, p))
                except Exception as ex:  # noqa: BLE001
                    self.post(lambda ex=ex: messagebox.showerror("Скачивание", "Не удалось скачать.\n\n" + str(ex)[:250], parent=self))
                    return
        POOL.submit(work)

    def downloaded(self, t, path):
        t = self.ensure_lib(t)
        self.store.by_src.pop(t["src"], None)
        t["kind"], t["src"] = "local", path
        self.store.by_src[path] = t
        self.save()
        self.refresh()
        self.status("Готово: " + os.path.basename(path))

    # ═════════════ диагностика ═════════════
    def diagnose(self):
        js = engine.find_js()
        info = [
            f"Okunek Music {VERSION}",
            f"Python: {sys.version.split()[0]} {'(сборка)' if getattr(sys, 'frozen', False) else ''}",
            f"VLC: {'OK' if self.pl else 'НЕТ — ⚙ → Скачать VLC'}",
            f"yt-dlp: {engine.ytdlp_version() or 'НЕ ЗАГРУЖЕН'}",
            f"JS-движок: {js[0] + ' — ' + js[1] if js else 'НЕТ (нужен для YouTube; скачается автоматически)'}",
            f"ffmpeg: {'есть' if shutil.which('ffmpeg') else 'нет (скачивание в m4a)'}",
            f"Last.fm ключ: {'задан' if self.set.get('lastfm_key') else 'нет (необязательно)'}",
            f"Обновления: {UPDATE_REPO or 'адрес не задан'}",
            f"Данные: {APP}",
            f"Фильтры: без цензуры={'вкл' if self.set['uncens'] else 'выкл'}, только оригиналы={'вкл' if self.set['originals'] else 'выкл'}",
        ]
        messagebox.showinfo("Диагностика", "\n".join(info), parent=self)
