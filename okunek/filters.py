"""Фильтр «только оригиналы» + ранжирование + подбор потока под треки каталога.

Логика, а не набор слов: каждое совпадение относится к категории (ремикс, мэшап, кавер, ускоренная
версия, караоке, подборка, лайв, «версия»). Слова, которые пользователь сам написал в запросе,
в расчёт не берутся — «linkin park numb live» найдёт лайв, а просто «numb» — нет.
Модуль чистый (без GUI и сети), покрыт тестами в tests/test_filters.py.
"""
import math
import re

I = re.I

# ── сильные признаки: ищем по всему тексту ────────────────────────────────────────
STRONG = {
    "remix": re.compile(
        r"\bre-?mix(?:ed|es)?\b|\brmx\b|ремикс|\brefix\b|\brework(?:ed)?\b|\bbootleg\b|\bre-?edit\b"
        r"|\bremake\b|\bremade\b|\bdub mix\b|\b(?:vip|flip) (?:mix|edit|remix)\b"
        r"|\b(?:club|extended|dance|dnb|dubstep|techno|house|trap|hardstyle|phonk|festival|bass) (?:mix|remix|edit)\b", I),
    "mashup": re.compile(r"mash[\s-]?up|мэш?-?ап|\bmegamix\b|\bmedley\b|\bblend\b|\s(?:vs\.?|versus)\s", I),
    "cover": re.compile(
        r"\bcover(?:ed)? (?:by|version|song)\b|\b(?:acoustic|piano|guitar|violin|drum|vocal|metal|rock|female|male|band) covers?\b|кавер|\btribute\b|\bin the style of\b|\boriginally performed\b|\bmade famous by\b"
        r"|\bperformed by\b|\bsung by\b|\bfan[\s-]?made\b|\bai (?:cover|voice|generated)\b|\bai-generated\b", I),
    "speed": re.compile(
        r"sped[\s-]?up|speed(?:ed)?[\s-]?up|slowed|nightcore|daycore|\b8d\b"
        r"|\b(?:bass|treble)[\s-]?boost(?:ed)?\b|\breverb\b|\bpitched\b|\bchipmunk\b", I),
    "karaoke": re.compile(
        r"karaoke|караоке|\bbacking track\b|\bminus(?:ovka)?\b|минус(?:овка)?|\ba ?cappella\b"
        r"|\bmusic box\b|\b(?:piano|guitar|violin|orchestral|lofi|lo-fi) (?:cover|version|tribute)\b", I),
    "compilation": re.compile(
        r"\bfull album\b|\bcompilation\b|\bbest of\b|\btop \d+\b|\b\d+\s*(?:hours?|hrs?)\b|\bplaylist\b"
        r"|\bhits? (?:mix|collection)\b|\btype beat\b|\breaction\b|\btutorial\b|\blesson\b|\bhow to\b", I),
}
# ── слабые признаки: только в скобках и «хвосте» названия («Title - Live at …») ───────
WEAK = {
    "live": re.compile(
        r"\blive\b|\bconcert\b|\bunplugged\b|\bsessions?\b|\bperformance\b|\btiny desk\b|\brecorded live\b|концерт"
        r"|\bat (?:the )?[\w' ]{2,30}\b(?:arena|stadium|festival|garden|hall|theat(?:re|er)|studios?)\b", I),
    "cover": re.compile(r"\bcovers?\b", I),
    "version": re.compile(r"\binstrumental\b|\bacoustic\b|\bdemo\b|\bsnippet\b|\bpreview\b|\bunreleased\b|\bleaked?\b|\bteaser\b", I),
}
# мягкие: «радио-версия», «extended» — это оригинал, но не самая каноничная запись → небольшой штраф
SOFT = re.compile(r"\bradio edit\b|\bextended\b|\bsingle version\b|\balbum version\b|\bedit\b", I)

HARD_TAGS = set(STRONG) | set(WEAK)

BAD = re.compile(  # «чистые»/цензурные версии
    r"(?<!un)censored|\b(?:clean (?:version|edit|radio)|radio (?:edit|version)|edited version|family friendly|tv edit|bleeped)\b"
    r"|[\(\[]\s*clean\s*[\)\]]|[-–|]\s*clean\s*$|без мата|без ненормативной|цензура", I)
GOOD = re.compile(r"explicit|uncensored|\bdirty\b|без цензуры|18\+|uncut|raw version", I)
OFFICIAL = re.compile(r"\bofficial (?:audio|music video|video|lyric video|visuali[sz]er)\b|provided to youtube|auto-generated|\bvevo\b", I)

_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_BRACKET_IN = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_TAIL = re.compile(
    r"\s[-–—]\s*(?:remaster(?:ed)?(?:\s*\d{4})?|\d{4}\s*remaster(?:ed)?|radio edit|single version|album version|mono|stereo"
    r"|deluxe.*|explicit|clean|bonus track)\s*$", I)
_FEAT = re.compile(r"\b(?:feat\.?|ft\.?|featuring|при уч\.?|с уч\.?)\s.*$", I)
_SPLIT_ARTIST = re.compile(r"\s*(?:,|;|/|&|\bfeat\.?|\bft\.?|\bfeaturing\b|\bx\b|\band\b)\s*", I)
_DASH = re.compile(r"\s[-–—|]\s")
_URL = re.compile(r"^(?:https?://|www\.)\S+$", I)


def norm(s):
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[\W_]+", " ", s).strip()


def is_url(s):
    return bool(_URL.match((s or "").strip()))


def primary_artist(a):
    return _SPLIT_ARTIST.split(a or "", 1)[0].strip()


def base_title(s):
    """Название без (feat. …), [Remastered], «- Radio Edit» — для сравнения и дедупликации."""
    s = _BRACKETS.sub(" ", s or "")
    s = _TAIL.sub("", s)
    s = _FEAT.sub("", s)
    return norm(s)


def track_key(artist, title):
    return norm(primary_artist(artist)) + "|" + base_title(title)


def _segments(text, title_only):
    segs = _BRACKET_IN.findall(text)
    parts = _DASH.split(text)
    # «Artist - Title - хвост» (3+ частей) или, для чистого названия трека, «Title - хвост»
    segs += parts[1:] if title_only else parts[2:]
    return segs


def junk_tags(text, query="", title_only=False):
    """Какие признаки «не оригинала» есть в тексте. Слова из запроса пользователя игнорируются."""
    q = norm(query)
    tags = set()
    for k, rx in STRONG.items():
        for m in rx.finditer(text or ""):
            if norm(m.group(0)) and norm(m.group(0)) in q:
                continue
            tags.add(k)
            break
    for seg in _segments(text or "", title_only):
        for k, rx in WEAK.items():
            m = rx.search(seg)
            if m and norm(m.group(0)) not in q:
                tags.add(k)
    return tags


def is_original(tags):
    return not (set(tags) & HARD_TAGS)


def classify(artist, title, query="", extra="", title_only=False):
    """Единая разметка трека: теги, explicit/clean, «официальность»."""
    raw = f"{artist} - {title}" if artist else title
    if title_only:  # название из каталога: «Song - Live» — хвост относится к названию, артист проверяется отдельно
        tags = junk_tags(title + " " + extra, query, True) | {x for x in junk_tags(artist or "", query) if x in STRONG}
    else:
        tags = junk_tags(raw + " " + extra, query, False)
    flags_src = f"{raw} {extra}"
    return dict(
        tags=sorted(tags),
        exp=bool(GOOD.search(flags_src)),
        bad=bool(BAD.search(flags_src)),
        soft=bool(SOFT.search(raw)),
        off=bool(OFFICIAL.search(flags_src)),
    )


def query_words(queries):
    stop = {"explicit", "uncensored", "песни", "official", "original", "audio", "topic"}
    return sorted({w for q in queries for w in norm(q).split()} - stop)


def score_web(t, words, uncens=True, originals=True):
    """Оценка найденного трека (чем больше, тем выше в списке)."""
    name = norm(f"{t['artist']} {t['title']}")
    s = 2.0 * sum(1 for w in words if w in name)
    if uncens and t.get("exp"):
        s += 2.0
    if uncens and t.get("bad"):
        s -= 4.0
    junk = bool(set(t.get("tags", ())) & HARD_TAGS)
    if originals:
        if junk:
            s -= 6.0
        if t.get("off"):
            s += 2.5
        if t.get("topic"):
            s += 3.0
        if t.get("soft"):
            s -= 1.0
    elif junk:
        s -= 1.5
    if t.get("cat"):
        s += 3.0  # запись из официального каталога — лучший источник «оригинала»
    d = t.get("dur") or 0
    if 90 <= d <= 480:
        s += 0.6
    if d and (d < 60 or d > 600):
        s -= 1.0
    v = t.get("views") or 0
    if v > 0:
        s += min(2.0, math.log10(v + 1) / 4)
    return s


def passes(t, originals=True, uncens=True):
    """Жёсткий отсев перед показом."""
    if originals:
        if set(t.get("tags", ())) & HARD_TAGS:
            return False
        d = t.get("dur") or 0
        if d and d > 720 and not t.get("off") and not t.get("cat"):
            return False
    if uncens and t.get("bad") and not t.get("exp"):
        return False
    return True


def match_score(cand, artist, title, dur):
    """Насколько видео-кандидат подходит как «звук» для трека каталога. Выше — лучше."""
    ct = norm(cand.get("title") or "")
    ch = cand.get("channel") or cand.get("uploader") or ""
    bt = base_title(title)
    s = 0.0
    if bt and bt in ct:
        s += 3
    else:
        toks = bt.split()
        hit = sum(1 for w in toks if w in ct.split())
        s += 3.0 * hit / max(1, len(toks)) - 2
    pa = norm(primary_artist(artist))
    if pa and (pa in ct or pa in norm(ch)):
        s += 2
    if ch.endswith("- Topic"):
        s += 4
    elif re.search(r"vevo|official", ch, I):
        s += 1.5
    if OFFICIAL.search(cand.get("title") or ""):
        s += 1
    cd = cand.get("duration") or 0
    if dur and cd:
        d = abs(cd - dur)
        s += 4 if d <= 2 else 3 if d <= 5 else 1 if d <= 10 else (-4 if d > 20 else -1)
    if set(junk_tags(f"{cand.get('title') or ''} {ch}", f"{artist} {title}")) & HARD_TAGS:
        s -= 8
    v = cand.get("view_count") or 0
    if v > 0:
        s += min(2.0, math.log10(v + 1) / 4)
    return s


def best_candidate(cands, artist, title, dur, floor=1.0):
    """Лучший кандидат или None, если ничего достойного (лучше ошибка, чем ремикс)."""
    best, bs = None, floor
    for c in cands:
        if not c or not (c.get("url") or c.get("webpage_url")):
            continue
        s = match_score(c, artist, title, dur)
        if s > bs:
            best, bs = c, s
    return best


def dedupe(tracks, keyfn=lambda t: track_key(t["artist"], t["title"]), scorefn=lambda t: t.get("sc", 0)):
    """Один трек — одна строка: оставляем самую качественную запись из дублей."""
    best = {}
    order = []
    for t in tracks:
        k = keyfn(t)
        if k not in best:
            best[k] = t
            order.append(k)
        elif scorefn(t) > scorefn(best[k]):
            best[k] = t
    return [best[k] for k in order]
