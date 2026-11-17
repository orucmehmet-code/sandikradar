"""SandikRadar cekirdegi — yalnizca Python standart kutuphanesi.

Panelin (docs/app.js), GitHub Actions iscisinin (collector/collect.py) ve yerel
koprunun (local-server/bridge.py) paylastigi tek mantik kaynagi:

  * TABS            : sekmeler ve on ayar filtreleri
  * derive()        : turetilmis alanlar (ratio, seconds_left, delta, status)
  * apply_filters() : filtre + siralama motoru (backend/filters.py'nin aynisi)
  * sim_rooms()     : deterministik sentetik oda akisi (DEMO)
  * euler_feed()    : EulerStream /webcast/feed kesif ucu (Business plan)
  * chest_from_envelope_fields() : websocket zarf alanlari -> oda sozlugu
  * check_live()    : imzasiz/anahtarsiz gercek canli kontrolu (TikTok web uclari)
  * send_telegram() : Telegram Bot API (CORS/HTTP, bagimlilik yok)
"""

from __future__ import annotations

import json
import math
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

APP = "SandikRadar"
VERSION = "1.0.0"

# --------------------------------------------------------------------- sekmeler
# LiveMira'da bunlarin bir kismi Plus/Pro'ya kilitliydi; burada hepsi acik.
TABS: list[dict] = [
    {"id": "chest", "label": {"tr": "Sandık", "vi": "Rương", "en": "Chest"}, "plan": "free",
     "filter": {"kind": "chest"}},
    {"id": "bag", "label": {"tr": "Çanta", "vi": "Túi", "en": "Bag"}, "plan": "free",
     "filter": {"kind": "bag"}},
    {"id": "ratio2", "label": {"tr": "Oran ≥ 2", "vi": "Ratio ≥ 2", "en": "Ratio ≥ 2"}, "plan": "plus",
     "filter": {"min_ratio": 2}},
    {"id": "ratio4", "label": {"tr": "Oran ≥ 4", "vi": "Ratio ≥ 4", "en": "Ratio ≥ 4"}, "plan": "plus",
     "filter": {"min_ratio": 4}},
    {"id": "level01", "label": {"tr": "Çanta Lv 0–1", "vi": "Túi level 0–1", "en": "Bag Lv 0–1"}, "plan": "plus",
     "filter": {"kind": "bag", "variants": ["l0", "l1"]}},
    {"id": "hanging", "label": {"tr": "Askıda sandık", "vi": "Rương treo", "en": "Hanging chest"}, "plan": "pro",
     "filter": {"kind": "chest", "variants": ["hanging"]}},
    {"id": "kismet", "label": {"tr": "Kısmet (oran ≥ 7)", "vi": "Nhân phẩm (ratio ≥ 7)", "en": "Lucky (ratio ≥ 7)"}, "plan": "pro",
     "filter": {"min_ratio": 7}},
    {"id": "gold", "label": {"tr": "Altın sandık", "vi": "Rương vàng", "en": "Gold chest"}, "plan": "pro",
     "filter": {"kind": "chest", "variants": ["gold"]}},
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")


# ------------------------------------------------------------------ turetilmis
def derive(room: dict, now_ms: int) -> dict:
    """Hesaplanan alanlari ekle (backend/store.py derive ile ayni)."""
    coins = int(room.get("coins") or 0)
    slots = max(1, int(room.get("slots") or 1))
    opens_at = int(room.get("opens_at") or 0)
    left = max(0, opens_at - now_ms)
    out = dict(room)
    # LiveMira'daki "ratio" = 1000 jeton basina dusen kontenjan payi.
    out["ratio"] = round(coins / slots / 1000, 2)
    out["seconds_left"] = round(left / 1000)
    out["delta"] = round((opens_at - now_ms) / 1000)
    out["status"] = "open" if left <= 0 else "upcoming"
    out["viewers_lt_slots"] = bool(int(room.get("viewers") or 0) < slots)
    if out.get("kind") == "bag" and out.get("joined"):
        out["odds"] = round(slots / max(1, int(out["joined"])), 3)
    return out


# --------------------------------------------------------------------- filtre
def _f(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def apply_filters(rooms: Iterable[dict], params: dict) -> list[dict]:
    """backend/filters.py apply_filters'in birebir karsiligi."""
    params = params or {}
    kind = str(params.get("kind") or "all").lower()
    variants = _as_list(params.get("variants"))
    levels = _as_list(params.get("levels"))
    status = str(params.get("status") or "all").lower()

    min_coins = _f(params.get("min_coins"))
    max_coins = _f(params.get("max_coins"))
    min_ratio = _f(params.get("min_ratio"))
    max_ratio = _f(params.get("max_ratio"))
    min_time = _f(params.get("min_time"))
    max_time = _f(params.get("max_time"))
    max_viewers = _f(params.get("max_viewers"))
    only_viewers_lt_slots = str(params.get("viewers_lt_slots") or "").lower() in ("1", "true", "on")
    hide_late = _f(params.get("hide_late"))

    out = []
    for room in rooms:
        if kind != "all" and room.get("kind") != kind:
            continue
        if variants and room.get("variant") not in variants:
            continue
        if levels and room.get("variant") not in [f"l{v.lstrip('lL')}" for v in levels]:
            continue
        if status == "upcoming" and room.get("status") != "upcoming":
            continue
        if status == "open" and room.get("status") != "open":
            continue
        if min_coins is not None and float(room.get("coins") or 0) < min_coins:
            continue
        if max_coins is not None and float(room.get("coins") or 0) > max_coins:
            continue
        if min_ratio is not None and float(room.get("ratio") or 0) < min_ratio:
            continue
        if max_ratio is not None and float(room.get("ratio") or 0) > max_ratio:
            continue
        left = float(room.get("seconds_left") or 0)
        if min_time is not None and left < min_time:
            continue
        if max_time is not None and left > max_time:
            continue
        if max_viewers is not None and float(room.get("viewers") or 0) > max_viewers:
            continue
        if only_viewers_lt_slots and not room.get("viewers_lt_slots"):
            continue
        if hide_late is not None and float(room.get("delta") or 0) < -hide_late:
            continue
        out.append(room)

    sort = str(params.get("sort") or "opens_at").lower()
    reverse = str(params.get("desc") or "").lower() in ("1", "true", "on")
    keys = {
        "opens_at": lambda r: int(r.get("opens_at") or 0),
        "coins": lambda r: int(r.get("coins") or 0),
        "ratio": lambda r: float(r.get("ratio") or 0),
        "viewers": lambda r: int(r.get("viewers") or 0),
        "left": lambda r: float(r.get("seconds_left") or 0),
    }
    out.sort(key=keys.get(sort, keys["opens_at"]), reverse=reverse)
    return out


def tab_counts(rooms: Iterable[dict], params: dict | None = None) -> dict[str, int]:
    """Her sekmenin sayaci tum havuzdan hesaplanir (aktif filtreden bagimsiz)."""
    rooms = list(rooms)
    params = params or {}
    out = {}
    for tab in TABS:
        merged = {**params, **{k: v for k, v in (tab.get("filter") or {}).items()}}
        out[tab["id"]] = len(apply_filters(rooms, merged))
    return out


def snapshot(rooms: Iterable[dict], now_ms: int) -> list[dict]:
    """Zamanla degisen alanlari tazele (store.snapshot karsiligi)."""
    out = []
    for room in rooms:
        item = dict(room)
        delta = int(item.get("opens_at") or 0) - now_ms
        item["seconds_left"] = round(max(0, delta) / 1000)
        item["delta"] = round(delta / 1000)
        item["status"] = "open" if delta <= 0 else "upcoming"
        out.append(item)
    return out


# ------------------------------------------------------------------ DEMO akisi
AVATAR_SEED = "https://api.dicebear.com/9.x/adventurer/svg?seed="

_FIRST = [
    "linh", "mai", "trang", "huy", "nam", "thao", "quynh", "duy", "khoa", "vy",
    "elif", "zeynep", "mert", "defne", "kerem", "selin", "burak", "ecem",
    "mira", "nova", "luna", "aria", "kaira", "sena", "deniz", "ada",
]
_SUFFIX = ["live", "tv", "official", "vn", "tr", "22", "9x", "cuti", "xinh", "gaming"]

_TITLES_CHEST = [
    "Rương vàng 500k đang chờ cả nhà 🎁",
    "Sandık açılıyor, kaçırmayın!",
    "Rương treo 1 triệu xu — 21:00",
    "Ai nhanh tay nhận 200k xu nào",
    "Bugün şanslı gününüz 🍀 sandık geliyor",
    "Rương thường nhưng view siêu ít 👀",
    "Come grab the chest with me!",
    "Túi xu + rương cùng lúc, vào nhanh",
]
_TITLES_BAG = [
    "Túi xu level 3 — chỉ 40 suất",
    "Level 5 túi, ai cũng có phần 🎉",
    "Çanta dağıtıyorum, 5 dakika!",
    "Bình luận để nhận túi xu nhé",
    "Goody bag level 2, view < slot",
    "Túi xu 150k, vào là có",
    "Free coins bag — hurry up",
    "Akşam çantası, herkese yeter",
]


def _pick_name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)}{rng.choice(_SUFFIX)}{rng.randint(0, 99)}"


def sim_room(seed: int, now_ms: int) -> dict:
    rng = random.Random(seed)
    kind = "chest" if rng.random() < 0.62 else "bag"
    target_ratio = math.exp(rng.uniform(math.log(0.3), math.log(18)))
    if kind == "chest":
        variant = rng.choices(["normal", "gold", "hanging"], [0.62, 0.23, 0.15])[0]
        slots = rng.choice([5, 10, 20, 40, 100, 200])
        coins = int(target_ratio * 1000 * slots)
        joined = 0
        title = rng.choice(_TITLES_CHEST)
    else:
        level = rng.choices([0, 1, 2, 3, 4, 5], [0.18, 0.24, 0.2, 0.16, 0.12, 0.1])[0]
        variant = f"l{level}"
        slots = rng.choice([20, 40, 60, 100, 200, 500])
        coins = int(target_ratio * (1 + level * 0.2) * 1000 * slots)
        joined = int(slots * rng.uniform(0.2, 3.4))
        title = rng.choice(_TITLES_BAG)

    offset = rng.choices(
        [-20_000, 60_000, 180_000, 420_000, 900_000, 1_500_000],
        [0.1, 0.22, 0.24, 0.2, 0.16, 0.08],
    )[0]
    opens_at = now_ms + offset + rng.randint(-15_000, 15_000)

    viewer_base = rng.choices([8, 45, 180, 900, 4_000, 15_000], [0.22, 0.26, 0.22, 0.16, 0.1, 0.04])[0]
    viewers = max(3, int(viewer_base * rng.uniform(0.55, 1.9)))

    name = _pick_name(rng)
    return {
        "id": f"sim:{seed}",
        "user": name,
        "nickname": name.replace("_", " ").title(),
        "avatar": AVATAR_SEED + name,
        "title": title,
        "kind": kind,
        "variant": variant,
        "coins": coins,
        "slots": slots,
        "joined": joined,
        "viewers": viewers,
        "opens_at": opens_at,
        "room_id": "",   # uydurma kimlik derin baglantiyi kirletirdi
        "thumb": "",
        "lang": "tr" if rng.random() < 0.35 else "vi",
    }


def sim_rooms(now_ms: int | None = None, size: int = 220) -> list[dict]:
    """Dakika kovasina gore deterministik, zamanla degisen sahte akis."""
    now_ms = int(now_ms or time.time() * 1000)
    bucket = now_ms // 60_000
    return [derive(sim_room(bucket * 1000 + i, now_ms), now_ms) for i in range(size)]


# ----------------------------------------------------------------- Euler feed
class ProviderError(RuntimeError):
    pass


def _get_json(url: str, headers: dict | None = None, timeout: float = 20) -> Any:
    req = urllib.request.Request(url, headers={"user-agent": UA, "accept": "application/json",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", "replace"))


def _first_url(obj) -> str:
    if isinstance(obj, dict):
        urls = obj.get("url_list") or obj.get("urlList") or []
        if urls:
            return urls[0]
        return _first_url(obj.get("m_urls") or obj.get("urls") or [])
    if isinstance(obj, list) and obj:
        return _first_url(obj[0])
    return ""


def euler_feed(api_key: str, region: str = "TR", timeout: float = 20) -> list[dict]:
    """EulerStream kesif ucu. Business plan yoksa 401 firlatir (mesaji ayirt et)."""
    if not api_key:
        raise ProviderError("EULER_API_KEY yok")
    url = "https://api.eulerstream.com/webcast/feed?" + urllib.parse.urlencode({"region": region})
    try:
        payload = _get_json(url, {"x-api-key": api_key}, timeout)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if exc.code == 401:
            raise ProviderError(f"401 — Business plan gerekli ya da anahtar gecersiz: {body}") from exc
        if exc.code == 429:
            raise ProviderError("429 — istek siniri (rate limit)") from exc
        raise ProviderError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

    data = ((payload.get("response") or {}).get("data") or {})
    rows = data.get("data") or []
    out = []
    for raw in rows:
        room = map_feed_room(raw, region)
        if room:
            out.append(room)
    return out


def map_feed_room(raw: dict, region: str = "TR") -> dict | None:
    owner = raw.get("owner") or {}
    user = owner.get("unique_id") or owner.get("uniqueId") or ""
    if not user:
        return None
    room_id = str(raw.get("id_str") or raw.get("id") or "")
    stats = raw.get("stats") or {}
    return {
        "room_id": room_id,
        "user": user,
        "nickname": owner.get("nickname") or user,
        "avatar": _first_url(owner.get("avatar_thumb") or owner.get("avatarThumb")),
        "title": raw.get("title") or "",
        "viewers": int(stats.get("total_user") or raw.get("user_count") or 0),
        "thumb": _first_url(raw.get("cover")),
        "region": region,
    }


SKIN_KINDS = {1: ("chest", "normal"), 2: ("chest", "gold"), 3: ("chest", "hanging")}


def chest_from_envelope_fields(fields: dict, meta: dict | None = None) -> dict | None:
    """Websocket zarf alanlari -> uygulama oda sozlugu (TikTokLive bagimsiz)."""
    coins = int(fields.get("diamond_count") or 0)
    slots = int(fields.get("people_count") or 0)
    if coins <= 0 and slots <= 0:
        return None
    skin = int(fields.get("skin_id") or 0)
    kind, variant = SKIN_KINDS.get(skin, ("chest", "normal"))
    unpack_at = int(fields.get("unpack_at") or 0)
    if unpack_at <= 0:
        unpack_at = int(time.time()) + 180
    meta = meta or {}
    room_id = str(fields.get("room_id") or meta.get("room_id") or "")
    envelope_id = str(fields.get("envelope_id") or "")
    rid = envelope_id or f"{room_id}-{unpack_at}"
    return {
        "id": f"chest:{rid}",
        "user": meta.get("user", ""),
        "nickname": meta.get("nickname", ""),
        "avatar": meta.get("avatar", ""),
        "title": meta.get("title", ""),
        "kind": kind,
        "variant": variant,
        "coins": coins,
        "slots": max(1, slots),
        "joined": 0,
        "viewers": int(meta.get("viewers") or 0),
        "opens_at": unpack_at * 1000 if unpack_at < 1e12 else unpack_at,
        "room_id": room_id,
        "thumb": meta.get("thumb", ""),
        "lang": meta.get("lang", "tr"),
        "skin_id": skin,
        "envelope_id": envelope_id,
        "source": "envelope",
    }


# --------------------------------------------- gercek canli kontrolu (imzasiz)
_SNSSDK_RE = re.compile(r"snssdk\d*://live\?.*?room_id=(\d+)", re.I)
_ROOM_ID_RE = re.compile(r"\broom_id=(\d+)", re.I)
_URL_USER_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._]+)", re.I)
_HANDLE_RE = re.compile(r"^@?([A-Za-z0-9._]{2,24})$")

USER_ROOM = "https://www.tiktok.com/api-live/user/room/"
CHECK_ALIVE = "https://webcast.tiktok.com/webcast/room/check_alive/"
ROOM_INFO = "https://webcast.tiktok.com/webcast/room/info/"


def parse_live_target(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("bos")
    m = _SNSSDK_RE.search(raw) or _ROOM_ID_RE.search(raw)
    if m:
        return {"handle": "", "room_id": m.group(1)}
    if raw.isdigit():
        return {"handle": "", "room_id": raw}
    m = _URL_USER_RE.search(raw)
    if m:
        return {"handle": m.group(1), "room_id": ""}
    m = _HANDLE_RE.match(raw)
    if m:
        return {"handle": m.group(1), "room_id": ""}
    raise ValueError(f"anlasilamadi: {raw[:60]}")


def user_room(handle: str, attempts: int = 3) -> dict:
    out = {"handle": handle.lstrip("@").lower(), "room_id": "", "nickname": "", "title": "",
           "status": None, "live": False, "error": ""}
    params = urllib.parse.urlencode({"aid": 1988, "uniqueId": out["handle"], "sourceType": 54})
    payload = None
    for i in range(max(1, attempts)):
        try:
            payload = _get_json(USER_ROOM + "?" + params, timeout=15) or {}
            break
        except Exception as exc:
            out["error"] = type(exc).__name__
            if i + 1 < attempts:
                time.sleep(0.8 + 0.7 * i)
    if payload is None:
        return out
    data = payload.get("data") or {}
    user = data.get("user") or {}
    room = data.get("liveRoom") or {}
    out["room_id"] = str(user.get("roomId") or "")
    out["nickname"] = user.get("nickname") or ""
    out["title"] = room.get("title") or ""
    out["status"] = room.get("status")
    out["error"] = "" if payload.get("statusCode") in (0, None) else str(payload.get("statusCode"))
    return out


def check_alive(room_ids: list[str]) -> dict[str, bool]:
    ids = [str(x) for x in room_ids if x]
    out: dict[str, bool] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            payload = _get_json(CHECK_ALIVE + "?" + urllib.parse.urlencode(
                {"aid": 1988, "room_ids": ",".join(chunk)}), timeout=20) or {}
            rows = payload.get("data") or []
            if isinstance(rows, dict):
                rows = []
            for row in rows:
                rid = str(row.get("room_id_str") or row.get("room_id") or "")
                if rid:
                    out[rid] = bool(row.get("alive"))
        except Exception:
            for rid in chunk:
                out.setdefault(rid, False)
    return out


def room_info(room_id: str) -> dict:
    try:
        payload = _get_json(ROOM_INFO + "?" + urllib.parse.urlencode(
            {"aid": 1988, "room_id": str(room_id)}), timeout=20) or {}
        data = payload.get("data") or {}
        owner = data.get("owner") or {}
        return {
            "room_id": str(data.get("id_str") or room_id),
            "title": data.get("title") or "",
            "viewers": int(data.get("user_count") or 0),
            "nickname": owner.get("nickname") or "",
            "avatar": _first_url(owner.get("avatar_thumb")),
            "thumb": _first_url(data.get("cover")),
        }
    except Exception:
        return {}


def check_live(target: str) -> dict:
    """Bir hesabin/linkin gercekten yayinda olup olmadigini sor (anahtar/imza yok)."""
    parsed = parse_live_target(target)
    handle, room_id = parsed["handle"], parsed["room_id"]
    out = {
        "target": target,
        "handle": handle,
        "room_id": room_id,
        "live": False,
        "url": f"https://www.tiktok.com/@{handle}/live" if handle else
               f"https://www.tiktok.com/live?room_id={room_id}",
        "title": "", "viewers": 0, "nickname": "", "detail": "",
    }
    if handle and not room_id:
        info = user_room(handle)
        room_id = info.get("room_id") or ""
        out["room_id"] = room_id
        out["nickname"] = info.get("nickname") or ""
        out["title"] = info.get("title") or ""
        out["detail"] = info.get("error") or ""
        if not room_id:
            out["detail"] = out["detail"] or "hesabin hic yayini yok"
            return out
    if room_id:
        alive = check_alive([room_id])
        out["live"] = bool(alive.get(str(room_id)))
        if out["live"]:
            extra = room_info(str(room_id))
            out["title"] = extra.get("title") or out["title"]
            out["viewers"] = int(extra.get("viewers") or 0)
            out["nickname"] = extra.get("nickname") or out["nickname"]
            out["url"] = f"https://www.tiktok.com/@{handle}/live" if handle else out["url"]
    return out


# ------------------------------------------------------------------- Telegram
def send_telegram(token: str, chat_id: str, text: str, timeout: float = 15) -> tuple[bool, str]:
    token = (token or "").strip()
    chat = str(chat_id or "").strip()
    if not token or not chat:
        return False, "bot_token veya chat_id bos"
    body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, resp.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:300]


def format_alert(room: dict) -> str:
    kind_label = "🎁 Sandık" if room.get("kind") == "chest" else "👜 Çanta"
    left = int(room.get("seconds_left") or 0)
    if left <= 0:
        when = "şimdi açık"
    elif left < 60:
        when = f"{left} sn sonra"
    else:
        when = f"{left // 60} dk {left % 60} sn sonra"
    return (
        f"<b>{kind_label}</b> · {int(room.get('coins') or 0):,} jeton · oran {room.get('ratio')}\n"
        f"@{room.get('user')} — {int(room.get('viewers') or 0):,} izleyici\n"
        f"⏱ {when}\n"
        f"https://www.tiktok.com/@{room.get('user')}/live"
    )


def matches(room: dict, cfg: dict) -> bool:
    if room.get("kind") not in (cfg.get("kinds") or ["chest", "bag"]):
        return False
    if float(room.get("ratio") or 0) < float(cfg.get("min_ratio") or 0):
        return False
    if float(room.get("coins") or 0) < float(cfg.get("min_coins") or 0):
        return False
    return True


# --------------------------------------------------------------------- cikti
def build_snapshot(provider: str, rooms: list[dict], now_ms: int, demo: bool,
                   notice: str = "", error: str = "") -> dict:
    now_ms = int(now_ms)
    fresh = snapshot(rooms, now_ms)
    return {
        "app": APP,
        "version": VERSION,
        "generated_at": now_ms,
        "provider": provider,
        "demo": bool(demo),
        "refresh_seconds": 60,
        "total": len(fresh),
        "tab_counts": tab_counts(fresh),
        "tabs": TABS,
        "notice": notice,
        "error": error,
        "rooms": fresh,
    }
