// 정적 뉴스 오디오 플레이어 (바닐라 JS, 빌드 도구 없음)
"use strict";
const $ = (s) => document.querySelector(s);
const KEY = "miradio.v1";
const MINS = [[10, "10분"], [30, "30분"], [60, "1시간"]];
const VOICES = [["female", "여성"], ["male", "남성"]];
const CAT_ORDER = ["politics", "economy", "society", "it"];

const audio = $("#audio");
const warm = new Audio(); warm.preload = "auto";   // 다음 청크 미리 로딩용 (HTTP 캐시 예열)
let manifest = null, list = [], idx = 0, errStreak = 0;
let pref = { mins: 30, cat: "politics", voice: "female", rate: 1 };
try { Object.assign(pref, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(pref)); } catch {} };

const fmt = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
function status(msg, retry) {
  const el = $("#status"); el.hidden = !msg; el.textContent = msg || "";
  if (msg && retry) { const b = document.createElement("button"); b.textContent = "다시 시도"; b.onclick = retry; el.append(document.createElement("br"), b); }
}

// ── 설정 칩 ──────────────────────────────────────────────────────────
function chips(id, opts, key) {
  const box = $(id); box.replaceChildren();
  for (const [val, label] of opts) {
    const b = document.createElement("button");
    b.className = "chip"; b.textContent = label;
    b.setAttribute("aria-pressed", String(pref[key] === val));
    b.onclick = () => { pref[key] = val; save(); renderSettings(); };
    box.append(b);
  }
}
function renderSettings() {
  const cats = CAT_ORDER.filter((c) => manifest.categories[c]).map((c) => [c, manifest.categories[c].label]);
  if (!cats.some(([c]) => c === pref.cat) && cats.length) pref.cat = cats[0][0];
  chips("#g-mins", MINS.map(([v, l]) => [v, l]), "mins");
  chips("#g-cat", cats, "cat");
  chips("#g-voice", VOICES, "voice");
}

// ── 플레이리스트: 목표 시간에 가장 가까운 지점에서 끊기 ────────────────────
function buildPlaylist() {
  const chunks = manifest.categories[pref.cat].voices[pref.voice].chunks;
  const target = pref.mins * 60;
  let cum = 0, best = 1, bestDiff = Infinity;
  for (let i = 0; i < chunks.length; i++) {
    cum += chunks[i].duration;
    const diff = Math.abs(cum - target);
    if (diff < bestDiff) { bestDiff = diff; best = i + 1; }
    if (cum > target) break;               // 이후는 차이가 계속 커지므로 중단
  }
  return chunks.slice(0, best);              // 재료가 부족하면 있는 만큼만
}
function renderList() {
  const ol = $("#list"); ol.replaceChildren();
  list.forEach((c, i) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.innerHTML = "<span></span><small></small>";
    b.children[0].textContent = c.title; b.children[1].textContent = fmt(c.duration);
    b.onclick = () => load(i, true);
    li.append(b);
    if (c.source) {
      const a = document.createElement("a");
      a.textContent = `출처: ${c.source}`; a.href = c.link || "#"; a.target = "_blank"; a.rel = "noopener noreferrer";
      li.append(a);
    }
    ol.append(li);
  });
}

// ── 재생 ─────────────────────────────────────────────────────────────
function load(i, autoplay) {
  if (i < 0 || i >= list.length) return;
  idx = i; const c = list[i];
  audio.src = c.audio;
  audio.defaultPlaybackRate = audio.playbackRate = pref.rate;
  if (autoplay) audio.play().catch(onPlayError);
  if (list[i + 1]) warm.src = list[i + 1].audio;   // 다음 청크 미리 로딩
  $("#title").textContent = c.title;
  $("#source").textContent = c.source ? `출처: ${c.source}` : "";
  document.querySelectorAll("#list li").forEach((li, n) => {
    if (n === i) { li.setAttribute("aria-current", "true"); li.scrollIntoView({ block: "nearest" }); }
    else li.removeAttribute("aria-current");
  });
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: c.title, artist: c.source || "miradio",
      album: `${manifest.categories[pref.cat].label} 뉴스 · ${i + 1}/${list.length}` });
  }
  tick();
}
const next = (auto = true) => { if (idx + 1 < list.length) load(idx + 1, auto); else { audio.pause(); status("모든 기사를 들었습니다."); } };
const prev = () => (audio.currentTime > 3 ? (audio.currentTime = 0) : load(Math.max(0, idx - 1), true));
function onPlayError(e) { if (e && e.name !== "AbortError") status("재생을 시작하지 못했습니다. 재생 버튼을 눌러 주세요."); }

function tick() {
  const dur = audio.duration || list[idx]?.duration || 0, cur = audio.currentTime || 0;
  $("#cur").textContent = fmt(cur); $("#dur").textContent = fmt(dur);
  $("#seek").value = dur ? Math.round((cur / dur) * 1000) : 0;
  const left = list.slice(idx + 1).reduce((s, c) => s + c.duration, 0) + Math.max(0, dur - cur);
  $("#remain").textContent = fmt(left / pref.rate);
  $("#play").textContent = audio.paused ? "▶" : "⏸";
  if ("mediaSession" in navigator && dur && isFinite(dur)) {
    try { navigator.mediaSession.setPositionState({ duration: dur, position: Math.min(cur, dur), playbackRate: pref.rate }); } catch {}
  }
}

audio.addEventListener("timeupdate", tick);
audio.addEventListener("play", tick); audio.addEventListener("pause", tick);
audio.addEventListener("loadedmetadata", () => { audio.playbackRate = pref.rate; if (errStreak) status(""); errStreak = 0; tick(); });
audio.addEventListener("ended", () => next(true));
audio.addEventListener("error", () => {                 // 깨진 청크는 건너뛰되, 연속 3회 실패 시 중단
  if (!audio.src) return;
  if (++errStreak >= 3) return status("오디오를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
  status("오디오 하나를 불러오지 못해 다음 기사로 넘어갑니다."); next(true);
});
$("#seek").oninput = (e) => { if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration; };
$("#play").onclick = () => (audio.paused ? audio.play().catch(onPlayError) : audio.pause());
$("#prev").onclick = prev; $("#next").onclick = () => next(true);
$("#rate").onchange = (e) => { pref.rate = +e.target.value; audio.playbackRate = audio.defaultPlaybackRate = pref.rate; save(); tick(); };

// 사용자 클릭 후에만 재생 시작 (브라우저 자동재생 정책)
$("#start").onclick = () => {
  list = buildPlaylist(); errStreak = 0; status("");
  $("#player").hidden = false; renderList();
  const total = list.reduce((s, c) => s + c.duration, 0);
  if (total < pref.mins * 60 * 0.8) status(`준비된 뉴스가 ${fmt(total)}분량뿐이라 그만큼만 재생합니다.`);
  load(0, true);
  $("#player").scrollIntoView({ behavior: "smooth", block: "start" });
};

// Media Session: 잠금화면/백그라운드 컨트롤
if ("mediaSession" in navigator) {
  const ms = navigator.mediaSession;
  const set = (a, f) => { try { ms.setActionHandler(a, f); } catch {} };
  set("play", () => audio.play()); set("pause", () => audio.pause());
  set("previoustrack", prev); set("nexttrack", () => next(true));
  set("seekbackward", () => (audio.currentTime = Math.max(0, audio.currentTime - 15)));
  set("seekforward", () => (audio.currentTime = Math.min(audio.duration || 1e9, audio.currentTime + 15)));
  set("seekto", (d) => { audio.currentTime = d.seekTime; });
}

// ── 초기화 ───────────────────────────────────────────────────────────
async function init() {
  status("");
  try {
    const r = await fetch("manifest.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    manifest = await r.json();
    if (!Object.keys(manifest.categories || {}).length) throw new Error("empty");
  } catch {
    $("#updated").textContent = "";
    return status("뉴스 목록을 불러오지 못했습니다. 아직 첫 생성이 끝나지 않았거나 네트워크 문제일 수 있습니다.", init);
  }
  $("#updated").textContent = "마지막 갱신 " + new Date(manifest.updated_at).toLocaleString("ko-KR",
    { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  $("#rate").value = String(pref.rate);
  renderSettings();
  $("#start").disabled = false;
}
init();
