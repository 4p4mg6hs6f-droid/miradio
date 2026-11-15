// miradio: 정적 뉴스 오디오 웹앱 (바닐라 JS, 빌드 도구 없음)
"use strict";
const $ = (s) => document.querySelector(s);
const KEY = "miradio.v1", POS = "miradio.pos.v1";
const MINS = [[10, "10분"], [30, "30분"], [60, "1시간"]];
const VOICES = [["female", "여성"], ["male", "남성"]];
const CAT_ORDER = ["politics", "economy", "society", "it"];
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};

const audio = $("#audio");
const warm = new Audio(); warm.preload = "auto";   // 다음 청크 미리 로딩(캐시 예열)
let manifest = null, list = [], idx = 0, errStreak = 0;
let stallTimer = 0, stalled = false, pendingWarm = "", seekOnLoad = 0, lastSaved = -1;
let ctx = { cats: [], voice: "female", mins: 30 };       // 현재 재생 중인 플레이리스트의 조건
let pref = { mins: 30, cats: ["politics"], voice: "female", rate: 1 };
{
  const o = store.get(KEY) || {};
  Object.assign(pref, o);
  if (o.cat && !o.cats) pref.cats = [o.cat];              // 예전 저장값(단일 분야) 이전
  delete pref.cat;
  if (!Array.isArray(pref.cats)) pref.cats = ["politics"];
}
const savePref = () => store.set(KEY, pref);

const fmt = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const fmtKo = (s) => { s = Math.round(s); const m = Math.floor(s / 60), r = s % 60; return m ? `${m}분${r ? ` ${r}초` : ""}` : `${r}초`; };
function status(msg, retry) {
  const el = $("#status"); el.hidden = !msg; el.textContent = msg || "";
  if (msg && retry) { const b = document.createElement("button"); b.textContent = "다시 시도"; b.onclick = retry; el.append(document.createElement("br"), b); }
}

// ── 설정 칩 (시간·목소리는 단일 선택, 분야는 다중 선택) ───────────────────
function chips(id, opts, isOn, pick) {
  const box = $(id); box.replaceChildren();
  for (const [val, label] of opts) {
    const b = document.createElement("button");
    b.className = "chip"; b.textContent = label;
    b.setAttribute("aria-pressed", String(isOn(val)));
    b.onclick = () => { pick(val); savePref(); renderSettings(); };
    box.append(b);
  }
}
function renderSettings() {
  const avail = CAT_ORDER.filter((c) => manifest.categories[c]);
  pref.cats = pref.cats.filter((c) => avail.includes(c));
  if (!pref.cats.length && avail.length) pref.cats = [avail[0]];
  chips("#g-mins", MINS, (v) => pref.mins === v, (v) => (pref.mins = v));
  chips("#g-cat", avail.map((c) => [c, manifest.categories[c].label]), (v) => pref.cats.includes(v), (v) => {
    const i = pref.cats.indexOf(v);
    if (i < 0) pref.cats.push(v);
    else if (pref.cats.length > 1) pref.cats.splice(i, 1);   // 최소 1개는 유지
  });
  chips("#g-voice", VOICES, (v) => pref.voice === v, (v) => (pref.voice = v));
  $("#mixnote").hidden = pref.cats.length < 2;
}

// ── 플레이리스트: 여러 분야는 번갈아 섞고, 목표 시간에 가장 가까운 지점에서 끊기 ──
function buildPlaylist(cats, voice, mins) {
  const lists = cats.map((c) => {
    const m = manifest.categories[c];
    const chunks = (m && m.voices[voice] && m.voices[voice].chunks) || [];
    return chunks.map((ch) => ({ ...ch, cat: c, catLabel: m.label }));
  });
  let seq;
  if (lists.length === 1) seq = lists[0];
  else {                                                   // 인트로(첫 청크) 제외, 라운드로빈
    const q = lists.map((l) => l.slice(1));
    seq = [];
    for (let i = 0; q.some((a) => i < a.length); i++) for (const a of q) if (i < a.length) seq.push(a[i]);
  }
  const target = mins * 60;
  let cum = 0, best = Math.min(1, seq.length), bestDiff = Infinity;
  for (let i = 0; i < seq.length; i++) {
    cum += seq[i].duration;
    const diff = Math.abs(cum - target);
    if (diff < bestDiff) { bestDiff = diff; best = i + 1; }
    if (cum > target) break;                               // 이후는 차이가 계속 커짐
  }
  return seq.slice(0, best);                               // 재료가 부족하면 있는 만큼만
}
function renderList() {
  const ol = $("#list"); ol.replaceChildren();
  const mixed = ctx.cats.length > 1;
  list.forEach((c, i) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.innerHTML = "<span></span><small></small>";
    b.children[0].textContent = c.title; b.children[1].textContent = fmt(c.duration);
    b.onclick = () => load(i, true);
    li.append(b);
    if (c.source || mixed) {
      const a = document.createElement("a");
      a.textContent = `${mixed ? c.catLabel + " · " : ""}${c.source ? "출처: " + c.source : ""}`;
      if (c.link) { a.href = c.link; a.target = "_blank"; a.rel = "noopener noreferrer"; }
      li.append(a);
    }
    ol.append(li);
  });
}

// ── 마지막 듣던 위치 저장/복원 ───────────────────────────────────────────
function savePos(force, t = audio.currentTime || 0) {
  const c = list[idx];
  if (!c) return;
  const dur = audio.duration;
  if (dur && isFinite(dur) && t > dur - 1) return;          // 곡 끝 위치는 저장하지 않음
  const key = Math.floor(t / 5);
  if (!force && key === lastSaved) return;                   // 5초 단위로만 저장
  lastSaved = key;
  store.set(POS, { ...ctx, url: c.audio, title: c.title, time: t, at: Date.now() });
}
function showResume() {
  const p = store.get(POS);
  $("#resume").hidden = true;
  if (!p || !Array.isArray(p.cats) || !p.cats.length) return;
  if (!p.cats.every((c) => manifest.categories[c])) return store.del(POS);
  const pl = buildPlaylist(p.cats, p.voice, p.mins);
  const i = pl.findIndex((c) => c.audio === p.url);
  if (i < 0) return store.del(POS);                          // 새 뉴스로 교체되어 위치 무효
  $("#r-title").textContent = p.title;
  $("#r-meta").textContent = `${p.cats.map((c) => manifest.categories[c].label).join("·")} · ${i + 1}/${pl.length}번째 · ${fmt(p.time)}`;
  $("#resume").hidden = false;
  $("#r-go").onclick = () => {
    Object.assign(pref, { cats: p.cats, voice: p.voice, mins: p.mins }); savePref(); renderSettings();
    ctx = { cats: p.cats, voice: p.voice, mins: p.mins };
    startPlay(pl, i, p.time);
  };
}

// ── 재생 ─────────────────────────────────────────────────────────────
function startPlay(pl, i, t) {
  list = pl; errStreak = 0; status("");
  $("#resume").hidden = true; $("#player").hidden = false; renderList();
  const total = list.reduce((s, c) => s + c.duration, 0);
  if (total < ctx.mins * 60 * 0.8) status(`${fmtKo(total)} 분량의 뉴스가 준비되었습니다.`);
  load(i, true, t);
  $("#player").scrollIntoView({ behavior: "smooth", block: "start" });
}
function load(i, autoplay, seekTo = 0) {
  if (i < 0 || i >= list.length) return;
  idx = i; const c = list[i];
  seekOnLoad = seekTo; lastSaved = -1;
  audio.src = c.audio;
  audio.defaultPlaybackRate = audio.playbackRate = pref.rate;
  if (autoplay) audio.play().catch(onPlayError);
  pendingWarm = list[i + 1] ? list[i + 1].audio : "";       // 다음 청크 미리 로딩은 canplay 이후
  clearTimeout(stallTimer); stalled = false;
  if (autoplay) stallTimer = setTimeout(() => {             // 10초 넘게 데이터가 안 오면 단서 표시
    if (audio.readyState < 3 && !audio.error) {
      stalled = true;
      status(`음원 응답이 늦습니다 (readyState ${audio.readyState}, network ${audio.networkState}).`);
      console.warn("[audio] stalled", audio.src);
    }
  }, 10000);
  $("#title").textContent = c.title;
  $("#source").textContent = c.source ? `출처: ${c.source}` : "";
  document.querySelectorAll("#list li").forEach((li, n) => {
    if (n === i) { li.setAttribute("aria-current", "true"); li.scrollIntoView({ block: "nearest" }); }
    else li.removeAttribute("aria-current");
  });
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: c.title, artist: c.source || "miradio",
      album: `${c.catLabel} 뉴스 · ${i + 1}/${list.length}`,
      artwork: [{ src: "icon-512.png", sizes: "512x512", type: "image/png" }] });
  }
  savePos(true, seekTo);
  tick();
}
const next = (auto = true) => {
  if (idx + 1 < list.length) load(idx + 1, auto);
  else { audio.pause(); store.del(POS); status("모든 기사를 들었습니다."); }
};
const prev = () => (audio.currentTime > 3 ? (audio.currentTime = 0) : load(Math.max(0, idx - 1), true));
function onPlayError(e) { if (e && e.name !== "AbortError") status("재생을 시작하지 못했습니다. 재생 버튼을 눌러 주세요."); }

function tick() {
  const dur = audio.duration || (list[idx] && list[idx].duration) || 0, cur = audio.currentTime || 0;
  $("#cur").textContent = fmt(cur); $("#dur").textContent = fmt(dur);
  $("#seek").value = dur ? Math.round((cur / dur) * 1000) : 0;
  const left = list.slice(idx + 1).reduce((s, c) => s + c.duration, 0) + Math.max(0, dur - cur);
  $("#remain").textContent = fmt(left / pref.rate);
  const paused = audio.paused;
  $("#play use").setAttribute("href", paused ? "#i-play" : "#i-pause");
  $("#play").setAttribute("aria-label", paused ? "재생" : "일시정지");
  if ("mediaSession" in navigator) {
    navigator.mediaSession.playbackState = paused ? "paused" : "playing";
    if (dur && isFinite(dur)) {
      try { navigator.mediaSession.setPositionState({ duration: dur, position: Math.min(cur, dur), playbackRate: pref.rate }); } catch {}
    }
  }
}

audio.addEventListener("timeupdate", () => { tick(); savePos(false); });
audio.addEventListener("play", tick);
audio.addEventListener("pause", () => { tick(); savePos(true); });
audio.addEventListener("loadedmetadata", () => {
  if (seekOnLoad) { audio.currentTime = Math.min(seekOnLoad, Math.max(0, audio.duration - 1)); seekOnLoad = 0; }
  audio.playbackRate = pref.rate; if (errStreak) status(""); errStreak = 0; tick();
});
audio.addEventListener("canplay", () => { if (pendingWarm) { warm.src = pendingWarm; pendingWarm = ""; } });
audio.addEventListener("playing", () => { clearTimeout(stallTimer); if (stalled) { stalled = false; status(""); } });
audio.addEventListener("ended", () => next(true));
const ERR = { 1: "중단됨", 2: "네트워크 오류", 3: "디코딩 오류", 4: "주소 또는 형식 미지원" };
audio.addEventListener("error", () => {                    // 깨진 청크는 건너뛰되, 연속 3회 실패 시 중단
  if (!audio.src) return;
  const c = audio.error && audio.error.code, detail = `코드 ${c}: ${ERR[c] || "알 수 없음"}`;
  console.error("[audio]", detail, audio.error && audio.error.message, audio.src);
  if (++errStreak >= 3) return status(`오디오를 불러오지 못했습니다 (${detail}).`);
  status(`오디오 하나를 불러오지 못해 다음 기사로 넘어갑니다 (${detail}).`); next(true);
});
addEventListener("pagehide", () => savePos(true));
document.addEventListener("visibilitychange", () => { if (document.hidden) savePos(true); });

$("#seek").oninput = (e) => { if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration; };
$("#play").onclick = () => (audio.paused ? audio.play().catch(onPlayError) : audio.pause());
$("#prev").onclick = prev; $("#next").onclick = () => next(true);
$("#rate").onchange = (e) => { pref.rate = +e.target.value; audio.playbackRate = audio.defaultPlaybackRate = pref.rate; savePref(); tick(); };

// 사용자 클릭 후에만 재생 시작 (브라우저 자동재생 정책)
$("#start").onclick = () => {
  ctx = { cats: CAT_ORDER.filter((c) => pref.cats.includes(c)), voice: pref.voice, mins: pref.mins };
  startPlay(buildPlaylist(ctx.cats, ctx.voice, ctx.mins), 0, 0);
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

// ── 웹앱(PWA): 서비스 워커 + 설치 버튼 ───────────────────────────────────
if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
let deferredInstall = null;
addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; $("#install").hidden = false; });
$("#install").onclick = async () => {
  if (!deferredInstall) return;
  deferredInstall.prompt(); await deferredInstall.userChoice;
  deferredInstall = null; $("#install").hidden = true;
};
{
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = navigator.standalone || matchMedia("(display-mode: standalone)").matches;
  if (ios && !standalone) $("#ioshint").hidden = false;
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
  showResume();
}
init();
