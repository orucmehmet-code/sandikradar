# SandıkRadar — GitHub Pages paneli + Actions veri işçisi

TikTok LIVE odalarındaki **sandık (chest)** ve **çanta (goody bag)** ödüllerini listeleyen,
filtreleyen ve uyaran panelin **tek klasörlük, sunucusuz sürümü**. Panel GitHub Pages'te
statik site olarak yayınlanır; veriyi **GitHub Actions işçisi** üretip repoya commit eder.
Bilgisayarında çalıştırmak istersen aynı klasörde **pip gerektirmeyen yerel köprü** var.

```
sandikradar-web/
├─ docs/                     ← GitHub Pages kökü (statik panel)
│  ├─ index.html  app.js  styles.css  sw.js  manifest.webmanifest  icon.svg
│  └─ data/rooms.json        ← Actions işçisinin ürettiği veri (otomatik commit)
├─ collector/
│  ├─ livecore.py            ← tek mantık kaynağı: filtre, türetme, DEMO, Euler, canlı kontrol, Telegram
│  └─ collect.py             ← CLI: docs/data/rooms.json üretir
├─ local-server/
│  ├─ bridge.py              ← yerel köprü (stdlib HTTP): /api/* + paneli servis eder
│  ├─ baslat.bat             ← Windows
│  └─ baslat.sh              ← Linux/macOS
└─ .github/workflows/
   ├─ deploy.yml             ← docs/ → GitHub Pages
   └─ collect.yml            ← 5 dakikada bir veri topla + commit
```

## 1) GitHub'a koy (5 dakika)

```bash
cd sandikradar-web
git init -b main
git add -A
git commit -m "SandıkRadar panel"
gh repo create sandikradar --public --source=. --remote=origin --push
```

Sonra **Settings → Pages → Build and deployment → Source: GitHub Actions** seç
(`gh api -X POST repos/KULLANICI/sandikradar/pages -f build_type=workflow` ile de olur).
`deploy-pages` işi bitince site şurada olur:

```
https://KULLANICI.github.io/sandikradar/
```

İlk açılışta veri **DEMO**'dur (sarı DEMO rozeti). Gerçek sandık için 2. bölüm.

## 2) Gerçek veri (EulerStream Business)

Gerçek sandık listesi iki parçadan oluşur: **keşif** (hangi hesaplar yayında) + **içerik**
(websocket'teki sandık zarfı). `collect.py` ikisini de yapar.

**Settings → Secrets and variables → Actions:**

| Tür | Ad | Değer |
|---|---|---|
| Secret | `EULER_API_KEY` | EulerStream Business anahtarı (`x-api-key`) |
| Variable | `EULER_REGIONS` | `TR,VN` (varsayılan `TR`) |
| Variable | `WATCHLIST` | `@hesap1,@hesap2` — feed olmadan da dinlenecek hesaplar (isteğe bağlı, ücretsiz Community planla da çalışır) |
| Variable | `MAX_ROOMS` | aynı anda dinlenecek oda sayısı (varsayılan 12, plan limitine göre) |

Anahtar girilince `collect.yml` otomatik olarak `TikTokLive` kütüphanesini kurar ve işçi
120–150 saniye boyunca odaları dinleyip `WebcastEnvelopeMessage` zarflarını toplar. Zarf
gelmezse **önceki liste korunur** (panel boşalmaz, `data/meta.json` içinde hata görünür).

Elde edilen alanlar: `diamond_count` → jeton, `people_count` → kontenjan, `unpack_at` → açılış
anı, `skin_id` → sandık/çanta türü, `envelope_id` → kararlı kimlik.

## 2a) İki katmanlı mantık: hediye jetonu akışı + zarf gelirse sandık

`collect.py` her dinlenen odada **iki olayı** birlikte işler:

| Olay | Ne üretir | Panelde |
|---|---|---|
| `GiftEvent` (hediye) | odanın jeton akışı: toplam jeton, dakikalık hız, gönderen sayısı, ilk 3 gönderen | **Jeton akışı** sekmesi (`kind: "live"`) |
| `EnvelopeEvent` (zarf) | sandık satırı: jeton, kontenjan, açılış anı, tür | **Sandık** sekmesi (`kind: "chest"`) |

Yani zarf gelmese de panel boş kalmaz: hediyelerden ölçülen gerçek jeton trafiği görünür.
Bir odada zarf yakalanırsa hem sandık satırı eklenir hem de o odanın akış satırı
`envelope_id` (→ `has_envelope`) ile "sandık var" diye işaretlenir.

- Combo hediyeler `repeat_count` farkı üzerinden sayılır (`livecore.GiftFlow`): 1-2-3 diye
  gelen tek bir combo 3 hediye sayılır, akış şişmez. Yeni combo turu baştan sayılır.
- `diamonds_per_min` = toplam jeton / gerçek dinleme süresi × 60 (abartılı hız çıkmasın diye
  pencere tüm dinleme süresidir).
- Ham kayıtlar `data/gifts.jsonl` ve `data/envelopes.jsonl` dosyalarına yazılır (repoya girmez).
- Alan eşlemesi kütüphane sürümleri arasında esnektir (`diamond_count` / `diamonds`,
  `unique_id` / `user_id`, `repeat_count` / `repeatCount`).

Çevrimdışı doğrulama (ağ/TikTokLive gerekmez):

```bash
python tools/selftest.py        # GiftFlow sayımı, zarf işaretleme, sekme sayaçları
python tools/selftest_live.py   # sahte TikTokLive ile uçtan uca _capture akışı
```

`selftest.py` kurulu TikTokLive paketi varsa **gerçek proto alanlarını** da doğrular
(`GiftEvent.gift.diamond_count`, `EnvelopeInfo.people_count`, …). Kütüphane sürüm
yükseltmesi alan adlarını değiştirirse test kırmızı olur.

## 2a-2) Gerçek yakalama: hesap listesi (`data/watchlist.txt`)

EulerStream Business anahtarı olmadan da gerçek veri toplanabilir: dinlenecek hesapları
yaz, toplayıcı o odalara websocket ile bağlanır.

```text
# data/watchlist.txt — bir satır bir hesap
@hesap1
@hesap2
https://www.tiktok.com/@hesap3/live
```

- Dosyada en az bir dolu satır varsa `collect.py` **otomatik olarak gerçek moda** geçer
  (`provider=euler`); boşsa panel DEMO'da kalır.
- Öncelik: `WATCHLIST` ortam değişkeni → `data/watchlist.txt` → `--watch @a,@b`.
- Elle deneme (dosyaya dokunmadan, çıktı geçici klasöre):

```bash
py -3.12 collector/collect.py --watch "@hesap1,@hesap2" --seconds 90 --out data/probe
```

- Bu makinede `TikTokLive` **py -3.12**'de kurulu (pompa de aynı yorumlayıcıyı kullanır:
  `tools/pump.bat` → `py -3.12 tools\pump.py`). Bağlantı kurulamazsa `meta.json` içinde
  sebep yazılır: `UserOfflineError` (hesap yayında değil), imza/anahtar hataları vb.
- **Bağlanma yolu:** `client.connect()` kullanılmaz; iptal anında `_clean_tasks()` zaten
  çalışan loop'ta `run_until_complete` çağırıp `RuntimeError: This event loop is already
  running` atıyor. Bunun yerine `task = await client.start(); await task` + toplu
  `disconnect()` (gather + 10 sn timeout).
- **Kota:** her hesap bir websocket bağlantısı açar (anonim imza, ~100 bağlantı/gün).
  Pompa 30 dakikada bir koşar; 3 hesap ≈ 144/gün. Kota dolarsa toplayıcı önceki listeyi
  `stale: true` ile korur, panel boşalmaz.
- **Durum (17 Kas 2026, canlı):** `data/watchlist.txt` = @raganuburvis, @creatinetwins666,
  @beinsports. İlk gerçek turda `beinsports` odasında hediye akışı yakalandı (Rose ×2) ve
  panel `demo:false` ile yayınlandı.



## 2b) Veri pompası — GitHub cron'u tetiklenmiyorsa (bu depoda öyle)

Bu depoda GitHub'ın zamanlanmış işleri hiç çalışmadı: `event=schedule → total_count: 0`
(4 elle tetikleme başarılı, planlı hiç koşu yok — bilinen bir GitHub sorunu). Aynı işi kendi
bilgisayarın yapar:

```bash
python tools/pump.py                 # topla → değiştiyse commit → push → Pages otomatik yayınlar
python tools/pump.py --dry-run        # sadece topla
```

Windows'ta 10 dakikada bir otomatik (zaten kurulu, görev adı `SandikRadarPump`):

```bat
schtasks /Create /TN SandikRadarPump /SC MINUTE /MO 10 /F ^
  /TR "C:\...\sandikradar-web\tools\pump.bat"
schtasks /Run    /TN SandikRadarPump     :: hemen bir tur
schtasks /Delete /TN SandikRadarPump /F  :: kapat
```

Doğrulanan akış: görev → `collect.py` → commit → push → `deploy-pages` (17–21 sn) →
Pages'teki `data/rooms.json` tazelenir. Push'lar kullanıcı hesabıyla yapıldığı için
`deploy-pages` kendiliğinden tetiklenir (bot push'unda tetiklenmez).

## 3) Yerel çalıştırma (pip yok, FastAPI yok)

En kısa yol: kök dizindeki **`BASLAT.bat`** (Windows) veya `./local-server/baslat.sh`.

```bash
python local-server/bridge.py          # → http://127.0.0.1:8800
```

Windows'ta `local-server/baslat.bat` çift tıkla. Panel aynı adresten açılır ve `local` moda
otomatik geçer (paneli **her zaman köprünün kendi adresinden** aç: `http://127.0.0.1:8800`).

> **Tarayıcı notu:** GitHub Pages (HTTPS) sayfasından `http://127.0.0.1:8800`'e istek atmak
> Chrome'un "yerel ağ erişimi" iznine bağlıdır. İzin penceresi çıkarsa onayla; çıkmıyorsa
> Ayarlar → Veri kaynağı → **Aç** düğmesi aynı paneli köprü adresinde açar (izinsiz, tam yetkili).

Bu modda ek olarak şunlar çalışır:

- **Gerçek canlı kontrolü**: `@hesap`, `tiktok.com/@hesap/live`, `room_id` veya `snssdk1233://`
  linki → TikTok'un imzasız uçlarına sorulur (`/api/live/check`). Doğrulandı: canlı yayın için
  başlık + izleyici sayısı döner.
- **SSE akışı** (`/api/stream`) → yeni oda olayı gelince panel anında tazelenir.
- **Sunucu tarafı Telegram uyarıları** (`data/alerts.json`, yeniden başlatmada korunur).

Mod seçimi:

```bash
DATA_PROVIDER=sim  python local-server/bridge.py   # canlı DEMO üretimi (varsayılan)
DATA_PROVIDER=file python local-server/bridge.py   # docs/data/rooms.json'u servis eder
python collector/collect.py --provider euler       # gerçek veriyi dosyaya yaz (TikTokLive gerekir)
BRIDGE_PORT=9000 BRIDGE_REFRESH=10 python local-server/bridge.py
```

## Özellikler (hepsi kilitli değil)

- Sekmeler: Sandık · Çanta · Oran ≥ 2 · Oran ≥ 4 · Çanta Lv 0–1 · Askıda sandık · Kısmet (≥7) · Altın sandık
- Kart: yayıncı, başlık, tür/seviye, jeton, oran, kontenjan, katılan, izleyici, renkli geri sayım
- Filtre: tür, alt tür/seviye, jeton aralığı, oran aralığı, kalan süre (+ hızlı çipler),
  izleyici < kontenjan, açılıştan 60 sn sonra gizle, vurgu eşiği
- Sıralama: açılış / jeton / oran / izleyici / kalan süre (azalan–artan)
- Mini pencere: Document Picture-in-Picture (destekliyorsa gerçek "her zaman üstte") + sürüklenebilir panel
- Uyarılar: ses, tarayıcı bildirimi, Telegram
- Ayarlar: TR/EN/VI, koyu/açık/sistem tema, yazı boyutu, geri sayım renk eşikleri, veri kaynağı
- PWA: ana ekrana ekle, çevrimdışı kabuk önbelleği, otomatik yenileme, bağlantı hatasında yeniden deneme

## API sözleşmesi (yerel köprü)

| Yol | Açıklama |
|---|---|
| `GET /api/health` | `{ok, provider, demo, rooms, updated_at, server_time}` |
| `GET /api/config` | sekmeler, diller, yenileme aralığı |
| `GET /api/rooms` | filtreli liste + `tab_counts` (panel bu ucu kullanır) |
| `GET /api/stats` | sağlayıcı sayaçları |
| `GET /api/live/check?q=` | gerçek canlı doğrulama |
| `GET/POST /api/alerts`, `POST /api/alerts/test` | Telegram uyarı yapılandırması/test |
| `GET /api/stream` | SSE: `snapshot`, `new_room` |

`/api/rooms` parametreleri: `kind, variants, levels, min_coins, max_coins, min_ratio, max_ratio,
min_time, max_time, max_viewers, viewers_lt_slots, hide_late, sort, desc, status`.

Statik modda panel aynı filtreleri tarayıcıda uygular (`docs/app.js` içindeki `applyFilters`),
bu yüzden GitHub Pages'te sunucu gerekmez.

## Ne çalışır, ne çalışmaz (dürüst tablo)

Her satır bu depoda **gerçekten koşularak** doğrulandı (2026-11-17). "Doğrulama" kolonu neyin
ölçüldüğünü söyler; ölçülmeyen şey ✅ diye işaretlenmedi.

| Yetenek | GitHub Pages (statik) | Yerel köprü | Doğrulama / sınır |
|---|---|---|---|
| Liste, sekmeler, filtre, sıralama, geri sayım | ✅ | ✅ | 220 oda, 8 sekme sayacı, 5 sıralama, oran≥4 → 83 kart; konsol hatası 0 |
| Mini pencere (+ PiP), tema/dil, yazı boyutu | ✅ | ✅ | PiP açıldı, 12 satır; TR/EN/VI etiketler değişti |
| Ses uyarısı | ✅ (ilk dokunuştan sonra) | ✅ | `AudioContext` ilk tıklamada açılıyor; tarayıcı otomatik oynatmayı engellediği için ilk kullanıcı hareketi şart |
| Tarayıcı bildirimi | ✅ (izin verilirse) | ✅ | İzin verilmemişken sessizce atlıyor, hata fırlatmıyor |
| PWA / çevrimdışı | ✅ (son liste, "⚠ veri eski") | ✅ | Ağ kapatıldı: kabuk + 125 kart önbellekten geldi, yaş etiketi "veri eski" |
| Veri tazeliği | pompa turu (30 dk) ya da **Run workflow** | 20 sn (canlı) | Görev 10:00 ve 10:09'da koştu, `Last Result: 0`, her tur commit + deploy |
| Gerçek canlı link kontrolü | ❌ | ✅ | Statik sayfadan TikTok uçları **CORS başlığı dönmediği için** "Failed to fetch"; köprüde `@beinsports → YAYINDA, 5.8K izleyici, id 7706853078218984210` |
| Telegram uyarısı | ✅ (token cihazda saklanır) | ✅ (sunucu tarafı) | Tarayıcıdan `sendMessage` yalnızca **form-urlencoded** gövdeyle geçiyor (JSON gövde preflight'a takılıyor, "Failed to fetch"); sahte token → `✗ Unauthorized` yanıtı okundu, yani taşıma çalışıyor. Gerçek gönderim geçerli token ister |
| Gerçek sandık verisi | `EULER_API_KEY` secret varsa ✅ | `collect.py --provider euler` | Yol doğrulandı: feed çağrısı gerçek `401 {"message":"The provided API Key is invalid."}` döndürüyor ve işçi önceki listeyi `stale: true` ile koruyor. **Business planlı anahtarla uçtan uca denenmedi** (elimde anahtar yok) |
| SSE ile anlık olay akışı | ❌ (yoklama) | ✅ | `/api/stream` `new_room` olayı gönderdi, panel tazelendi |
| HTTPS sayfadan köprüye erişim | ⚠ tarayıcı iznine bağlı | — | Chrome 145 `local-network-access` izni otomatik `denied`; Ayarlar → **Aç** ile panel köprü adresinde açılıyor |

**DEMO rozeti** görünüyorsa odalar gerçek değildir. `data/rooms.json` içindeki
`"demo": true` alanı bunu belirler; sahte `room_id` üretilmez, böylece "KATIL" düğmesi
asla var olmayan bir odaya gitmez.

## Sınırlar

- GitHub zamanlanmış işler yoğun saatlerde gecikebilir (5 dk yerine 10–20 dk). Panel veri
  yaşını üst çubukta gösterir, 30 dakikayı geçince "⚠ veri eski" yazar.
- TikTok kullanım şartları üçüncü taraf kazımayı sınırlar; bu bir **keşif** aracıdır: odaya
  girmez, ödül toplamaz, otomatik katılmaz.
- GitHub'ın zamanlayıcısı "en iyi çaba" ile çalışır: yeni bir depoda ilk `schedule` tetiklemesi 1 saate kadar
  gecikebilir, yoğun saatlerde turlar seyrek atlanır. Veri beklemek istemiyorsan Actions →
  `collect-data` → **Run workflow**.
- Depoya 60 gün hiç push gelmezse GitHub zamanlanmış işleri duraklatır (Actions → `collect-data` → ⋯ → Enable).
- Actions IP'leri TikTok tarafından sınırlandırılabilir; o durumda `collect.py` önceki listeyi
  korur ve `data/meta.json` içindeki `error` alanında nedeni yazar (iş kırmızı yanmaz).
- TikTok, LiveMira veya EulerStream ile bağlantılı değildir.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Sayfa boş, "veri dosyası bulunamadı" | Actions → `collect-data` → **Run workflow** |
| DEMO rozeti gitmiyor | `EULER_API_KEY` secret'ı yok/geçersiz; Actions logunda `401` mesajına bak (Business plan gerekir) |
| Panelde "veri eski" | İşçi son turda veri üretemedi; `data/meta.json` → `error` |
| Yerel köprü 404 | `python local-server/bridge.py` çalışıyor mu, `http://127.0.0.1:8800/api/health` |
| "Yerel köprüye ulaşılamadı" (Pages sayfası) | Chrome yerel ağ iznini reddetmiş olabilir — Ayarlar → Veri kaynağı → **Aç** ile `http://127.0.0.1:8800`'de aç |
| Telegram testi ✗ | token/chat_id hatalı; grup için `-100…` biçimi; bot gruba ekli mi |
| GitHub Pages 404 | Settings → Pages → Source = **GitHub Actions**, `deploy-pages` işi yeşil mi |
