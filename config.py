"""Константы, пути, темы. Не импортирует ничего тяжёлого — грузится мгновенно."""
import os
import sys

VERSION = "3.0.0"
APP_NAME = "Okunek Music"

# Репозиторий GitHub вида "логин/репозиторий", в Releases которого лежит OkunekMusic-Setup-X.Y.Z.exe.
# Пока пусто — проверка обновлений выключена. См. README.md → «Обновления».
UPDATE_REPO = "butuzovatatyana82-ui/test1"

FROZEN = getattr(sys, "frozen", False)
EXE_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = getattr(sys, "_MEIPASS", EXE_DIR)

if os.name == "nt":
    HOME = os.environ.get("APPDATA", os.path.expanduser("~"))
    APP = os.path.join(HOME, "OkunekMusic")
else:  # для разработки на Linux/macOS
    APP = os.path.join(os.path.expanduser("~"), ".okunek")
OLD = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MyPlayer")

LIB = os.path.join(APP, "lib")      # pip-библиотеки (запуск из исходников)
BIN = os.path.join(APP, "bin")      # yt-dlp.zip, deno
VLCDIR = os.path.join(APP, "vlc")   # портативный VLC (если системного нет)
COV = os.path.join(APP, "covers")
LYR = os.path.join(APP, "lyrics")
CACHE = os.path.join(APP, "cache")
ART = os.path.join(APP, "artists")  # кэш карточек исполнителей
DATA = os.path.join(APP, "data.json")
ENGINE = os.path.join(APP, "engine.json")
MUSIC = os.path.join(os.path.expanduser("~"), "Music", "Okunek")

EXTS = (".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".ape", ".wv")
UNKNOWN = "Неизвестный исполнитель"
UA = {"User-Agent": f"OkunekMusic/{VERSION} (personal player)"}

# Источники поиска. Ключ — название в интерфейсе, значение — список «провайдеров».
#   dz  — каталог Deezer (официальные релизы: оригиналы, метаданные, обложки)
#   ytm — YouTube Music (песни), с запасным переходом на обычный YouTube
#   остальные — префиксы поиска yt-dlp
SOURCES = {
    "Каталог": ["dz"],
    "YouTube Music": ["ytm"],
    "YouTube": ["ytsearch"],
    "SoundCloud": ["scsearch"],
    "Bilibili": ["bilisearch"],
    "Niconico": ["nicosearch"],
    "Все": ["dz", "ytm", "ytsearch", "scsearch"],
}
DEFAULT_SOURCE = "Каталог"

THEMES = {
    "Okunek":  dict(bg="#050308", panel="#120c1f", elev="#241838", text="#f4efff", muted="#a193c4", accent="#a855f7", atext="#12061f", hi="#31d4f7"),
    "Полночь": dict(bg="#000000", panel="#121212", elev="#2a2a2a", text="#ffffff", muted="#b3b3b3", accent="#1ed760", atext="#000000", hi="#1ed760"),
    "Светлая": dict(bg="#e9e6f2", panel="#ffffff", elev="#efeaf9", text="#1c1830", muted="#6f6890", accent="#c026d3", atext="#ffffff", hi="#0ea5e9"),
    "Океан":   dict(bg="#04101a", panel="#0b2030", elev="#16364d", text="#e6f4fc", muted="#84a9bf", accent="#35c2e8", atext="#04161f", hi="#7dd3fc"),
    "Лес":     dict(bg="#070d08", panel="#101b13", elev="#1d3123", text="#e8f5ea", muted="#8cab93", accent="#9be564", atext="#10200a", hi="#4ade80"),
    "Закат":   dict(bg="#0d0705", panel="#1d110c", elev="#33201a", text="#fff0e6", muted="#c9a58f", accent="#ff8a3d", atext="#2a1204", hi="#fb7185"),
}
ALIAS = {"Тёмная": "Полночь"}

SANS = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
SYM = "Segoe UI Symbol" if os.name == "nt" else "DejaVu Sans"
F, FB = (SANS, 10), (SANS, 10, "bold")
FS = (SANS, 9)
FI, FIL, FH = (SYM, 13), (SYM, 16), (SANS, 30, "bold")

DEFAULT_SETTINGS = dict(
    theme="Okunek", vol=80, shuffle=False, rep=0, src=DEFAULT_SOURCE,
    uncens=True, originals=True, lyrics=True, dl=MUSIC,
    lastfm_key="", auto_update=True,
)
