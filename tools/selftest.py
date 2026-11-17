#!/usr/bin/env python3
"""SandikRadar kendi kendini test — ağ/TikTokLive olmadan çekirdek mantığı doğrular.

    python tools/selftest.py

Kapsam:
  * GiftFlow combo sayımı (repeat_count farkı, yeni tur, çok gönderen)
  * zarf yakalanınca akış satırının `envelope_id` ile işaretlenmesi
  * collect._gift_fields / _envelope_fields alan eşlemesi (sahte event nesneleri)
  * build_snapshot sekme sayaçları (flow sekmesi > 0)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

import collect as C  # noqa: E402
import livecore as L  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name} = {got}")
    else:
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
        FAILS.append(name)


class FakeUser:
    def __init__(self, unique_id, nickname=""):
        self.unique_id = unique_id
        self.nickname = nickname or unique_id


class FakeGift:
    def __init__(self, gid, name, diamonds):
        self.id = gid
        self.name = name
        self.diamond_count = diamonds


class FakeGiftEvent:
    def __init__(self, user, gift, repeat_count=1, repeat_end=True):
        self.user = FakeUser(user, user.title())
        self.gift = FakeGift(*gift)
        self.repeat_count = repeat_count
        self.repeat_end = repeat_end


class FakeEnvelopeInfo:
    def __init__(self, envelope_id, diamonds, people, unpack_at, skin_id=1):
        self.envelope_id = envelope_id
        self.room_id = "7001"
        self.diamond_count = diamonds
        self.people_count = people
        self.unpack_at = unpack_at
        self.skin_id = skin_id


class FakeEnvelopeEvent:
    def __init__(self, info):
        self.envelope_info = info


def test_gift_flow() -> None:
    print("GiftFlow")
    meta = {"user": "yayinci", "nickname": "Yayıncı", "viewers": 120, "room_id": "7001"}
    flow = L.GiftFlow()

    # combo: ayni hediye 1 -> 2 -> 3 tekrar; her mesajda 10 jeton
    g1 = flow.add_gift("@yayinci", meta, user="ayse", gift_id="5655", diamonds=10, repeat_count=1)
    g2 = flow.add_gift("@yayinci", meta, user="ayse", gift_id="5655", diamonds=10, repeat_count=2)
    g3 = flow.add_gift("@yayinci", meta, user="ayse", gift_id="5655", diamonds=10, repeat_count=3)
    # yeni tur: sayac bastan basliyor
    g4 = flow.add_gift("@yayinci", meta, user="ayse", gift_id="5655", diamonds=10, repeat_count=1)
    # baska gonderen, combo olmayan hediye (repeat_count=1 her mesajda)
    g5 = flow.add_gift("@yayinci", meta, user="mert", gift_id="999", diamonds=500, repeat_count=1)
    g6 = flow.add_gift("@yayinci", meta, user="mert", gift_id="999", diamonds=500, repeat_count=1)

    check("combo artisi 1. adim", g1, 10)
    check("combo artisi 2. adim", g2, 10)
    check("combo artisi 3. adim", g3, 10)
    check("yeni combo turu", g4, 10)
    check("tekrarli hediye 1", g5, 500)
    check("tekrarli hediye 2", g6, 500)

    rows = flow.rows(now_ms=int(time.time() * 1000), window_seconds=120)
    check("akis satiri sayisi", len(rows), 1)
    row = rows[0]
    check("kind", row["kind"], "live")
    check("toplam jeton", row["gift_coins"], 1040)  # 4×10 combo + 2×500
    check("gonderen sayisi", row["gift_senders"], 2)
    check("dakikalik hiz", row["diamonds_per_min"], 520.0)  # 1040/120*60
    check("combo yok: envelope_id bos", row["envelope_id"], "")
    check("gift_top ilk gonderen", row["gift_top"][0], ["mert", 1000])

    flow.mark_envelope("@yayinci", meta, "env-42")
    row = flow.rows(now_ms=int(time.time() * 1000), window_seconds=120)[0]
    check("zarf isaretlendi", row["envelope_id"], "env-42")
    check("derive has_envelope", L.derive(row, int(time.time() * 1000))["has_envelope"], True)

    # hediye gelmeyen oda satir uretmemeli
    empty = L.GiftFlow()
    empty.touch("@sessiz", {"user": "sessiz"})
    check("hediyesiz oda satiri", len(empty.rows()), 0)


def test_event_fields() -> None:
    print("event -> alan eslemesi")
    ev = FakeGiftEvent("ayse", ("5655", "Rose", 1), repeat_count=7, repeat_end=False)
    f = C._gift_fields(ev)
    check("gift_id", f["gift_id"], "5655")
    check("gift_name", f["gift_name"], "Rose")
    check("diamonds", f["diamonds"], 1)
    check("repeat_count", f["repeat_count"], 7)
    check("repeat_end", f["repeat_end"], False)
    check("sender", f["user"], "ayse")

    env = FakeEnvelopeEvent(FakeEnvelopeInfo("env-1", 5000, 50, int(time.time()) + 60))
    ef = C._envelope_fields(env.envelope_info, {"room_id": "7001"})
    check("envelope diamond_count", ef["diamond_count"], 5000)
    check("envelope people_count", ef["people_count"], 50)
    chest = L.chest_from_envelope_fields(ef, {"user": "yayinci", "nickname": "Y"})
    check("sandik kind", chest["kind"], "chest")
    check("sandik slots", chest["slots"], 50)


def test_snapshot_counts() -> None:
    print("snapshot / sekme sayaclari")
    now = int(time.time() * 1000)
    rooms = L.sim_flow_rooms(now)
    snap = L.build_snapshot("sim", rooms, now, demo=True)
    check("akis satiri sayisi", snap["total"], len(rooms))
    check("flow sekmesi dolu", snap["tab_counts"]["flow"] > 0, True)
    check("chest sekmesi bos", snap["tab_counts"]["chest"], 0)
    live = snap["rooms"][0]
    check("status", live["status"], "open")
    check("ratio = bin jeton/dk", live["ratio"], round(live["diamonds_per_min"] / 1000, 2))
    json.dumps(snap)  # serileştirilebilir olmalı


def main() -> int:
    test_gift_flow()
    test_event_fields()
    test_snapshot_counts()
    print()
    if FAILS:
        print(f"{len(FAILS)} test BASARISIZ: {', '.join(FAILS)}")
        return 1
    print("tum testler gecti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
