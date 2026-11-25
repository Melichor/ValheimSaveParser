"use strict";

/* Creation timer. Beeps four times faintly, one second apart, and a fifth time loudly exactly on a chosen local time, so
   a new character can be created during that second. The time is a local time in the shared time zone (#zone); the shift (ms)
   moves every beep. Uses the time helpers of web/finder.js (wallParts, wallToMs, localNow, TIME_ZONE, el) and its shared
   time zone choice (zone(), setZone, ZONE), which loads first.

   The beeps are Web Audio oscillators started at an exact time on the audio clock, which is far steadier than page
   timers (those can be late by tens of milliseconds, or by seconds in a background tab). The audio clock is mapped to
   this computer's wall clock about 15 seconds before the first beep, so drift between the two clocks over a long wait
   does not matter. The mapping uses AudioContext.getOutputTimestamp (what is leaving the speakers when), so the output
   delay is allowed for and the sound is heard on time; delay the browser cannot see (Bluetooth) is what Shift is for. */

const T = {
  form: byId("tForm"), time: byId("tTime"), shift: byId("tShift"), go: byId("tGo"), stop: byId("tStop"),
  test: byId("tTest"), error: byId("tError"), clock: byId("tClock"), zoneName: byId("tZoneName"), left: byId("tLeft"),
  leftLabel: byId("tLeftLabel"), state: byId("tState"),
};

const BEEPS = 5;                 // four faint ones, then the loud one on the time
const LEAD_MS = 15000;           // schedule the beeps this long before the first one
const SHIFT_KEY = "valheim-timer-shift";

let audio = null;                // the AudioContext, made on the first click (browsers only allow sound after one)
let run = null;                  // the running timer: { target (epoch ms of the loud beep), label, nodes, scheduled }

// the time starts as now in the shared zone, and follows the zone until it is changed by hand
let timeAuto = true;
T.time.value = localNow(zone());
T.time.addEventListener("input", () => { timeAuto = false; });
ZONE.addEventListener("change", () => { if (timeAuto) T.time.value = localNow(zone()); });
try { const v = localStorage.getItem(SHIFT_KEY); if (v !== null && v !== "") T.shift.value = v; } catch { /* no storage */ }

const shiftMs = () => { const v = Number(T.shift.value); return Number.isFinite(v) ? Math.max(-5000, Math.min(5000, v)) : 0; };

function fail(message) {
  T.error.textContent = message;
  T.error.hidden = false;
}

// ---------- sound ----------

async function unlockAudio() {
  if (!audio) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) throw new Error("This browser cannot play sound from a page.");
    audio = new Ctx({ latencyHint: "interactive" });
  }
  if (audio.state !== "running") await audio.resume();
}

// one beep starting at audio time `at`: short and faint, or longer, higher and loud for the last one
function beep(at, loud) {
  const osc = audio.createOscillator();
  const gain = audio.createGain();
  osc.type = "sine";
  osc.frequency.value = loud ? 1320 : 880;
  const peak = loud ? 0.6 : 0.06, length = loud ? 0.35 : 0.12;
  gain.gain.setValueAtTime(0, at);
  gain.gain.linearRampToValueAtTime(peak, at + 0.004);          // a 4 ms attack: the sound starts on the time
  gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
  osc.connect(gain).connect(audio.destination);
  osc.start(at);
  osc.stop(at + length + 0.02);
  return osc;
}

// the audio time at which a sound must start to be heard at epoch ms `ms`
function audioTimeOf(ms) {
  const wallNow = Date.now(), perfNow = performance.now();
  if (audio.getOutputTimestamp) {
    // the audio time leaving the speakers at a performance.now() time: the output delay is already in it
    const ts = audio.getOutputTimestamp();
    if (ts.performanceTime) return ts.contextTime + (perfNow - ts.performanceTime) / 1000 + (ms - wallNow) / 1000;
  }
  // without it, the audio time being rendered now, less the output delay the browser reports
  const latency = audio.outputLatency || audio.baseLatency || 0;
  return audio.currentTime + (ms - wallNow) / 1000 - latency;
}

function cancelBeeps() {
  if (!run) return;
  for (const n of run.nodes) { try { n.stop(); } catch { /* already done */ } }
  run.nodes = [];
  run.scheduled = false;
}

function scheduleBeeps() {
  cancelBeeps();
  const first = run.target - (BEEPS - 1) * 1000;
  for (let i = 0; i < BEEPS; i++) {
    const at = audioTimeOf(first + i * 1000);
    if (at < audio.currentTime) continue;       // already past (started late): skip that beep
    run.nodes.push(beep(at, i === BEEPS - 1));
  }
  run.scheduled = true;
}

// ---------- the timer ----------

async function start(targetWall, tz, label) {
  T.error.hidden = true;
  const base = wallToMs(targetWall, tz);
  if (base === null) {
    return fail(wallParts(Date.now(), tz) ? "That time never shows on a clock in this time zone (summer time skips it)."
      : "Unknown time zone: use a name such as Europe/Prague, UTC or an offset such as +02:00.");
  }
  try { await unlockAudio(); } catch (e) { return fail(e.message || "Could not start the sound."); }
  stop(false);
  run = { base, label, tz, nodes: [], scheduled: false };
  run.target = base + shiftMs();
  if (run.target - Date.now() < -1000) {
    run = null;
    return fail("That time has already passed.");
  }
  T.go.hidden = true;
  T.stop.hidden = false;
  showState();
  tick();
}

function stop(clearState = true) {
  cancelBeeps();
  run = null;
  T.go.hidden = false;
  T.stop.hidden = true;
  if (clearState) T.state.textContent = "";
  T.left.textContent = "–";
  T.left.classList.remove("go");
  T.leftLabel.textContent = "Next beep";
}

function showState() {
  if (!run) return;
  const s = shiftMs();
  T.state.textContent = `Beeping for ${run.label}` + (s ? ` (shifted ${s > 0 ? "+" : ""}${s} ms)` : "") +
    ": four faint beeps, then the loud one on the time.";
}

const fmtClock = (ms, tz) => {
  const w = wallParts(ms, tz);
  if (!w) return "--:--:--.---";
  return `${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}.${String(((ms % 1000) + 1000) % 1000).padStart(3, "0")}`;
};

function fmtLeft(ms) {
  const s = Math.max(0, ms) / 1000;
  if (s >= 3600) return `${Math.floor(s / 3600)} h ${pad(Math.floor(s / 60) % 60)} min`;
  if (s >= 60) return `${Math.floor(s / 60)} min ${pad(Math.floor(s) % 60)} s`;
  return s.toFixed(1) + " s";
}

// checks the schedule; runs on a timer, so it keeps going (if slower) in a background tab
function tick() {
  if (!run) return;
  const now = Date.now();
  const first = run.target - (BEEPS - 1) * 1000;
  if (!run.scheduled && first - now <= LEAD_MS) scheduleBeeps();
  if (now > run.target + 1500) {
    const label = run.label;
    stop(false);
    T.state.textContent = `Done: the loud beep was on ${label}.`;
  }
}
setInterval(tick, 200);

// the clock and the countdown, every frame while the tab is visible
function draw() {
  const tz = run ? run.tz : zone();
  T.zoneName.textContent = tz || TIME_ZONE || "this browser";
  T.clock.textContent = fmtClock(Date.now(), tz);
  if (run) {
    const now = Date.now();
    const first = run.target - (BEEPS - 1) * 1000;
    const next = now < first ? first : run.target - Math.floor((run.target - now) / 1000) * 1000;
    const isLast = next >= run.target;
    T.leftLabel.textContent = now < first ? "First beep in" : isLast ? "Loud beep in" : "Next beep in";
    T.left.textContent = fmtLeft((isLast ? run.target : next) - now);
    T.left.classList.toggle("go", now >= first);
  }
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

T.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const tz = zone();
  const shown = T.time.value.replace("T", " ") + (T.time.value.length === 16 ? ":00" : "");
  start(T.time.value, tz, `${shown} (${tz || TIME_ZONE})`);
});
T.stop.addEventListener("click", () => stop());

// a test run: the loud beep on the next whole second that is at least five seconds away
T.test.addEventListener("click", () => {
  const tz = zone();
  const at = Math.ceil((Date.now() + 5000) / 1000) * 1000;
  const w = wallParts(at, tz);
  if (!w) return fail("Unknown time zone: use a name such as Europe/Prague, UTC or an offset such as +02:00.");
  const wall = `${w.y}-${pad(w.mo)}-${pad(w.d)} ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}`;
  start(wall, tz, `a test at ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}`);
});

// a new shift applies at once, also to a running timer (and is remembered)
T.shift.addEventListener("input", () => {
  try { localStorage.setItem(SHIFT_KEY, T.shift.value); } catch { /* no storage */ }
  if (!run) return;
  run.target = run.base + shiftMs();
  if (run.scheduled) scheduleBeeps();
  showState();
});

// the finder and the relay planner open the timer with one of their times (see timerButton in web/finder.js)
window.openTimer = (time, tz) => {
  T.time.value = time.replace(" ", "T");
  timeAuto = false;
  setZone(tz || TIME_ZONE);
  T.error.hidden = true;
  document.getElementById("tab-timer").click();
  T.time.focus();
};

// ---------- checking the result: a dropped save against the timer's time ----------
// The save keeps the creation time to the whole second, so a miss is a whole number of seconds: created in second C
// when aiming for second T means the press came between C − T and C − T + 1 s after the start of the target second.
// With the loud beep at T + shift, a shift of about shift − (C − T) × 1000 ms would have put the press in the middle of
// the target second, give or take half a second. That is only suggested: the timer is never changed from here.

const V = {
  drop: byId("vDrop"), file: byId("vFile"), status: byId("vStatus"), statusText: byId("vStatusText"), error: byId("vError"),
  result: byId("vResult"), summary: byId("vSummary"), suggest: byId("vSuggest"), facts: byId("vFacts"),
};

function checkFail(message) {
  window.timerChecking = false;
  V.status.hidden = true;
  V.drop.classList.remove("busy");
  V.error.textContent = message;
  V.error.hidden = false;
}

async function check(file) {
  V.error.hidden = true;
  V.result.hidden = true;
  V.file.value = "";
  if (wallToMs(T.time.value, zone()) === null) {
    return checkFail("Set the timer's time (and the time zone at the top of the page) to the time you aimed for first.");
  }
  let bytes;
  try { bytes = await file.arrayBuffer(); } catch { return checkFail("Could not read that file."); }
  V.drop.classList.add("busy");
  V.status.hidden = false;
  V.statusText.textContent = worker ? "Reading the file…" : "Starting the Python runtime (about 10 MB, cached after the first visit)…";
  window.timerChecking = true;
  (worker || startWorker()).postMessage({ type: "created", bytes, tz: zone() }, [bytes]);
}

// the UTC offset (minutes) of zone tz at epoch ms, or null for an unknown zone
function zoneOffsetMin(ms, tz) {
  const w = wallParts(ms, tz);
  return w ? Math.round((Date.UTC(w.y, w.mo - 1, w.d, w.h, w.mi, w.s) - Math.floor(ms / 1000) * 1000) / 60000) : null;
}

const fmtOffset = (min) => `${min < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(min) / 60))}:${pad(Math.abs(min) % 60)}`;

// up to three zone names with UTC offset `min` at epoch ms, the browser's own first when it fits
function zonesWithOffset(min, ms) {
  let zones = [];
  try { zones = Intl.supportedValuesOf("timeZone"); } catch { /* none to suggest */ }
  const fit = (z) => zoneOffsetMin(ms, z) === min;
  return [...new Set([TIME_ZONE, ...zones])].filter((z) => z && fit(z)).slice(0, 3);
}

window.onCreatedRead = (msg) => {
  if (!window.timerChecking) return;
  window.timerChecking = false;
  V.status.hidden = true;
  V.drop.classList.remove("busy");
  if (msg.error) return checkFail(msg.error[0].toUpperCase() + msg.error.slice(1).replace(/\.?$/, "."));
  const tz = zone();
  const zoneShown = tz || TIME_ZONE;
  const target = wallToMs(T.time.value, tz);
  const createdMs = msg.createdUnix * 1000;
  const aimed = T.time.value.replace("T", " ") + (T.time.value.length === 16 ? ":00" : "");
  const diff = Math.round((createdMs - target) / 1000);       // whole seconds: late > 0, early < 0
  const shift = shiftMs();
  // a miss of whole quarter hours (plus a few seconds) is a time zone mismatch, not a late press
  const zoneMiss = Math.round(diff / 900) * 900;
  const rest = diff - zoneMiss;
  const facts = [`The game saved ${msg.created} (${msg.timeZone}); the timer is set to ${aimed} (${zoneShown}).`];
  let suggest;
  V.result.classList.toggle("hit", diff === 0);
  V.result.classList.toggle("miss", diff !== 0);
  if (diff === 0) {
    V.summary.textContent = `${msg.character}: created exactly on the timer's second.`;
    suggest = `Keep Shift at ${fmtShift(shift)} and Time zone at ${zoneShown}; for the next character, only set Time.`;
    facts.push("The press landed inside the target second, so the shift you used works. The save keeps only whole " +
      "seconds, so it cannot tell how close to the edge of the second it was.");
  } else if (zoneMiss !== 0 && Math.abs(rest) <= 30) {
    const n = Math.abs(diff);
    V.summary.textContent = `${msg.character}: created ${n.toLocaleString()} s too ${diff > 0 ? "late" : "early"}` +
      ` – that is the time zone, not your timing.`;
    const timerOffset = zoneOffsetMin(createdMs, tz);
    const gameOffset = timerOffset === null ? null : timerOffset - zoneMiss / 60;
    const names = gameOffset === null ? [] : zonesWithOffset(gameOffset, createdMs);
    const restShift = shift - rest * 1000;
    suggest = (gameOffset === null ? "Set Time zone to the game computer's zone" :
      `Set Time zone to ${names.length ? names.join(", ") + " or " : ""}${fmtOffset(gameOffset)}`) +
      (rest ? `, and Shift to about ${fmtShift(restShift)} (now ${fmtShift(shift)})` : `, and keep Shift at ${fmtShift(shift)}`) + ".";
    facts.push(`The miss is ${Math.abs(zoneMiss / 3600)} hour${Math.abs(zoneMiss) === 3600 ? "" : "s"}` +
      (rest ? ` and ${Math.abs(rest)} s` : "") + ". Whole hours (or quarter hours) mean the timer counted in a different " +
      "time zone than the game computer's clock: the game computer was on " +
      (gameOffset === null ? "another offset" : `UTC${fmtOffset(gameOffset)}`) + " at the time" +
      (timerOffset === null ? "." : `, the timer on UTC${fmtOffset(timerOffset)}.`) +
      (rest ? ` The ${Math.abs(rest)} s left over are your timing: the press came that much too ${rest > 0 ? "late" : "early"}.` : ""));
  } else if (Math.abs(diff) > 30) {
    V.summary.textContent = `${msg.character}: created ${Math.abs(diff).toLocaleString()} s too ${diff > 0 ? "late" : "early"}.`;
    suggest = "No timer setting fixes this: the miss is too large for a late or early press, and not a time zone difference.";
    facts.push("Check that the timer's Time is the time you aimed for and that this is the new character's file. If it " +
      "is, this computer's clock and the game computer's disagree: set both to the internet time, or run the timer on " +
      "the game computer.");
  } else {
    const n = Math.abs(diff), late = diff > 0;
    const suggested = Math.round((shift - diff * 1000) / 10) * 10;
    V.summary.textContent = `${msg.character}: created ${n} s too ${late ? "late" : "early"}.`;
    suggest = Math.abs(suggested) <= 5000
      ? `Set Shift to about ${fmtShift(suggested)} (now ${fmtShift(shift)}) and keep Time zone at ${zoneShown}.`
      : `Shift would need ${fmtShift(suggested)}, beyond the ±5000 ms it allows: set this computer's clock (or the ` +
        "game computer's) to the internet time instead, so the two agree.";
    facts.push(late
      ? `The press came between ${n} and ${n + 1} s after the start of the target second.`
      : `The press came between ${n - 1 || "0"} and ${n} s before the start of the target second.`);
    if (Math.abs(suggested) <= 5000) {
      facts.push(`That shift moves the beeps ${n * 1000} ms ${late ? "earlier" : "later"}, assuming ${fmtShift(shift)} was ` +
        "the shift when you pressed. The save keeps only whole seconds, so it is right to about ±500 ms: check it with " +
        "Test in 5 s.");
    } else {
      facts.push("A miss this large usually means the two computers' clocks disagree by that much, not a slow press.");
    }
  }
  facts.push("Nothing here changes the timer: set it yourself, then try again with a new character.");
  V.suggest.textContent = suggest;
  V.facts.replaceChildren(...facts.map((t) => el("li", "", t)));
  V.result.hidden = false;
};

function fmtShift(ms) { return `${ms > 0 ? "+" : ""}${ms} ms`; }

V.file.addEventListener("change", () => V.file.files[0] && check(V.file.files[0]));
V.drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); V.file.click(); } });
for (const ev of ["dragenter", "dragover"]) V.drop.addEventListener(ev, (e) => { e.preventDefault(); V.drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) V.drop.addEventListener(ev, (e) => { e.preventDefault(); V.drop.classList.remove("over"); });
V.drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) check(f); });
