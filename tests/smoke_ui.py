"""Дымовой тест интерфейса БЕЗ реального tkinter: подставляет заглушку и прогоняет сборку окна и отрисовку.
Ловит NameError/AttributeError/TypeError в UI-коде. Реальную графику не проверяет."""
import os, sys, tempfile, types
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["APPDATA"] = os.environ["HOME"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class W:
    _n = 0
    def __init__(self, *a, **k): self.k = dict(k); W._n += 1
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return lambda *a, **k: 0
    def winfo_width(self): return 900
    def winfo_height(self): return 600
    def winfo_exists(self): return True
    def winfo_ismapped(self): return True
    def winfo_viewable(self): return True
    def winfo_children(self): return []
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def configure(self, **k): self.k.update(k)
    config = configure
    def cget(self, n): return self.k.get(n)
    def after(self, ms, fn=None, *a): return 1
    def after_cancel(self, i): pass
    def create_text(self, *a, **k): return 1
    def get(self, *a): return ""
    def tk_popup(self, *a): pass


class Var:
    def __init__(self, *a, **k): self.v = ""; self.cbs = []
    def get(self): return self.v
    def set(self, v): self.v = v
    def trace_add(self, *a): pass


class Font:
    def __init__(self, **k): pass
    def measure(self, s): return 7 * len(s)


tk = types.ModuleType("tkinter")
for n in ("Canvas", "Frame", "Label", "Text", "Entry", "Menu", "PhotoImage", "Toplevel"): setattr(tk, n, type(n, (W,), {}))
tk.Tk = type("Tk", (W,), {})
tk.StringVar = Var
tk.TclError = Exception
tk.font = types.ModuleType("tkinter.font"); tk.font.Font = Font
for sub in ("filedialog", "messagebox", "simpledialog"):
    m = types.ModuleType("tkinter." + sub); setattr(tk, sub, m); sys.modules["tkinter." + sub] = m
    m.__getattr__ = lambda n: (lambda *a, **k: None)
sys.modules["tkinter"] = tk; sys.modules["tkinter.font"] = tk.font

from okunek import app as A, engine
engine.vlc = None
fakeimg = types.SimpleNamespace(PhotoImage=lambda im: W())
A.ImageTk = fakeimg

a = A.App()
tr = lambda i, **k: dict(id=f"t{i}", kind="web", src=f"http://x/{i}", title=f"Track {i} " + "long " * (i % 5), artist="Artist A", album="Alb", alid=5, dur=200 + i, plays=0, fav=i % 3 == 0, last=0, exp=i % 2 == 0, cover=None, tags=[], **k)
for i in range(40): a.store.ensure(tr(i))
for v in ("lib", "fav", "rec", "search", "queue"):
    a.go(v); a.tl.W, a.tl.H = 900, 500; a.tl.redraw()
print("views ok; rows:", len(a.tl.items))
# поиск → ingest → дедуп/сортировка
a.sq = 1; a.pending = 2; a.words = ["artist"]; a.view = "search"
a.ingest(1, [dict(tr(100), sc=0, kind="cat", cat=True, src="dz:1"), dict(tr(101, ), title="Track 100 (Remix)", tags=["remix"]), dict(tr(102), bad=True, exp=False)], True, True, set())
print("search results:", [t["title"][:14] for t in a.results])
# карточка артиста
a.artist = dict(id=7, name="Artist A", pic=None, info=dict(fans=1234567, albums=12, pic=None), tab="top", top=[tr(1), tr(2)], all=None, albums=[dict(id=1, title="Alb", cover=None, date="2020-01-01", type="album")], stats=dict(avg=3.4e6), loaded=True)
a.view = "artist"; a.hist = [("lib", None, None)]
for tab in ("top", "all", "albums"):
    a.artist["tab"] = tab; a.render(); a.tl.redraw(); a.cards.W, a.cards.H = 900, 500; a.cards.redraw()
print("hero:", a.hero_info()[1])
a.album = dict(id=1, title="Alb", cover=None, date="2020", artist="Artist A", tracks=[tr(3)]); a.view = "album"; a.render(); a.hero_draw()
# события списка
class E: x = 100; y = 70; state = 0; x_root = 0; y_root = 0; delta = -120
a.tl.items = [tr(i) for i in range(10)]; a.tl._motion(E); a.tl._click(E); a.tl._wheel(E); a.tl._key(1)
a.tick(); a.diagnose(); a.update_ctl(); a.refresh_nav()
print("SMOKE OK")
