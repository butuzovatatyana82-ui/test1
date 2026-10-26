"""Сеть: HTTP с повторами, каталог Deezer (исполнители/альбомы/треки), тексты LRCLIB, дисковый кэш."""
import hashlib
import json
import os
import threading
import time
import urllib.parse as up
import urllib.request as ur
from concurrent.futures import ThreadPoolExecutor

from . import filters as flt
from .config import ART, LYR, UA
from .util import nowin  # noqa: F401  (реэкспорт не нужен, оставлено для совместимости)

_gate = threading.Semaphore(4)  # Deezer: ~50 запросов / 5 с — держим скромный параллелизм


def http_get(url, timeout=12, tries=2, headers=None):
    last = None
    for i in range(tries):
        try:
            h = dict(UA)
            h.update(headers or {})
            with ur.urlopen(ur.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except Exception as ex:  # noqa: BLE001
            last = ex
            time.sleep(0.4 * (i + 1))
    raise last


def http_json(url, timeout=12, tries=2):
    return json.loads(http_get(url, timeout, tries).decode("utf-8"))


# ───────── дисковый кэш JSON с TTL ─────────
def cache_get(folder, key, ttl):
    p = os.path.join(folder, hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
    try:
        if time.time() - os.path.getmtime(p) < ttl:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return None


def cache_put(folder, key, val):
    try:
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(val, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
    except Exception:  # noqa: BLE001
        pass


DAY = 86400


# ───────── Deezer ─────────
class Deezer:
    API = "https://api.deezer.com"
    pool = ThreadPoolExecutor(max_workers=4)

    def _get(self, path, **params):
        url = f"{self.API}{path}" + ("?" + up.urlencode(params) if params else "")
        for i in range(3):
            with _gate:
                d = http_json(url)
            err = d.get("error") if isinstance(d, dict) else None
            if err and err.get("code") == 4:  # лимит запросов — подождать и повторить
                time.sleep(1.2 * (i + 1))
                continue
            if err:
                raise RuntimeError(err.get("message", "Deezer error"))
            return d
        raise RuntimeError("Deezer: превышен лимит запросов")

    def _cached(self, key, ttl, fn):
        v = cache_get(ART, key, ttl)
        if v is None:
            v = fn()
            cache_put(ART, key, v)
        return v

    # --- исполнители
    def search_artists(self, q, limit=4):
        d = self._get("/search/artist", q=q, limit=limit)
        return [self._artist(a) for a in d.get("data", [])]

    @staticmethod
    def _artist(a):
        return dict(id=a["id"], name=a["name"], fans=a.get("nb_fan", 0), albums=a.get("nb_album", 0),
                    pic=a.get("picture_xl") or a.get("picture_big") or a.get("picture_medium"),
                    pic_s=a.get("picture_medium") or a.get("picture_small"))

    def artist(self, aid):
        return self._cached(f"artist:{aid}", 3 * DAY, lambda: self._artist(self._get(f"/artist/{aid}")))

    def artist_by_name(self, name):
        r = self.search_artists(name, 3)
        n = flt.norm(name)
        for a in r:
            if flt.norm(a["name"]) == n:
                return a
        return r[0] if r else None

    def related(self, aid, limit=8):
        d = self._get(f"/artist/{aid}/related", limit=limit)
        return [self._artist(a) for a in d.get("data", [])]

    # --- треки
    def track(self, x, album=None):
        """Приводит объект трека Deezer к внутреннему формату (с разметкой оригинал/ремикс)."""
        art = x.get("artist") or {}
        alb = x.get("album") or album or {}
        title = x.get("title") or x.get("title_short") or ""
        ecl = x.get("explicit_content_lyrics")
        exp = bool(x.get("explicit_lyrics")) or ecl == 1
        c = flt.classify(art.get("name", ""), title, extra=alb.get("title", "") if alb.get("record_type") != "single" else "", title_only=True)
        tags = set(c["tags"])
        # сам альбом может быть «Karaoke Hits», «Tribute to…» — проверяем его название тоже
        tags |= {t for t in flt.junk_tags(alb.get("title", ""), art.get("name", ""), True) if t in flt.STRONG}
        return dict(
            id="dz" + str(x["id"]), kind="cat", src=f"dz:{x['id']}", did=x["id"], title=title, artist=art.get("name", ""),
            aid=art.get("id"), album=alb.get("title", ""), alid=alb.get("id"), dur=x.get("duration", 0),
            cover=alb.get("cover_medium") or alb.get("cover_big") or alb.get("cover"), exp=exp, bad=(ecl == 3),
            tags=sorted(tags), cat=True, rank=x.get("rank", 0), plays=0, fav=False, last=0,
        )

    def search_tracks(self, q, limit=40):
        d = self._get("/search", q=q, limit=limit)
        return [self.track(x) for x in d.get("data", []) if x.get("type") == "track"]

    def top(self, aid, limit=50):
        def go():
            d = self._get(f"/artist/{aid}/top", limit=limit)
            return d.get("data", [])
        return [self.track(x) for x in self._cached(f"top:{aid}:{limit}", DAY, go)]

    # --- альбомы
    def albums(self, aid):
        def go():
            out, url_idx = [], 0
            while url_idx < 500:
                d = self._get(f"/artist/{aid}/albums", limit=100, index=url_idx)
                out += d.get("data", [])
                if not d.get("next"):
                    break
                url_idx += 100
            return [dict(id=a["id"], title=a["title"], cover=a.get("cover_medium") or a.get("cover_big"),
                         date=a.get("release_date", ""), type=a.get("record_type", "album"), exp=bool(a.get("explicit_lyrics")))
                    for a in out]
        r = self._cached(f"albums:{aid}", 3 * DAY, go)
        # без сборников и «Karaoke/Tribute»-альбомов; дубли изданий (Deluxe/Remastered) схлопываем
        r = [a for a in r if a["type"] not in ("compile",) and not (set(flt.junk_tags(a["title"], "", True)) & flt.STRONG.keys())]
        seen, res = {}, []
        for a in sorted(r, key=lambda a: a["date"], reverse=True):
            k = (flt.base_title(a["title"]), a["type"])
            if k not in seen:
                seen[k] = a
                res.append(a)
            elif a["exp"] and not seen[k]["exp"]:
                res[res.index(seen[k])] = a
                seen[k] = a
        return res

    def album_tracks(self, alid, album=None):
        def go():
            return self._get(f"/album/{alid}/tracks", limit=200).get("data", [])
        meta = album or {"id": alid}
        out = []
        for i, x in enumerate(self._cached(f"albtr:{alid}", 3 * DAY, go), 1):
            t = self.track(x, meta)
            t["no"] = i
            out.append(t)
        return out

    def all_tracks(self, aid, albums=None, progress=None):
        """Все песни исполнителя: треки всех его альбомов/синглов, без дублей и без ремиксов."""
        albums = albums if albums is not None else self.albums(aid)
        done = [0]

        def one(a):
            try:
                ts = self.album_tracks(a["id"], dict(id=a["id"], title=a["title"], cover_medium=a["cover"], record_type=a["type"]))
            except Exception:  # noqa: BLE001
                ts = []
            done[0] += 1
            if progress:
                progress(done[0], len(albums))
            return ts
        res = []
        for ts in self.pool.map(one, albums):
            res += [t for t in ts if t.get("aid") == aid]  # только свои треки, не чужие фиты из сборников
        res = [t for t in res if flt.is_original(t["tags"])]
        for t in res:
            t["sc"] = t.get("rank", 0)
        return flt.dedupe(res, scorefn=lambda t: (t.get("exp", False), t.get("rank", 0)))


# ───────── Last.fm (необязательно — нужен бесплатный ключ в настройках) ─────────
def lastfm_stats(key, artist):
    try:
        d = http_json("https://ws.audioscrobbler.com/2.0/?" + up.urlencode(
            dict(method="artist.getinfo", artist=artist, api_key=key, format="json", autocorrect=1)))
        st = d["artist"]["stats"]
        t = http_json("https://ws.audioscrobbler.com/2.0/?" + up.urlencode(
            dict(method="artist.gettoptracks", artist=artist, api_key=key, format="json", limit=10, autocorrect=1)))
        pcs = [int(x["playcount"]) for x in t["toptracks"]["track"]]
        return dict(listeners=int(st["listeners"]), playcount=int(st["playcount"]), avg_top=sum(pcs) / len(pcs) if pcs else 0)
    except Exception:  # noqa: BLE001
        return None


# ───────── тексты (LRCLIB) ─────────
def parse_lrc(s):
    import re
    out = []
    for ln in s.splitlines():
        txt = re.sub(r"\[[^\]]*\]", "", ln).strip()
        for mm, ss in re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", ln):
            out.append((int(mm) * 60 + float(ss), txt or "♪"))
    return sorted(out)


def clean_title(s):
    import re
    s = re.sub(r"[\(\[][^\)\]]*(official|video|audio|lyric|explicit|clip|клип|hd|4k|prod|uncensored)[^\)\]]*[\)\]]", "", s, flags=re.I)
    s = re.sub(r"\b(official (music )?video|lyric video|lyrics|explicit|uncensored)\b", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" -–|")


def fetch_lyrics(artist, title):
    a, t = clean_title(artist), clean_title(title)
    key = f"{a}|{t}".lower()
    c = cache_get(LYR, key, 365 * DAY)
    if c is not None:
        return c
    q = up.quote

    def js(u):
        try:
            return http_json(u, tries=1)
        except Exception:  # noqa: BLE001
            return None
    d = js(f"https://lrclib.net/api/get?artist_name={q(a)}&track_name={q(t)}") if a else None
    if not d or not (d.get("syncedLyrics") or d.get("plainLyrics")):
        d = None
        for u in (f"https://lrclib.net/api/search?q={q((a + ' ' + t).strip())}", f"https://lrclib.net/api/search?track_name={q(t)}"):
            r = [x for x in (js(u) or []) if isinstance(x, dict) and (x.get("syncedLyrics") or x.get("plainLyrics"))]
            if r:
                d = r[0]
                break
    res = {"synced": (d or {}).get("syncedLyrics") or "", "plain": (d or {}).get("plainLyrics") or ""}
    if d:
        cache_put(LYR, key, res)
    return res
