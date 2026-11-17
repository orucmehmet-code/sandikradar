/* SandıkRadar — tek dosyalık panel (GitHub Pages + yerel köprü).
   Derleme yok, bağımlılık yok. Veri: data/rooms.json (Actions işçisi üretir)
   ya da yerel köprü http://127.0.0.1:8800/api/rooms. */

const FALLBACK_TABS = [
  { id: "chest", label: { tr: "Sandık", vi: "Rương", en: "Chest" }, filter: { kind: "chest" } },
  { id: "bag", label: { tr: "Çanta", vi: "Túi", en: "Bag" }, filter: { kind: "bag" } },
  { id: "ratio2", label: { tr: "Oran ≥ 2", vi: "Ratio ≥ 2", en: "Ratio ≥ 2" }, filter: { min_ratio: 2 } },
  { id: "ratio4", label: { tr: "Oran ≥ 4", vi: "Ratio ≥ 4", en: "Ratio ≥ 4" }, filter: { min_ratio: 4 } },
  { id: "level01", label: { tr: "Çanta Lv 0–1", vi: "Túi level 0–1", en: "Bag Lv 0–1" }, filter: { kind: "bag", variants: ["l0", "l1"] } },
  { id: "hanging", label: { tr: "Askıda sandık", vi: "Rương treo", en: "Hanging chest" }, filter: { kind: "chest", variants: ["hanging"] } },
  { id: "kismet", label: { tr: "Kısmet (oran ≥ 7)", vi: "Nhân phẩm (ratio ≥ 7)", en: "Lucky (ratio ≥ 7)" }, filter: { min_ratio: 7 } },
  { id: "gold", label: { tr: "Altın sandık", vi: "Rương vàng", en: "Gold chest" }, filter: { kind: "chest", variants: ["gold"] } },
];

const I18N = {
  tr: {
    chest: "Sandık", bag: "Çanta", coins: "jeton", ratio: "oran", slots: "kontenjan",
    joined: "katılan", viewers: "izleyici", openLive: "CANLI'yı Aç", copyComment: "Yorumu kopyala",
    copied: "Kopyalandı", countFound: n => `${n} uygun LIVE`, connecting: "yükleniyor…",
    updated: s => `${s} sn önce güncellendi`, noRooms: "Uygun LIVE aranıyor…",
    now: "şimdi", late: "geçti", inSec: "sn", inMin: "dk", soon: "açılıyor",
    newChest: "Yeni sandık!", newBag: "Yeni çanta!", stale: "veri eski",
    gold: "Altın", hanging: "Askıda", normal: "Sandık", bagLv: lv => `Çanta Lv ${lv}`,
    offline: "Bağlantı kesildi, yeniden deneniyor…", loading: "veri yükleniyor…",
    noData: "Veri dosyası bulunamadı — Actions işçisi henüz çalışmamış olabilir.",
  },
  en: {
    chest: "Chest", bag: "Bag", coins: "coins", ratio: "ratio", slots: "slots",
    joined: "joined", viewers: "viewers", openLive: "Open LIVE", copyComment: "Copy comment",
    copied: "Copied", countFound: n => `${n} matching LIVE`, connecting: "loading…",
    updated: s => `updated ${s}s ago`, noRooms: "Looking for matching LIVE…",
    now: "now", late: "late", inSec: "s", inMin: "m", soon: "opening",
    newChest: "New chest!", newBag: "New bag!", stale: "stale data",
    gold: "Gold", hanging: "Hanging", normal: "Chest", bagLv: lv => `Bag Lv ${lv}`,
    offline: "Disconnected, retrying…", loading: "loading data…",
    noData: "Data file not found — the Actions worker may not have run yet.",
  },
  vi: {
    chest: "Rương", bag: "Túi", coins: "xu", ratio: "ratio", slots: "suất",
    joined: "đã tham gia", viewers: "người xem", openLive: "Mở LIVE", copyComment: "Chép bình luận",
    copied: "Đã chép", countFound: n => `${n} LIVE phù hợp`, connecting: "đang tải…",
    updated: s => `cập nhật ${s} giây trước`, noRooms: "Đang tìm LIVE phù hợp…",
    now: "bây giờ", late: "trễ", inSec: "giây", inMin: "phút", soon: "sắp mở",
    newChest: "Rương mới!", newBag: "Túi mới!", stale: "dữ liệu cũ",
    gold: "Vàng", hanging: "Treo", normal: "Rương", bagLv: lv => `Túi level ${lv}`,
    offline: "Mất kết nối, đang thử lại…", loading: "đang tải dữ liệu…",
    noData: "Không tìm thấy tệp dữ liệu — worker Actions chưa chạy.",
  },
};

const DEFAULTS = {
  lang: "tr", theme: "dark", scale: 1, sound: true, notify: false, autoPip: false,
  sort: "opens_at",
  thresholds: { red: 30, amber: 120, green: 600 },
  colors: { red: "#ff3b5c", amber: "#ffa62b", green: "#2ee6a8" },
  filters: {
    kind: "all", variants: [], min_coins: "", max_coins: "", min_ratio: "", max_ratio: "",
    min_time: "", max_time: "", viewers_lt_slots: false, hide_late: "", highlight: "",
  },
  tab: "chest",
  source: "static",
  bridge: "http://127.0.0.1:8800",
  tg: { enabled: false, bot_token: "", chat_id: "", min_ratio: 3, min_coins: 100000 },
};

const state = {
  data: null, all: [], rooms: [], tabs: FALLBACK_TABS,
  prefs: structuredClone(DEFAULTS), lastUpdate: 0, playing: true,
  seen: new Set(), firstLoad: true, offline: false, tabCounts: {},
  pipWin: null, bridgeOk: false, alerted: new Map(),
};

/* ------------------------------------------------------------------ yardımcı */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const t = key => (I18N[state.prefs.lang] || I18N.tr)[key] ?? key;

function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem("sandikradar.prefs") || "{}");
    state.prefs = {
      ...state.prefs, ...saved,
      filters: { ...DEFAULTS.filters, ...(saved.filters || {}) },
      thresholds: { ...DEFAULTS.thresholds, ...(saved.thresholds || {}) },
      colors: { ...DEFAULTS.colors, ...(saved.colors || {}) },
      tg: { ...DEFAULTS.tg, ...(saved.tg || {}) },
    };
  } catch { /* bozuk kayıt: varsayılanla devam */ }
}
function savePrefs() {
  try { localStorage.setItem("sandikradar.prefs", JSON.stringify(state.prefs)); } catch { }
}

function fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1).replace(".", ",") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1).replace(".", ",") + "K";
  return String(n);
}

function fmtClock(sec) {
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return `${m}:${String(r).padStart(2, "0")}`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function variantLabel(room) {
  if (room.kind === "bag") {
    const lv = (room.variant || "l0").replace("l", "");
    return t("bagLv")(lv);
  }
  if (room.variant === "gold") return t("gold");
  if (room.variant === "hanging") return t("hanging");
  return t("normal");
}

/* --------------------------------------------------------------------- ses */
let audioCtx = null;
function beep(freq = 880, dur = 0.12, gain = 0.06) {
  if (!state.prefs.sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.type = "sine"; o.frequency.value = freq; g.gain.value = gain;
    o.connect(g).connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + dur);
  } catch { /* ses desteklenmiyor */ }
}

function notify(title, body, tag) {
  if (!state.prefs.notify || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try { new Notification(title, { body, tag, icon: "icon.svg" }); } catch { }
}

/* ---------------------------------------------------- filtre motoru (JS) */
const num = v => (v === "" || v === null || v === undefined ? null : (Number.isFinite(+v) ? +v : null));
const list = v => (Array.isArray(v) ? v : (v ? String(v).split(",") : [])).map(s => String(s).trim()).filter(Boolean);

function applyFilters(rooms, params = {}) {
  const kind = String(params.kind || "all").toLowerCase();
  const variants = list(params.variants);
  const levels = list(params.levels);
  const status = String(params.status || "all").toLowerCase();
  const minCoins = num(params.min_coins), maxCoins = num(params.max_coins);
  const minRatio = num(params.min_ratio), maxRatio = num(params.max_ratio);
  const minTime = num(params.min_time), maxTime = num(params.max_time);
  const maxViewers = num(params.max_viewers);
  const onlyViewersLtSlots = String(params.viewers_lt_slots || "").toLowerCase() === "true" || params.viewers_lt_slots === true;
  const hideLate = num(params.hide_late);

  const out = rooms.filter(room => {
    if (kind !== "all" && room.kind !== kind) return false;
    if (variants.length && !variants.includes(room.variant)) return false;
    if (levels.length && !levels.map(v => "l" + String(v).replace(/^l/i, "")).includes(room.variant)) return false;
    if (status === "upcoming" && room.status !== "upcoming") return false;
    if (status === "open" && room.status !== "open") return false;
    if (minCoins !== null && (room.coins || 0) < minCoins) return false;
    if (maxCoins !== null && (room.coins || 0) > maxCoins) return false;
    if (minRatio !== null && (room.ratio || 0) < minRatio) return false;
    if (maxRatio !== null && (room.ratio || 0) > maxRatio) return false;
    if (minTime !== null && (room.seconds_left || 0) < minTime) return false;
    if (maxTime !== null && (room.seconds_left || 0) > maxTime) return false;
    if (maxViewers !== null && (room.viewers || 0) > maxViewers) return false;
    if (onlyViewersLtSlots && !room.viewers_lt_slots) return false;
    if (hideLate !== null && (room.delta || 0) < -hideLate) return false;
    return true;
  });

  const sort = String(params.sort || "opens_at").toLowerCase();
  const reverse = ["1", "true", "on", "yes"].includes(String(params.desc || "").toLowerCase()) || params.desc === true;
  const keys = {
    opens_at: r => r.opens_at || 0, coins: r => r.coins || 0, ratio: r => r.ratio || 0,
    viewers: r => r.viewers || 0, left: r => r.seconds_left || 0,
  };
  out.sort((a, b) => (keys[sort] || keys.opens_at)(a) - (keys[sort] || keys.opens_at)(b));
  if (reverse) out.reverse();
  return out;
}

function baseParams() {
  const f = state.prefs.filters;
  const p = {};
  for (const [k, v] of Object.entries(f)) {
    if (v === "" || v === null || v === undefined || v === false) continue;
    if (Array.isArray(v) && !v.length) continue;
    if (k === "highlight") continue;
    p[k] = Array.isArray(v) ? v.join(",") : v;
  }
  p.sort = state.prefs.sort;
  p.desc = state.prefs.sort === "opens_at" ? "0" : "1";
  return p;
}

function tabParams(tabId = state.prefs.tab) {
  const tab = state.tabs.find(x => x.id === tabId);
  const p = { ...baseParams() };
  if (tab?.filter) {
    Object.assign(p, tab.filter);
    if (p.kind && p.kind !== "all" && tab.filter.kind && p.kind !== tab.filter.kind) {
      /* kullanıcı tür seçtiyse o öncelikli */
    }
  }
  return p;
}

function computeTabCounts(allRooms, params) {
  const counts = {};
  for (const tab of state.tabs) {
    counts[tab.id] = applyFilters(allRooms, { ...params, ...(tab.filter || {}) }).length;
  }
  return counts;
}

/* -------------------------------------------------------------------- API */
function bridgeBase() {
  return (state.prefs.bridge || "http://127.0.0.1:8800").replace(/\/+$/, "");
}

function refreshRoomTimes(rooms, now = Date.now()) {
  return rooms.map(room => {
    const opensAt = Number(room.opens_at) || 0;
    const delta = opensAt - now;
    return {
      ...room,
      seconds_left: Math.round(Math.max(0, delta) / 1000),
      delta: Math.round(delta / 1000),
      status: delta <= 0 ? "open" : "upcoming",
      viewers_lt_slots: (Number(room.viewers) || 0) < Math.max(1, Number(room.slots) || 1),
    };
  });
}

async function fetchStatic() {
  const res = await fetch(`data/rooms.json?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(res.status === 404 ? t("noData") : `HTTP ${res.status}`);
  const data = await res.json();
  state.data = data;
  state.activeSource = "static";
  state.tabs = Array.isArray(data.tabs) && data.tabs.length ? data.tabs : FALLBACK_TABS;
  state.all = refreshRoomTimes(Array.isArray(data.rooms) ? data.rooms : []);
  state.lastUpdate = Number(data.generated_at) || Date.now();
  const params = tabParams();
  state.rooms = applyFilters(state.all, params);
  state.tabCounts = computeTabCounts(state.all, baseParams());
}

async function fetchLocal() {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(tabParams())) {
    if (v === "" || v === null || v === undefined || v === false) continue;
    qs.set(k, String(v));
  }
  const res = await fetch(`${bridgeBase()}/api/rooms?${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`köprü HTTP ${res.status}`);
  const data = await res.json();
  state.data = data;
  state.activeSource = "local";
  state.all = [];
  state.rooms = refreshRoomTimes(Array.isArray(data.rooms) ? data.rooms : []);
  state.tabCounts = data.tab_counts || {};
  state.lastUpdate = Number(data.updated_at) || Date.now();
  if (Array.isArray(data.tabs) && data.tabs.length) state.tabs = data.tabs;
}

async function fetchData() {
  try {
    if (state.prefs.source === "local") await fetchLocal();
    else await fetchStatic();
    state.offline = false;
    $("#offline").classList.add("hidden");
    setStatus("ok");
    render();
    const fresh = state.rooms.filter(r => !state.seen.has(r.id));
    for (const room of fresh) state.seen.add(room.id);
    if (!state.firstLoad && fresh.length) {
      const top = fresh.slice().sort((a, b) => (b.ratio || 0) - (a.ratio || 0))[0];
      if (state.playing) beep(room2Freq(top), 0.14);
      notify(top.kind === "chest" ? t("newChest") : t("newBag"),
        `@${top.user} · ${fmtNum(top.coins)} ${t("coins")} · ${t("ratio")} ${top.ratio}`, top.id);
      maybeTelegram(top);
    }
    state.firstLoad = false;
  } catch (err) {
    state.offline = true;
    setStatus("err", err.message && err.message.length < 60 ? err.message : undefined);
    $("#offline").classList.remove("hidden");
    $("#offline").textContent = state.prefs.source === "local"
      ? "Yerel köprüye ulaşılamadı. Tarayıcı yerel ağ izni istediyse onayla; ya da paneli " + bridgeBase() + " adresinden aç."
      : t("offline");
  }
}

function room2Freq(room) {
  if (!room) return 880;
  return room.kind === "chest" ? 760 + Math.min(600, (room.ratio || 0) * 40) : 620;
}

function syncDemoBadge() {
  const badge = $("#demoBadge");
  if (badge) badge.classList.toggle("hidden", !(state.data && state.data.demo));
}

function setStatus(kind, text) {
  syncDemoBadge();
  const el = $("#status");
  if (!el) return;
  el.classList.remove("ok", "err");
  if (kind) el.classList.add(kind);
  const age = state.lastUpdate ? Math.round((Date.now() - state.lastUpdate) / 1000) : null;
  const prov = state.data?.provider || (state.prefs.source === "local" ? "köprü" : "");
  const parts = [];
  if (prov) parts.push(prov);
  if (age !== null) parts.push(t("updated")(age));
  if (age !== null && age > 1800) parts.push("⚠ " + t("stale"));
  if (state.data?.error) parts.push("⚠");
  $("#statusText").textContent = text || (kind === "ok" ? parts.join(" · ") : t("loading"));
  $("#statusText").title = state.data?.error || state.data?.notice || "";
}

/* ------------------------------------------------------------------ render */
function timerColor(sec) {
  const th = state.prefs.thresholds;
  if (sec <= th.red) return state.prefs.colors.red;
  if (sec <= th.amber) return state.prefs.colors.amber;
  if (sec <= th.green) return state.prefs.colors.green;
  return "";
}

function highlightThreshold() {
  const v = parseFloat(state.prefs.filters.highlight);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

function render() {
  const listEl = $("#list");
  const tpl = $("#roomTpl");
  const highlight = highlightThreshold();
  listEl.innerHTML = "";

  if (!state.rooms.length) {
    $("#empty").classList.remove("hidden");
    const prov = state.data?.provider;
    $("#emptyText").textContent = state.data?.error
      ? `⚠ ${state.data.error}`
      : prov === "sim"
        ? "DEMO veri: arayüzün tamamı çalışıyor, odalar gerçek değil.\nGerçek sandık için Actions'a EULER_API_KEY ekle (README)."
        : prov === "euler"
          ? "Henüz sandık yakalanmadı — işçi bir sonraki turda dolduracak."
          : t("noRooms");
  } else {
    $("#empty").classList.add("hidden");
  }

  const frag = document.createDocumentFragment();
  for (const room of state.rooms) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = room.id;
    node._room = room;
    node.classList.toggle("gold", room.variant === "gold");
    node.classList.toggle("hanging", room.variant === "hanging");
    node.classList.toggle("hot", highlight > 0 && (room.coins || 0) >= highlight);

    const img = $(".avatar", node);
    if (room.avatar) { img.src = room.avatar; img.onerror = () => { img.style.visibility = "hidden"; }; }
    else img.style.visibility = "hidden";
    $(".nick", node).textContent = room.nickname || room.user || "—";
    $(".handle", node).textContent = "@" + (room.user || "—");
    const badge = $(".kind-badge", node);
    badge.textContent = room.kind === "chest" ? t("chest") : t("bag");
    badge.classList.toggle("bag", room.kind === "bag");
    $(".viewers", node).textContent = `${fmtNum(room.viewers)} ${t("viewers")}`;
    $(".title", node).textContent = room.title || variantLabel(room);
    $(".coins", node).textContent = fmtNum(room.coins);
    $(".ratio", node).textContent = (room.ratio ?? 0).toFixed(1);
    $(".slots", node).textContent = fmtNum(room.slots);
    const joinedM = $(".joined-metric", node);
    const metrics = $(".metrics", node);
    if (room.kind === "bag") {
      joinedM.classList.remove("hidden");
      metrics.classList.remove("three");
      $(".joined", node).textContent = fmtNum(room.joined || 0);
    } else {
      joinedM.classList.add("hidden");
      metrics.classList.add("three");
    }
    $(".open-btn", node).textContent = t("openLive");
    $(".copy-btn", node).textContent = t("copyComment");
    updateTimer(node, room);
    frag.appendChild(node);
  }
  listEl.appendChild(frag);

  $("#countLabel").textContent = t("countFound")(state.rooms.length);
  renderTabs();
  renderMini();
  setStatus(state.offline ? "err" : "ok");
  updateDataInfo();
}

function updateTimer(node, room) {
  const left = Math.round(((Number(room.opens_at) || 0) - Date.now()) / 1000);
  const val = $(".timer-val", node);
  const lbl = $(".timer-lbl", node);
  const color = timerColor(Math.max(0, left));
  if (left > 0) {
    val.textContent = fmtClock(left);
    lbl.textContent = left <= 30 ? t("soon") : "";
  } else {
    val.textContent = "●";
    lbl.textContent = `${Math.abs(left)}s ${t("late")}`;
  }
  val.style.color = left <= 0 ? state.prefs.colors.red : (color || "");
  node.classList.toggle("soon", left > 0 && left <= 30);
  node.classList.toggle("open-now", left <= 0);
}

function tickTimers() {
  for (const node of $$("#list .card")) {
    if (node._room) updateTimer(node, node._room);
  }
  for (const row of $$("#miniList .mini-row")) {
    if (row._room) {
      const left = Math.round(((Number(row._room.opens_at) || 0) - Date.now()) / 1000);
      const el = $(".t", row);
      if (el) {
        el.textContent = left > 0 ? fmtClock(left) : "●";
        el.style.color = left <= 0 ? state.prefs.colors.red : (timerColor(left) || "");
      }
    }
  }
  if (state.lastUpdate && !state.offline) {
    const age = Math.round((Date.now() - state.lastUpdate) / 1000);
    const prov = state.data?.provider || (state.prefs.source === "local" ? "köprü" : "");
    const bits = [prov, t("updated")(age)].filter(Boolean);
    if (age > 1800) bits.push("⚠ " + t("stale"));
    $("#statusText").textContent = bits.join(" · ");
  }
}

/* ------------------------------------------------------------------ sekmeler */
function renderTabs() {
  const wrap = $("#tabs");
  wrap.innerHTML = "";
  const counts = state.tabCounts || {};
  for (const tab of state.tabs) {
    const btn = document.createElement("button");
    btn.className = "tab" + (state.prefs.tab === tab.id ? " active" : "");
    const label = (tab.label && (tab.label[state.prefs.lang] || tab.label.tr)) || tab.id;
    btn.innerHTML = `<span></span><span class="n"></span>`;
    btn.firstChild.textContent = label;
    btn.lastChild.textContent = counts[tab.id] ?? 0;
    btn.onclick = () => {
      state.prefs.tab = tab.id;
      savePrefs(); renderTabs(); fetchData();
    };
    wrap.appendChild(btn);
  }
}

/* -------------------------------------------------------------- mini pencere */
function renderMini() {
  const mini = $("#mini");
  if (mini.classList.contains("hidden")) return;
  const listEl = $("#miniList");
  listEl.innerHTML = "";
  $("#miniCount").textContent = `${state.rooms.length}`;
  for (const room of state.rooms.slice(0, 12)) {
    const row = document.createElement("div");
    row.className = "mini-row";
    row._room = room;
    const left = Math.round(((Number(room.opens_at) || 0) - Date.now()) / 1000);
    row.innerHTML = `<span>${room.kind === "chest" ? "🎁" : "👜"}</span>
      <span class="u"></span><span class="c"></span><span class="c"></span>
      <span class="t">${left > 0 ? fmtClock(left) : "●"}</span>`;
    row.querySelector(".u").textContent = "@" + (room.user || "—");
    const cells = row.querySelectorAll(".c");
    cells[0].textContent = fmtNum(room.coins);
    cells[1].textContent = "×" + (room.ratio ?? 0).toFixed(1);
    row.onclick = () => openRoom(room);
    listEl.appendChild(row);
  }
}

async function toggleMini(force) {
  const mini = $("#mini");
  const show = force ?? mini.classList.contains("hidden");
  mini.classList.toggle("hidden", !show);
  if (show && "documentPictureInPicture" in window) {
    try {
      const pip = await window.documentPictureInPicture.requestWindow({ width: 340, height: 460 });
      pip.document.head.innerHTML = "";
      const style = pip.document.createElement("link");
      style.rel = "stylesheet"; style.href = "styles.css";
      pip.document.head.appendChild(style);
      pip.document.documentElement.dataset.theme = document.documentElement.dataset.theme;
      pip.document.body.style.margin = "0";
      const box = pip.document.createElement("div");
      box.className = "mini";
      box.style.position = "static";
      box.style.width = "100%";
      box.style.maxHeight = "100vh";
      box.innerHTML = `<header class="mini-head"><strong>SandıkRadar</strong><span class="mini-count" id="mp"></span></header><div class="mini-list" id="ml"></div>`;
      pip.document.body.appendChild(box);
      state.pipWin = pip;
      renderPipList();
      mini.classList.add("hidden");
      return;
    } catch { /* PiP reddedildi: sayfa içi mini pencere yeter */ }
  }
  renderMini();
}

function renderPipList() {
  const pip = state.pipWin;
  if (!pip || pip.closed) return;
  const ml = pip.document.getElementById("ml");
  const mp = pip.document.getElementById("mp");
  if (!ml) return;
  mp.textContent = `${state.rooms.length}`;
  ml.innerHTML = "";
  for (const room of state.rooms.slice(0, 12)) {
    const left = Math.round(((Number(room.opens_at) || 0) - Date.now()) / 1000);
    const row = pip.document.createElement("div");
    row.className = "mini-row";
    row.innerHTML = `<span>${room.kind === "chest" ? "🎁" : "👜"}</span><span class="u"></span>
      <span class="c"></span><span class="c"></span><span class="t">${left > 0 ? fmtClock(left) : "●"}</span>`;
    row.querySelector(".u").textContent = "@" + (room.user || "—");
    const cells = row.querySelectorAll(".c");
    cells[0].textContent = fmtNum(room.coins);
    cells[1].textContent = "×" + (room.ratio ?? 0).toFixed(1);
    row.onclick = () => openRoom(room);
    ml.appendChild(row);
  }
}

/* ------------------------------------------------------------------ eylemler */
const IS_MOBILE = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

function openRoom(room) {
  const url = `https://www.tiktok.com/@${room.user}/live`;
  const deep = IS_MOBILE && room.room_id ? `snssdk1233://live?room_id=${room.room_id}` : null;
  if (!deep) {
    window.open(url, "_blank", "noopener");
  } else {
    const a = document.createElement("a");
    a.href = deep; a.rel = "noopener"; a.target = "_blank";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => window.open(url, "_blank", "noopener"), 700);
  }
  if (state.pipWin && !state.pipWin.closed) state.pipWin.close();
}

function copyComment(room) {
  const text = `${room.kind === "chest" ? "🎁" : "👜"} ${room.title || ""}`.trim();
  navigator.clipboard?.writeText(text).then(() => {
    beep(1200, 0.06, 0.03); flash(t("copied"));
  }).catch(() => flash("✗"));
}

function flash(msg) {
  const el = document.createElement("div");
  el.textContent = msg;
  Object.assign(el.style, {
    position: "fixed", left: "50%", bottom: "80px", transform: "translateX(-50%)",
    background: "#2ee6a8", color: "#04120c", padding: "8px 14px", borderRadius: "10px",
    fontWeight: "700", fontSize: ".8rem", zIndex: 99,
  });
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 1400);
}

/* -------------------------------------------------- gerçek canlı doğrulama */
async function checkLiveTarget(openAfter) {
  const q = ($("#sLiveInput")?.value || "").trim();
  const out = $("#liveStatus");
  if (!q) { if (out) out.textContent = "link / hesap gir"; return; }
  if (state.prefs.source !== "local") {
    if (out) out.textContent = "Bu kontrol yerel köprü gerektirir — Ayarlar → Veri kaynağı → Yerel köprü.";
    return;
  }
  if (out) out.textContent = "sorgulanıyor…";
  try {
    const res = await fetch(`${bridgeBase()}/api/live/check?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    if (!data.ok) { if (out) out.textContent = "✗ " + (data.error || "hata"); return; }
    if (!data.live) {
      if (out) out.textContent = `○ yayında değil${data.handle ? " (@" + data.handle + ")" : ""} — ${data.url}`;
      return;
    }
    const meta = [data.nickname && "@" + (data.handle || data.nickname),
      data.viewers ? fmtNum(data.viewers) + " izleyici" : "",
      data.room_id ? "id " + data.room_id : ""].filter(Boolean).join(" · ");
    if (out) out.textContent = `● YAYINDA — ${data.title || "(başlık yok)"}\n${meta}`;
    if (openAfter) window.open(data.url, "_blank", "noopener");
  } catch (err) {
    if (out) out.textContent = "✗ " + err.message;
  }
}

/* ------------------------------------------------------------------ telegram */
function tgConfig() {
  const tg = state.prefs.tg;
  return { enabled: !$("#sTgDisabled")?.checked, token: tg.bot_token, chat: tg.chat_id,
           min_ratio: tg.min_ratio, min_coins: tg.min_coins };
}

async function sendTelegram(text) {
  const tg = state.prefs.tg;
  if (!tg.bot_token || !tg.chat_id) return { ok: false, detail: "token/chat yok" };
  if (state.prefs.source === "local") {
    const res = await fetch(`${bridgeBase()}/api/alerts/test`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ bot_token: tg.bot_token, chat_id: tg.chat_id, text }),
    });
    return res.json();
  }
  const res = await fetch(`https://api.telegram.org/bot${tg.bot_token}/sendMessage`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: tg.chat_id, text, parse_mode: "HTML", disable_web_page_preview: true }),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok && data.ok !== false, detail: data.description || (res.ok ? "" : "HTTP " + res.status) };
}

function maybeTelegram(room) {
  const tg = state.prefs.tg;
  if (!tg.enabled || !tg.bot_token || !tg.chat_id) return;
  if ((room.ratio || 0) < (tg.min_ratio || 0) || (room.coins || 0) < (tg.min_coins || 0)) return;
  const last = state.alerted.get(room.id) || 0;
  if (Date.now() - last < 90_000) return;
  state.alerted.set(room.id, Date.now());
  const text = `${room.kind === "chest" ? "🎁 <b>Sandık</b>" : "👜 <b>Çanta</b>"} · ${fmtNum(room.coins)} jeton · oran ${room.ratio}\n` +
    `@${room.user} — ${fmtNum(room.viewers)} izleyici\nhttps://www.tiktok.com/@${room.user}/live`;
  sendTelegram(text).catch(() => { });
}

/* --------------------------------------------------------------------- form */
function openSheet(id) {
  const el = document.getElementById(id);
  el.classList.add("open");
  el.setAttribute("aria-hidden", "false");
}
function closeSheet(id) {
  const el = document.getElementById(id);
  el.classList.remove("open");
  el.setAttribute("aria-hidden", "true");
}

function bindSegmented(sel, current, onPick) {
  for (const btn of $$(sel + " .seg")) {
    btn.classList.toggle("active", btn.dataset.value === String(current));
    btn.onclick = () => {
      $$(sel + " .seg").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      onPick(btn.dataset.value);
    };
  }
}

function hydrateFilterForm() {
  const f = state.prefs.filters;
  bindSegmented("#fKind", f.kind, v => { f.kind = v; });
  for (const chip of $$("#fVariants .chip")) {
    chip.classList.toggle("active", f.variants.includes(chip.dataset.value));
    chip.onclick = () => {
      chip.classList.toggle("active");
      f.variants = $$("#fVariants .chip.active").map(c => c.dataset.value);
    };
  }
  $("#fMinCoins").value = f.min_coins;
  $("#fMaxCoins").value = f.max_coins;
  $("#fMinRatio").value = f.min_ratio;
  $("#fMaxRatio").value = f.max_ratio;
  $("#fMinTime").value = f.min_time;
  $("#fMaxTime").value = f.max_time;
  $("#fViewersLtSlots").checked = !!f.viewers_lt_slots;
  $("#fHideLate").checked = Number(f.hide_late) > 0;
  $("#fHighlight").value = f.highlight;
  for (const chip of $$("#quickTime .chip")) {
    chip.onclick = () => {
      $("#fMinTime").value = chip.dataset.min;
      $("#fMaxTime").value = chip.dataset.max;
    };
  }
}

function collectFilters() {
  const f = state.prefs.filters;
  f.min_coins = $("#fMinCoins").value;
  f.max_coins = $("#fMaxCoins").value;
  f.min_ratio = $("#fMinRatio").value;
  f.max_ratio = $("#fMaxRatio").value;
  f.min_time = $("#fMinTime").value;
  f.max_time = $("#fMaxTime").value;
  f.viewers_lt_slots = $("#fViewersLtSlots").checked;
  f.hide_late = $("#fHideLate").checked ? 60 : "";
  f.highlight = $("#fHighlight").value;
}

function filterChipCount() {
  const f = state.prefs.filters;
  let n = 0;
  if (f.kind !== "all") n++;
  if (f.variants.length) n++;
  for (const k of ["min_coins", "max_coins", "min_ratio", "max_ratio", "min_time", "max_time", "highlight"]) {
    if (f[k] !== "" && f[k] !== undefined) n++;
  }
  if (f.viewers_lt_slots) n++;
  if (Number(f.hide_late) > 0) n++;
  return n;
}

function syncFilterBadge() {
  const n = filterChipCount();
  const badge = $("#filterCount");
  badge.textContent = n;
  badge.classList.toggle("hidden", n === 0);
  $("#filterBtn").classList.toggle("active", n > 0);
}

function hydrateSettings() {
  const p = state.prefs;
  bindSegmented("#sLang", p.lang, v => { p.lang = v; applyStaticLabels(); render(); });
  bindSegmented("#sTheme", p.theme, v => { p.theme = v; applyTheme(); });
  bindSegmented("#sSource", p.source, v => { p.source = v; updateSourceHint(); });
  $("#sBridge").value = p.bridge;
  $("#sFont").value = Math.round(p.scale * 100);
  $("#sSound").checked = p.sound;
  $("#sNotify").checked = p.notify;
  $("#sAutoPip").checked = p.autoPip;
  $("#sRed").value = p.thresholds.red;
  $("#sAmber").value = p.thresholds.amber;
  $("#sGreen").value = p.thresholds.green;
  $("#cRed").value = p.colors.red;
  $("#cAmber").value = p.colors.amber;
  $("#cGreen").value = p.colors.green;
  $("#sTgToken").value = p.tg.bot_token ? "***" : "";
  $("#sTgToken").placeholder = p.tg.bot_token ? "kayıtlı — değiştirmek için yeni token yaz" : "bot token (123456:ABC…)";
  $("#sTgChat").value = p.tg.chat_id || "";
  $("#sTgRatio").value = p.tg.min_ratio;
  $("#sTgCoins").value = p.tg.min_coins;
  $("#sTgDisabled").checked = !p.tg.enabled;
  updateSourceHint();
  updateDataInfo();
}

function collectSettings() {
  const p = state.prefs;
  p.scale = Number($("#sFont").value) / 100;
  p.sound = $("#sSound").checked;
  p.notify = $("#sNotify").checked;
  p.autoPip = $("#sAutoPip").checked;
  p.thresholds = { red: +$("#sRed").value, amber: +$("#sAmber").value, green: +$("#sGreen").value };
  p.colors = { red: $("#cRed").value, amber: $("#cAmber").value, green: $("#cGreen").value };
  p.bridge = ($("#sBridge").value || "").trim().replace(/\/+$/, "") || DEFAULTS.bridge;
  p.tg.chat_id = $("#sTgChat").value.trim();
  const tok = $("#sTgToken").value.trim();
  if (tok && tok !== "***") p.tg.bot_token = tok;
  p.tg.min_ratio = +$("#sTgRatio").value || 0;
  p.tg.min_coins = +$("#sTgCoins").value || 0;
  p.tg.enabled = !$("#sTgDisabled").checked;
}

function updateSourceHint() {
  const box = $("#sourceStatus");
  if (!box) return;
  if (state.prefs.source === "local") {
    box.textContent = state.bridgeOk
      ? "● yerel köprü bağlı: " + bridgeBase()
      : "köprüye ulaşılamadı — bilgisayarda local-server/bridge.py çalışıyor mu? Tarayıcı yerel ağ iznini reddettiyse "
        + "paneli doğrudan " + bridgeBase() + " adresinden açabilirsin (aynı arayüz, canlı veri).";
  } else {
    box.textContent = "● GitHub modu: data/rooms.json (Actions işçisi ~5 dakikada bir yeniler).";
  }
}

function updateDataInfo() {
  const box = $("#dataInfo");
  if (!box) return;
  const d = state.data;
  if (!d) { box.textContent = "—"; return; }
  const when = d.generated_at ? new Date(d.generated_at).toLocaleString() : "?";
  const bits = [
    `kaynak: ${state.activeSource === "local" ? "yerel köprü" : "data/rooms.json"}`,
    `sağlayıcı: ${d.provider || "?"}`,
    `üretildi: ${when}`,
    `gösterilen: ${state.rooms.length} / toplam: ${d.total ?? state.all.length ?? "?"}`,
  ];
  if (d.demo) bits.push("DEMO");
  if (d.stale) bits.push("ESKİ VERİ");
  if (d.notice) bits.push(d.notice);
  if (d.error) bits.push("hata: " + d.error);
  box.textContent = bits.join(" · ");
}

function applyTheme() {
  const mode = state.prefs.theme;
  const dark = mode === "dark" || (mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? "#0b0f14" : "#f4f6fa";
}

function applyScale() {
  document.documentElement.style.setProperty("--scale", state.prefs.scale);
}

const STATIC_LABELS = {
  tr: { sort: ["Açılışa göre", "Jeton", "Oran", "İzleyici", "Kalan süre"], filter: "Filtre ",
        filtTitle: "Filtreler", setTitle: "Ayarlar", apply: "Uygula", reset: "Sıfırla",
        close: "Kapat", save: "Kaydet", empty: "Filtreleri sıfırla" },
  en: { sort: ["By open time", "Coins", "Ratio", "Viewers", "Time left"], filter: "Filter ",
        filtTitle: "Filters", setTitle: "Settings", apply: "Apply", reset: "Reset",
        close: "Close", save: "Save", empty: "Reset filters" },
  vi: { sort: ["Theo giờ mở", "Xu", "Ratio", "Người xem", "Thời gian còn"], filter: "Bộ lọc ",
        filtTitle: "Bộ lọc", setTitle: "Cài đặt", apply: "Áp dụng", reset: "Đặt lại",
        close: "Đóng", save: "Lưu", empty: "Đặt lại bộ lọc" },
};

function applyStaticLabels() {
  const L = STATIC_LABELS[state.prefs.lang] || STATIC_LABELS.tr;
  L.sort.forEach((label, i) => { if ($("#sortSelect").options[i]) $("#sortSelect").options[i].textContent = label; });
  $("#filterBtn").firstChild.textContent = L.filter;
  $("#filterTitle").textContent = L.filtTitle;
  $("#settingsTitle").textContent = L.setTitle;
  $("#applyFilters").textContent = L.apply;
  $("#resetFilters").textContent = L.reset;
  $("#closeSettings").textContent = L.close;
  $("#saveSettings").textContent = L.save;
  $("#emptyReset").textContent = L.empty;
}

/* -------------------------------------------------------------------- köprü */
async function probeBridge(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 1500);
  try {
    const res = await fetch(`${url}/api/health`, { signal: ctrl.signal, cache: "no-store" });
    const data = await res.json();
    return !!(res.ok && data.ok);
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/* ------------------------------------------------------------------- başlat */
async function boot() {
  loadPrefs();
  applyTheme();
  applyScale();
  hydrateFilterForm();
  hydrateSettings();
  applyStaticLabels();
  $("#sortSelect").value = state.prefs.sort;
  syncFilterBadge();
  renderTabs();

  // Sayfa köprünün kendisinden servis ediliyorsa (aynı origin) canlı moda geç.
  if (location.protocol.startsWith("http") && !/github\.io$/.test(location.hostname)) {
    if (await probeBridge(location.origin)) {
      state.prefs.source = "local";
      state.prefs.bridge = location.origin;
      state.bridgeOk = true;
      hydrateSettings();
    }
  }

  await fetchData();
  const period = Math.max(30, Number(state.data?.refresh_seconds) || 60) * 1000;
  clearInterval(state.timer);
  state.timer = setInterval(fetchData, state.prefs.source === "local" ? period : Math.max(60_000, period));
  if (!state.clock) state.clock = setInterval(tickTimers, 1000);
  if (!state.filterClock) state.filterClock = setInterval(syncFilterBadge, 2000);
  if (state.prefs.source === "local") subscribeEvents();
}

function subscribeEvents() {
  if (state.es) state.es.close();
  try {
    const es = new EventSource(`${bridgeBase()}/api/stream`);
    state.es = es;
    es.addEventListener("new_room", () => { fetchData(); });
    es.onerror = () => { /* EventSource kendi kendine yeniden bağlanır */ };
  } catch { }
}

/* ---------------------------------------------------------------- olaylar */
$("#filterBtn").onclick = () => { hydrateFilterForm(); openSheet("filterSheet"); };
$("#refreshBtn").onclick = () => { state.firstLoad = true; fetchData(); flash("⟳"); };
$("#settingsBtn").onclick = async () => {
  hydrateSettings();
  openSheet("settingsSheet");
  if (state.prefs.source === "local") state.bridgeOk = await probeBridge(bridgeBase());
  updateSourceHint();
};
$("#soundBtn").onclick = e => {
  state.playing = !state.playing;
  e.currentTarget.classList.toggle("on", state.playing);
  e.currentTarget.textContent = state.playing ? "🔔" : "🔕";
  beep(660, 0.08);
};
$("#pipBtn").onclick = () => toggleMini();
$("#miniClose").onclick = () => $("#mini").classList.add("hidden");
$("#miniPip").onclick = () => toggleMini(true);
$("#emptyReset").onclick = () => {
  state.prefs.filters = structuredClone(DEFAULTS.filters);
  savePrefs(); hydrateFilterForm(); fetchData(); syncFilterBadge();
};

$("#sortSelect").onchange = e => {
  state.prefs.sort = e.target.value; savePrefs(); fetchData();
};

$("#applyFilters").onclick = () => {
  collectFilters(); savePrefs(); closeSheet("filterSheet"); fetchData(); syncFilterBadge();
};
$("#resetFilters").onclick = () => {
  state.prefs.filters = structuredClone(DEFAULTS.filters);
  hydrateFilterForm(); savePrefs(); closeSheet("filterSheet"); fetchData(); syncFilterBadge();
};

$("#closeSettings").onclick = () => closeSheet("settingsSheet");
$("#saveSettings").onclick = async () => {
  const before = state.prefs.source;
  collectSettings();
  savePrefs(); applyTheme(); applyScale();
  closeSheet("settingsSheet");
  state.bridgeOk = state.prefs.source === "local" ? await probeBridge(bridgeBase()) : false;
  if (state.prefs.source !== before || state.bridgeOk) { state.firstLoad = true; await boot(); }
  else { render(); }
  flash("✓");
};

$("#sBridgeOpen").onclick = () => window.open(bridgeBase() + "/", "_blank", "noopener");

$("#sBridgeTest").onclick = async () => {
  const url = ($("#sBridge").value || "").trim().replace(/\/+$/, "");
  const box = $("#sourceStatus");
  box.textContent = "deneniyor…";
  const ok = url ? await probeBridge(url) : false;
  state.bridgeOk = ok;
  box.textContent = ok ? `✓ köprü çalışıyor: ${url}` : `✗ ulaşılamadı: ${url || "(boş)"}`;
};

$("#sLiveCheck").onclick = () => checkLiveTarget(false);
$("#sLiveOpen").onclick = () => checkLiveTarget(true);
$("#sLiveInput").addEventListener("keydown", e => { if (e.key === "Enter") checkLiveTarget(false); });

$("#sNotify").onchange = async e => {
  if (e.target.checked && "Notification" in window && Notification.permission !== "granted") {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") e.target.checked = false;
  }
};

$("#sTgTest").onclick = async () => {
  collectSettings();
  savePrefs();
  const box = $("#tgStatus");
  box.textContent = "gönderiliyor…";
  try {
    const r = await sendTelegram("✅ <b>SandıkRadar</b> test bildirimi — panel çalışıyor.");
    box.textContent = r.ok ? "✓ gönderildi" : "✗ " + (r.detail || r.description || "hata");
  } catch (err) {
    box.textContent = "✗ " + err.message;
  }
};

$("#sBridge").addEventListener("change", () => {
  state.prefs.bridge = ($("#sBridge").value || "").trim().replace(/\/+$/, "") || DEFAULTS.bridge;
  savePrefs();
});

for (const backdrop of $$(".sheet-backdrop")) {
  backdrop.onclick = () => closeSheet(backdrop.dataset.close);
}

$("#list").addEventListener("click", ev => {
  const card = ev.target.closest(".card");
  if (!card || !card._room) return;
  if (ev.target.closest(".open-btn")) return openRoom(card._room);
  if (ev.target.closest(".copy-btn")) return copyComment(card._room);
  if (ev.target.closest(".share-btn")) {
    const url = `https://www.tiktok.com/@${card._room.user}/live`;
    if (navigator.share) navigator.share({ title: "SandıkRadar", url }).catch(() => { });
    else navigator.clipboard?.writeText(url).then(() => flash("✓")).catch(() => { });
  }
});

// mini pencereyi sürükle
(() => {
  let drag = null;
  const head = $("#miniHead");
  const mini = $("#mini");
  head.addEventListener("pointerdown", e => {
    if (e.target.closest("button")) return;
    const rect = mini.getBoundingClientRect();
    drag = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    head.setPointerCapture(e.pointerId);
  });
  head.addEventListener("pointermove", e => {
    if (!drag) return;
    mini.style.left = `${Math.min(window.innerWidth - 60, Math.max(0, e.clientX - drag.x))}px`;
    mini.style.top = `${Math.min(window.innerHeight - 60, Math.max(0, e.clientY - drag.y))}px`;
    mini.style.right = "auto";
    mini.style.bottom = "auto";
  });
  head.addEventListener("pointerup", () => { drag = null; });
})();

document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.prefs.autoPip) toggleMini(true);
});

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (state.prefs.theme === "system") applyTheme();
});

if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("sw.js").catch(() => { });
}

boot();
