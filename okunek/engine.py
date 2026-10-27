"""Движок: автоустановка библиотек, yt-dlp (обновляемый), Deno, VLC, поиск и получение звукового потока."""
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

from . import filters as flt
from .config import APP, BIN, CACHE, ART, BASE, ENGINE, EXE_DIR, FROZEN, LIB, UA, VLCDIR
from .util import dbg
from .net import cache_get, cache_put, http_get, http_json

yt_dlp = None
vlc = None
PIP_REQS = [("vlc", "python-vlc"), ("mutagen", "mutagen"), ("PIL", "pillow")]
YT_ZIP = os.path.join(BIN, "yt-dlp.zip")
YT_SHIPPED = os.path.join(EXE_DIR, "bin", "yt-dlp.zip")
YT_CLIENTS = [
    None,
    {"youtube": {"player_client": ["tv", "web_safari"]}},
    {"youtube": {"player_client": ["ios", "android_vr"]}},
]
FMT = "bestaudio[ext=m4a]/bestaudio/best"
STREAM_CACHE = {}  # page_url -> (время, url, headers)


# ═════════════════════ окружение и зависимости ═════════════════════
def setup_paths():
    """PATH (deno/ffmpeg), каталог pip-библиотек, yt-dlp.zip."""
    for d in (BIN, os.path.join(BASE, "bin"), os.path.join(EXE_DIR, "bin"), EXE_DIR):
        if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if os.path.isdir(LIB) and LIB not in sys.path:
        sys.path.insert(0, LIB)


def missing_pip():
    import importlib.util
    return [pkg for mod, pkg in PIP_REQS if importlib.util.find_spec(mod) is None]


def pip_install(pkgs, log=print):
    """Ставит библиотеки в %APPDATA%/OkunekMusic/lib — без прав администратора и без засорения системы."""
    os.makedirs(LIB, exist_ok=True)
    if LIB not in sys.path:
        sys.path.insert(0, LIB)
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--target", LIB, *pkgs]
    log("Устанавливаю: " + ", ".join(pkgs))
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode != 0:
        subprocess.run([sys.executable, "-m", "ensurepip", "--user"], capture_output=True, creationflags=0x08000000 if os.name == "nt" else 0)
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode != 0:
        raise RuntimeError("pip: " + (r.stderr or r.stdout)[-300:])
    import importlib
    importlib.invalidate_caches()


def download(url, dest, progress=None, timeout=60):
    """Скачивание с прогрессом и записью через временный файл."""
    import urllib.request as ur
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with ur.urlopen(ur.Request(url, headers=UA), timeout=timeout) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            b = r.read(256 * 1024)
            if not b:
                break
            f.write(b)
            got += len(b)
            if progress and total:
                progress(got / total)
    os.replace(tmp, dest)
    return dest


def _state():
    try:
        with open(ENGINE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_state(s):
    try:
        os.makedirs(APP, exist_ok=True)
        with open(ENGINE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:  # noqa: BLE001
        pass


# ═════════════════════ yt-dlp (обновляется как zip, pip не нужен) ═════════════════════
def pick_ytdlp_zip():
    ex = [p for p in (YT_ZIP, YT_SHIPPED) if os.path.isfile(p)]
    return max(ex, key=os.path.getmtime) if ex else None


def load_ytdlp():
    global yt_dlp
    z = pick_ytdlp_zip()
    if z and z not in sys.path:
        sys.path.insert(0, z)
    try:
        import yt_dlp as y
        yt_dlp = y
    except Exception:  # noqa: BLE001
        yt_dlp = None
    return yt_dlp


def ytdlp_version():
    return getattr(getattr(yt_dlp, "version", None), "__version__", None) if yt_dlp else None


def update_ytdlp(force=False, log=print):
    """'new' — скачана свежая версия (применится при следующем запуске), 'same' — актуально, 'fail'."""
    st = _state()
    if not force and time.time() - st.get("yt_checked", 0) < 12 * 3600 and os.path.isfile(YT_ZIP):
        return "same"
    try:
        tag = http_json("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", 15)["tag_name"]
        st["yt_checked"] = time.time()
        if tag == st.get("yt_tag") and os.path.isfile(YT_ZIP):
            _save_state(st)
            return "same"
        log("Обновляю yt-dlp " + tag + "…")
        data = http_get(f"https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/yt-dlp", 120, 3)
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise RuntimeError("скачанный файл — не yt-dlp")
        os.makedirs(BIN, exist_ok=True)
        with open(YT_ZIP + ".tmp", "wb") as f:
            f.write(data)
        os.replace(YT_ZIP + ".tmp", YT_ZIP)
        st["yt_tag"] = tag
        _save_state(st)
        STREAM_CACHE.clear()
        return "new"
    except Exception as ex:  # noqa: BLE001
        dbg("update_ytdlp:", ex)
        return "fail"


# ═════════════════════ Deno (JS-движок для YouTube) ═════════════════════
def find_js():
    for n in ("deno", "node", "bun"):
        p = shutil.which(n)
        if p:
            return n, p
    return None


def ensure_deno(log=print):
    if find_js() or os.name != "nt":
        return bool(find_js())
    try:
        log("Скачиваю Deno (JS-движок для YouTube)…")
        z = http_get("https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip", 240, 2)
        os.makedirs(BIN, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(z)).extract("deno.exe", BIN)
        setup_paths()
        return True
    except Exception as ex:  # noqa: BLE001
        dbg("deno:", ex)
        return False


# ═════════════════════ VLC ═════════════════════
def _find_libvlc():
    for root in (VLCDIR, os.path.join(EXE_DIR, "vlc"), os.path.join(BASE, "vlc")):
        for p in glob.glob(os.path.join(root, "**", "libvlc.dll"), recursive=True):
            return p
    return None


def load_vlc():
    """Подключает VLC: сначала портативный из папки программы, потом установленный в системе."""
    global vlc
    lib = _find_libvlc()
    if lib:
        d = os.path.dirname(lib)
        os.environ["PYTHON_VLC_LIB_PATH"] = lib
        os.environ["PYTHON_VLC_MODULE_PATH"] = os.environ["VLC_PLUGIN_PATH"] = os.path.join(d, "plugins")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(d)
    sys.modules.pop("vlc", None)
    try:
        import vlc as v
        v.Instance("--quiet")  # проверка: библиотека действительно загрузилась
        vlc = v
    except Exception:  # noqa: BLE001
        vlc = None
    return vlc


def install_vlc(log=print, progress=None):
    """Скачивает портативный VLC (64-bit, ≈ 45 МБ) с videolan.org в папку программы."""
    if os.name != "nt":
        raise RuntimeError("Установите VLC через пакетный менеджер (apt install vlc).")
    idx = http_get("https://get.videolan.org/vlc/last/win64/", 30).decode("utf-8", "ignore")
    m = re.findall(r'href="(vlc-[\d.]+-win64\.zip)"', idx)
    if not m:
        raise RuntimeError("не нашёл архив VLC на videolan.org")
    name = sorted(set(m))[-1]
    log("Скачиваю VLC…")
    z = os.path.join(APP, name)
    download("https://get.videolan.org/vlc/last/win64/" + name, z, progress, 120)
    log("Распаковываю VLC…")
    shutil.rmtree(VLCDIR, ignore_errors=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(VLCDIR)
    os.remove(z)
    return load_vlc()


# ═════════════════════ yt-dlp: опции и поиск ═════════════════════
def ydl_opts(**kw):
    d = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20, "retries": 3,
         "extractor_retries": 2, "fragment_retries": 3, "geo_bypass": True,
         "http_headers": {"User-Agent": UA["User-Agent"]}}
    js = find_js()
    if js:
        d["js_runtimes"] = {js[0]: {"path": js[1]}}
        d["remote_components"] = ["ejs:github"]
    d.update(kw)
    return d


def ydl(opts, fn):
    """Запуск yt-dlp; если версия не знает js_runtimes/remote_components — повтор без них."""
    if not yt_dlp:
        raise RuntimeError("yt-dlp не загружен (нет интернета при первом запуске?)")
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            return fn(y)
    except Exception as ex:  # noqa: BLE001
        if ("js_runtimes" in opts or "remote_components" in opts) and re.search(r"js_runtimes|remote_comp|unexpected keyword", str(ex), re.I):
            o = {k: v for k, v in opts.items() if k not in ("js_runtimes", "remote_components")}
            with yt_dlp.YoutubeDL(o) as y:
                return fn(y)
        raise


def flat_search(prefix, q, n):
    """Быстрый поиск без получения потоков (extract_flat)."""
    def go(y):
        return [e for e in (y.extract_info(f"{prefix}{n}:{q}", download=False).get("entries") or []) if e]
    return ydl(ydl_opts(extract_flat=True, skip_download=True, noplaylist=False), go)


def ytm_search(q, n):
    """YouTube Music; если страница поиска недоступна — обычный YouTube с упором на «Topic»-каналы."""
    try:
        def go(y):
            info = y.extract_info("https://music.youtube.com/search?q=" + re.sub(r"\s+", "+", q), download=False)
            return [e for e in (info.get("entries") or []) if e and e.get("duration")]
        r = ydl(ydl_opts(extract_flat=True, skip_download=True, noplaylist=False, playlistend=n), go)
        if r:
            return r
    except Exception as ex:  # noqa: BLE001
        dbg("ytm:", str(ex)[:120])
    return flat_search("ytsearch", q + " topic", n)


def search(prov, q, n):
    return ytm_search(q, n) if prov == "ytm" else flat_search(prov, q, n)


def web_track(e, query=""):
    """Запись yt-dlp → внутренний формат трека с разметкой оригинал/ремикс."""
    import uuid
    raw = e.get("title") or "Без названия"
    ch = (e.get("uploader") or e.get("channel") or "")
    topic = ch.endswith("- Topic")
    artist, title = ch.replace(" - Topic", "") or "Неизвестный исполнитель", raw
    if " - " in raw:
        artist, title = [x.strip() for x in raw.split(" - ", 1)]
    th = e.get("thumbnails") or []
    c = flt.classify(artist, title, query, extra=ch)
    src = e.get("webpage_url") or e.get("url")
    return dict(
        id=hashlib.sha1((src or uuid.uuid4().hex).encode()).hexdigest()[:16], kind="web", src=src, title=title, artist=artist,
        dur=e.get("duration") or 0, plays=0, fav=False, last=0, views=e.get("view_count") or 0, topic=topic,
        cover=e.get("thumbnail") or (th[-1].get("url") if th else None), **c,
    )


# ═════════════════════ получение потока ═════════════════════
def _stream(page, alive):
    """Прямая ссылка на звук для страницы трека (перебор клиентов YouTube)."""
    c = STREAM_CACHE.get(page)
    if c and time.time() - c[0] < 1800:
        return c[1], c[2]
    is_yt = "youtu" in page
    last = None
    for i, args in enumerate(YT_CLIENTS if is_yt else [None]):
        if not alive():
            raise RuntimeError("отменено")
        try:
            o = ydl_opts(format=FMT)
            if args:
                o["extractor_args"] = args
            info = ydl(o, lambda y: y.extract_info(page, download=False))
            url = info.get("url")
            if not url:
                for f in reversed(info.get("formats") or []):
                    if f.get("acodec") not in (None, "none") and f.get("url"):
                        url = f["url"]
                        break
            if url:
                hd = info.get("http_headers") or {}
                STREAM_CACHE[page] = (time.time(), url, hd)
                return url, hd
        except Exception as ex:  # noqa: BLE001
            last = ex
            dbg("stream:", str(ex)[:160])
    raise last or RuntimeError("не удалось получить ссылку на звук")


def match_catalog(t):
    """Находит для трека каталога лучшую «оригинальную» запись (Topic/официальный канал, длина ±секунды)."""
    key = "match:" + t["src"]
    c = cache_get(ART, key, 30 * 86400)
    if c:
        return c
    q = f"{flt.primary_artist(t['artist'])} {t['title']}"
    best = None
    for prov, n in (("ytsearch", 8), ("scsearch", 5)):
        try:
            b = flt.best_candidate(flat_search(prov, q, n), t["artist"], t["title"], t.get("dur"))
        except Exception as ex:  # noqa: BLE001
            dbg("match:", str(ex)[:100])
            continue
        if b:
            best = dict(url=b.get("url") or b.get("webpage_url"), views=b.get("view_count") or 0, dur=b.get("duration") or 0)
            break
    if best:
        cache_put(ART, key, best)
    return best


def resolve(t, alive=lambda: True):
    """(url, headers) для проигрывания. Для каталога — сначала подбор записи; при сбое — запасные источники."""
    if t["kind"] == "cat":
        m = match_catalog(t)
        if not m:
            raise RuntimeError("Не нашёл оригинальную запись этого трека (только ремиксы/каверы). Попробуйте другой источник.")
        t["alt"], t["views"] = m["url"], m["views"]
        return _stream(m["url"], alive)
    try:
        return _stream(t["src"], alive)
    except Exception as ex:  # noqa: BLE001
        if not alive():
            raise
        dbg("запасной источник:", str(ex)[:100])
        # основной источник не отдал звук — ищем ту же песню на других площадках
        q = f"{flt.primary_artist(t['artist'])} {t['title']}"
        for prov, n in (("scsearch", 5), ("ytsearch", 6)):
            if prov == "ytsearch" and "youtu" in t["src"]:
                continue
            if prov == "scsearch" and "soundcloud" in t["src"]:
                continue
            try:
                b = flt.best_candidate(flat_search(prov, q, n), t["artist"], t["title"], t.get("dur"))
                if b:
                    return _stream(b.get("url") or b.get("webpage_url"), alive)
            except Exception:  # noqa: BLE001
                continue
        raise


def page_of(t):
    return t.get("alt") or t["src"]


def download_track(t, folder, base, ffmpeg=False):
    """Скачивает трек в folder/base.ext; возвращает путь к файлу."""
    os.makedirs(folder, exist_ok=True)
    page = t.get("alt") or (match_catalog(t) or {}).get("url") if t["kind"] == "cat" else t["src"]
    if not page:
        raise RuntimeError("не нашёл источник для скачивания")
    o = ydl_opts(format=FMT, outtmpl=os.path.join(folder, base + ".%(ext)s"))
    if ffmpeg:
        o["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}]
    ydl(o, lambda y: y.download([page]))
    return os.path.join(folder, next(x for x in os.listdir(folder) if x.startswith(base + ".") and not x.endswith((".part", ".ytdl"))))


def cache_file(t):
    """Запасной путь: целиком скачать трек во временную папку и играть файл."""
    key = hashlib.sha1(page_of(t).encode()).hexdigest()[:16]
    os.makedirs(CACHE, exist_ok=True)
    have = lambda: [f for f in os.listdir(CACHE) if f.startswith(key + ".") and not f.endswith((".part", ".ytdl"))]  # noqa: E731
    if not have():
        page = page_of(t)
        if t["kind"] == "cat" and not t.get("alt"):
            m = match_catalog(t)
            page = m["url"] if m else page
        ydl(ydl_opts(format=FMT, outtmpl=os.path.join(CACHE, key + ".%(ext)s")), lambda y: y.download([page]))
    return os.path.join(CACHE, have()[0])


def avg_views(tracks, limit=8):
    """Среднее число просмотров/прослушиваний на трек по записям, найденным для топ-треков."""
    from concurrent.futures import ThreadPoolExecutor
    ts = tracks[:limit]

    def one(t):
        try:
            m = match_catalog(t)
            if m:
                t["alt"], t["views"] = m["url"], m["views"]
                return m["views"]
        except Exception:  # noqa: BLE001
            pass
        return 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        vs = [v for v in ex.map(one, ts) if v]
    return (sum(vs) / len(vs)) if vs else 0
