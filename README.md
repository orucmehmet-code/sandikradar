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

## 3) Yerel çalıştırma (pip yok, FastAPI yok)

```bash
python local-server/bridge.py          # → http://127.0.0.1:8800
```

Windows'ta `local-server/baslat.bat` çift tıkla. Panel aynı adresten açılır ve `local` moda
otomatik geçer. Bu modda ek olarak şunlar çalışır:

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

| Yetenek | GitHub Pages (statik) | Yerel köprü |
|---|---|---|
| Liste, sekmeler, filtre, sıralama, geri sayım | ✅ | ✅ |
| Mini pencere, ses, bildirim, tema/dil, PWA | ✅ | ✅ |
| Veri tazeliği | Actions turu (≈5 dk, pratikte 5–15 dk) | 20 sn (canlı) |
| Gerçek canlı link kontrolü | ❌ (tarayıcıda CORS) | ✅ |
| Telegram uyarısı | ✅ (tarayıcıdan doğrudan; token cihazda saklanır) | ✅ (sunucu tarafı) |
| Gerçek sandık verisi | `EULER_API_KEY` secret varsa ✅, yoksa DEMO | `collect.py --provider euler` sonrası ✅ |
| SSE ile anlık olay akışı | ❌ (yoklama) | ✅ |

**DEMO rozeti** görünüyorsa odalar gerçek değildir. `data/rooms.json` içindeki
`"demo": true` alanı bunu belirler; sahte `room_id` üretilmez, böylece "KATIL" düğmesi
asla var olmayan bir odaya gitmez.

## Sınırlar

- GitHub zamanlanmış işler yoğun saatlerde gecikebilir (5 dk yerine 10–20 dk). Panel veri
  yaşını üst çubukta gösterir, 30 dakikayı geçince "⚠ veri eski" yazar.
- TikTok kullanım şartları üçüncü taraf kazımayı sınırlar; bu bir **keşif** aracıdır: odaya
  girmez, ödül toplamaz, otomatik katılmaz.
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
| Telegram testi ✗ | token/chat_id hatalı; grup için `-100…` biçimi; bot gruba ekli mi |
| GitHub Pages 404 | Settings → Pages → Source = **GitHub Actions**, `deploy-pages` işi yeşil mi |
