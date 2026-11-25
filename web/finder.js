"use strict";

/* Upgrade name finder. Asks web/finder-worker.js (upgrade_oracle.py in Pyodide) for character names that give 8 upgrades
   in a row on an item, and the relay planner for a chain of characters that goes further. Nothing is uploaded and no
   save file is needed.

   The predictor, in its own tab, takes a dropped character file instead and asks the same worker what happens to every
   upgradable item in its inventory. The cost tool, in the last tab, uses the same worker too. */

const byId = (id) => document.getElementById(id);
const F = {
  form: byId("finderForm"), item: byId("fItem"), items: byId("fItems"), quality: byId("fQuality"), go: byId("fGo"), cancel: byId("fCancel"),
  status: byId("fStatus"), statusText: byId("fStatusText"), error: byId("fError"),
  result: byId("fResult"), summary: byId("fSummary"), names: byId("fNames"), more: byId("fMore"), note: byId("fNote"),
};

const P = {
  drop: byId("uDrop"), file: byId("uFile"), status: byId("uStatus"), statusText: byId("uStatusText"), error: byId("uError"),
  result: byId("uResult"), summary: byId("uSummary"), items: byId("uItems"),
  form: byId("uForm"), item: byId("uItem"), quality: byId("uQuality"), name: byId("uName"), go: byId("uGo"),
};

const R = {
  form: byId("rForm"), item: byId("rItem"), from: byId("rFrom"), to: byId("rTo"), go: byId("rGo"),
  status: byId("rStatus"), statusText: byId("rStatusText"), error: byId("rError"),
  result: byId("rResult"), summary: byId("rSummary"), plan: byId("rPlan"),
};

const C = {
  form: byId("cForm"), item: byId("cItem"), items: byId("cItems"), target: byId("cTarget"), name: byId("cName"),
  file: byId("cFile"), drop: byId("cDrop"), dropText: byId("cDropText"), dropHint: byId("cDropHint"),
  clearFile: byId("cClearFile"), go: byId("cGo"), status: byId("cStatus"), statusText: byId("cStatusText"), error: byId("cError"),
  result: byId("cResult"), summary: byId("cSummary"), facts: byId("cFacts"), rows: byId("cRows"), list: byId("cList"),
  copies: byId("cCopies"), hist: byId("cHist"), download: byId("cDownload"), listNote: byId("cListNote"),
};

const STEP = 5;      // names added by each "Find more"
let worker = null;
let itemsLoaded = false;
let found = [];      // the names listed so far: { name }
let asked = 0;       // how many names the last request asked for
let request = null;  // the settings of the current search, reused by "Find more"
let costing = false;    // the cost tool is working, so worker errors belong to it
let costItemsLoaded = false;
let relaying = false;   // a relay plan is being worked out, so worker errors belong to the planner
let predicting = false; // a dropped file is being read, so worker errors belong to the predictor

function startWorker() {
  worker = new Worker("web/finder-worker.js?v=__BUILD__");
  worker.onmessage = (e) => handle(e.data);
  worker.onerror = () => fail("Could not start the Python runtime.");
  return worker;
}

function busy(text) {
  F.status.hidden = !text;
  F.statusText.textContent = text || "";
  F.go.disabled = F.more.disabled = !!text;
  F.cancel.hidden = !text;
}

function fail(message) {
  if (costing) return costFail(message);
  if (relaying) return relayFail(message);
  if (predicting) return predictFail(message);
  busy("");
  F.error.textContent = message;
  F.error.hidden = false;
}

function handle(msg) {
  if (msg.type === "items") {
    itemsLoaded = true;
    F.items.replaceChildren(...msg.items.map((name) => Object.assign(document.createElement("option"), { value: name })));
    busy("");
    if (!predicting) P.status.hidden = true;
    if (!relaying) R.status.hidden = true;
  } else if (msg.type === "costItems") {
    costItemsLoaded = true;
    C.items.replaceChildren(...msg.items.map((name) => Object.assign(document.createElement("option"), { value: name })));
    if (!costing) C.status.hidden = true;
  } else if (msg.type === "costed") {
    costing = false;
    if (msg.error) return costFail(msg.error[0].toUpperCase() + msg.error.slice(1) + ".");
    showCost(msg);
  } else if (msg.type === "relayed") {
    relaying = false;
    if (msg.error) return relayFail(msg.error[0].toUpperCase() + msg.error.slice(1) + ".");
    showRelay(msg);
  } else if (msg.type === "predicted" || msg.type === "predictedItem") {
    predicting = false;
    if (msg.error) return predictFail(msg.error[0].toUpperCase() + msg.error.slice(1) + ".");
    if (msg.type === "predicted") showPrediction(msg);
    else showPrediction({ character: msg.character, typedAs: msg.typedAs, items: [msg.item], manual: true });
  } else if (msg.type === "error" || msg.error) {
    fail(msg.error || msg.message);
  } else if (msg.type === "result") {
    busy("");
    found = found.concat(msg.names.map((n) => (typeof n === "string" ? { name: n } : n)));
    showResult(msg, msg.names.length < asked);
  }
}

// ---------- the upgrade path of one name ----------

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function renderPath(path) {
  const box = el("div", "pathBox");
  for (const copy of path) {
    const head = copy.role === "predict"
      ? `If you keep upgrading: ${copy.upgrades} upgrade${copy.upgrades === 1 ? "" : "s"}, then it breaks`
      : `Upgrade path: ${copy.upgrades} upgrade${copy.upgrades === 1 ? "" : "s"}, then stop`;
    const line = el("div", "pathLine");
    line.append(el("span", "st start", String(copy.from)));
    for (const s of copy.steps) {
      const ok = s.outcome === "success";
      const step = el("span", "st " + (ok ? "ok" : "bad"), `→ ${s.to} ${ok ? "✓" : "✗"}`);
      step.title = `roll ${s.roll.toFixed(3)}: ${ok ? "upgrade works" : "the item breaks"}` +
        (copy.role === "predict" ? (s.savedSeed ? " (seed saved in the file)" : " (seed from the character name)") : "");
      line.append(step);
    }
    const end = copy.role === "keep"
      ? `Stop at quality ${copy.from + copy.upgrades}.`
      : `It breaks going to quality ${copy.breaksAt}.`;
    box.append(el("div", "pathHead", head), line, el("div", "pathEnd", end));
  }
  return box;
}

// ---------- results ----------

function showResult(r, over) {
  F.result.hidden = false;
  F.summary.textContent = `${r.item}, starting at quality ${r.from}: names that give exactly ${r.upgrades} upgrades before it breaks`;
  F.names.replaceChildren(...found.map(({ name }) => {
    const li = el("li");
    const top = el("div", "nameRow");
    const code = el("code", "", name);
    const copy = el("button", "", "Copy");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(name); copy.textContent = "Copied"; } catch { copy.textContent = "Select it by hand"; }
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    top.append(code, copy);
    li.append(top);
    return li;
  }));
  F.more.hidden = over;                        // fewer than asked for: the search is over
  F.note.textContent = found.length === 0
    ? "No name found in the search range."
    : over ? "That is every name the search could find." : `${r.tried.toLocaleString()} names tried this time.`;
}

function search(more) {
  F.error.hidden = true;
  if (!more) {
    const item = F.item.value.trim();
    if (!item) return fail("Enter the name of an item.");
    found = [];
    request = { type: "find", item, quality: F.quality.value };
  }
  asked = STEP;
  busy(itemsLoaded ? "Searching names…" : "Starting the Python runtime (about 10 MB, cached after the first visit), then searching…");
  (worker || startWorker()).postMessage({ ...request, limit: STEP, after: more && found.length ? found[found.length - 1].name : "" });
}

F.form.addEventListener("submit", (e) => { e.preventDefault(); search(false); });
F.more.addEventListener("click", () => search(true));
F.cancel.addEventListener("click", () => {
  if (worker) { worker.terminate(); worker = null; itemsLoaded = false; }
  busy("");
});

// load the item list the first time the box is used, so the page does not fetch the runtime for visitors who only analyse a file
F.item.addEventListener("focus", () => {
  if (itemsLoaded || worker) return;
  busy("Loading the item list…");
  startWorker().postMessage({ type: "items" });
}, { once: true });

// ---------- the predictor: a dropped character file ----------

function predictFail(message) {
  predicting = false;
  P.status.hidden = true;
  P.drop.classList.remove("busy");
  P.go.disabled = false;
  P.error.textContent = message;
  P.error.hidden = false;
}

async function predict(file) {
  P.error.hidden = true;
  P.result.hidden = true;
  P.drop.classList.add("busy");
  P.status.hidden = false;
  P.statusText.textContent = worker ? "Reading the file…" : "Starting the Python runtime (about 10 MB, cached after the first visit)…";
  try {
    const bytes = await file.arrayBuffer();
    predicting = true;
    (worker || startWorker()).postMessage({ type: "predict", bytes }, [bytes]);
  } catch (e) {
    predictFail("Could not read that file.");
  }
  P.file.value = "";
}

function predictItem() {
  P.error.hidden = true;
  const item = P.item.value.trim();
  const name = P.name.value;                   // not trimmed: the name is used exactly as typed
  if (!item) return predictFail("Enter the name of an item.");
  if (!name) return predictFail("Enter a character name.");
  P.result.hidden = true;
  P.go.disabled = true;
  P.status.hidden = false;
  P.statusText.textContent = worker ? "Predicting…" : "Starting the Python runtime (about 10 MB, cached after the first visit)…";
  predicting = true;
  (worker || startWorker()).postMessage({ type: "predictItem", item, quality: P.quality.value, name });
}

// the game's name box changes some names as they are typed or pasted (upgrade_oracle.as_typed): say so
function typedNote(r) {
  return r.typedAs != null && r.typedAs !== r.character
    ? `. Careful: the game's name box saves “${r.character}” as “${r.typedAs}”, which rolls differently` : "";
}

function showPrediction(r) {
  P.status.hidden = true;
  P.drop.classList.remove("busy");
  P.go.disabled = false;
  P.result.hidden = false;
  P.summary.textContent = r.manual
    ? `As a new character named “${r.character}” (no saved seeds)` + typedNote(r)
    : `${r.character}: ${r.items.length} upgradable item${r.items.length === 1 ? "" : "s"} in the inventory` +
      ` · ${r.savedSeeds} saved upgrade seed${r.savedSeeds === 1 ? "" : "s"}`;
  P.items.replaceChildren(...(r.items.length ? r.items.map((it) => {
    const li = el("li");
    const row = el("div", "predRow");
    row.append(
      el("strong", "", it.name + (it.stack > 1 ? ` ×${it.stack}` : "") + (it.equipped ? " (equipped)" : "")),
      el("span", "what", it.broke
        ? `quality ${it.from}: ${it.upgrades} upgrade${it.upgrades === 1 ? "" : "s"}, then it breaks going to ${it.breaksAt}`
        : `quality ${it.from}: survives ${it.attempts} attempts`));
    const d = el("details", "path");
    d.append(el("summary", "", "Upgrade path"), renderPath([{ ...it, role: "predict", copy: 1 }]));
    li.append(row, d);
    return li;
  }) : [el("li", "", "No upgradable items in this character's inventory.")]));
}

P.form.addEventListener("submit", (e) => { e.preventDefault(); predictItem(); });
// the item box shares the finder's item list; load it the first time either box is used
P.item.addEventListener("focus", () => {
  if (itemsLoaded || worker) return;
  P.status.hidden = false;
  P.statusText.textContent = "Loading the item list…";
  startWorker().postMessage({ type: "items" });
}, { once: true });
P.file.addEventListener("change", () => P.file.files[0] && predict(P.file.files[0]));
P.drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); P.file.click(); } });
for (const ev of ["dragenter", "dragover"]) P.drop.addEventListener(ev, (e) => { e.preventDefault(); P.drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) P.drop.addEventListener(ev, (e) => { e.preventDefault(); P.drop.classList.remove("over"); });
P.drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) predict(f); });

// ---------- the relay planner ----------

function relayFail(message) {
  relaying = false;
  R.status.hidden = true;
  R.go.disabled = false;
  R.error.textContent = message;
  R.error.hidden = false;
}

function plan() {
  R.error.hidden = true;
  const item = R.item.value.trim();
  if (!item) return relayFail("Enter the name of an item.");
  R.result.hidden = true;
  R.go.disabled = true;
  R.status.hidden = false;
  R.statusText.textContent = (worker ? "Finding characters…" : "Starting the Python runtime (about 10 MB, cached after the first visit), then finding characters…") +
    " Each hand-over takes a few seconds.";
  relaying = true;
  (worker || startWorker()).postMessage({ type: "relay", item, from: R.from.value, to: R.to.value });
}

function showRelay(r) {
  R.status.hidden = true;
  R.go.disabled = false;
  R.result.hidden = false;
  R.summary.textContent = `${r.item}, quality ${r.from} to ${r.to}: ${r.plan.length} character${r.plan.length === 1 ? "" : "s"}, in this order`;
  R.plan.replaceChildren(...r.plan.map((seg, i) => {
    const li = el("li");
    const row = el("div", "predRow");
    const name = el("strong");
    name.append(el("code", "", seg.name));
    const copy = el("button", "", "Copy");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(seg.name); copy.textContent = "Copied"; } catch { copy.textContent = "Select it by hand"; }
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    const n = seg.to - seg.from;
    const last = i === r.plan.length - 1;
    row.append(name, el("span", "what", `quality ${seg.from} → ${seg.to} (${n} upgrade${n === 1 ? "" : "s"})` +
      (last ? ", then stop" : ", then put the item in a chest for the next character")), copy);
    const d = el("details", "path");
    d.append(el("summary", "", "Upgrade path"),
      renderPath([{ copy: i + 1, role: "keep", from: seg.from, upgrades: n, steps: seg.steps }]));
    li.append(row, d);
    return li;
  }));
}

R.form.addEventListener("submit", (e) => { e.preventDefault(); plan(); });
R.item.addEventListener("focus", () => {
  if (itemsLoaded || worker) return;
  R.status.hidden = false;
  R.statusText.textContent = "Loading the item list…";
  startWorker().postMessage({ type: "items" });
}, { once: true });

// ---------- the upgrade cost tool ----------

function costFail(message) {
  costing = false;
  C.status.hidden = true;
  C.go.disabled = false;
  C.error.textContent = message;
  C.error.hidden = false;
}

async function calculate() {
  C.error.hidden = true;
  const item = C.item.value.trim();
  const file = costFile;
  const name = C.name.value;                   // not trimmed: the name is used exactly as typed
  if (!item) return costFail("Enter the name of an item.");
  if (!file && !name) return costFail("Enter a character name or choose its character file.");
  C.result.hidden = true;
  C.go.disabled = true;
  C.status.hidden = false;
  C.statusText.textContent = (worker ? "Calculating…" : "Starting the Python runtime (about 10 MB, cached after the first visit)…") +
    " High targets can take a while: every copy is replayed.";
  costing = true;
  const msg = { type: "cost", item, target: C.target.value, name };
  try {
    if (file) msg.bytes = await file.arrayBuffer();
  } catch (e) {
    return costFail("Could not read that file.");
  }
  (worker || startWorker()).postMessage(msg, msg.bytes ? [msg.bytes] : []);
}

function showCost(r) {
  C.status.hidden = true;
  C.go.disabled = false;
  C.result.hidden = false;
  const who = r.source === "file" ? `${r.character} (from the file, ${r.savedSeeds} saved seed${r.savedSeeds === 1 ? "" : "s"})`
    : `a new character named “${r.character}”` + typedNote(r);
  const breaks = r.copies - (r.reached ? 1 : 0);
  C.summary.textContent = r.target <= r.cap
    ? `${r.item} to quality ${r.target} by ${who}: no Forge needed, the station gets it there.`
    : `${r.item} to quality ${r.target} by ${who}: ${r.copies.toLocaleString()} cop${r.copies === 1 ? "y" : "ies"}, ` +
      `${r.attempts.toLocaleString()} Forge attempt${r.attempts === 1 ? "" : "s"}, ${breaks.toLocaleString()} break${breaks === 1 ? "" : "s"}.`;
  const facts = [];
  const where = r.station || "no station";
  const made = r.via
    ? `Crafted as ${r.via.cast} at ${where}, then cooked in the ${r.via.foundry} with ${r.via.perCast} ${r.via.fuel} per cast`
    : `Crafted at ${where}`;
  facts.push(`${made}; each copy is upgraded at ${where} to quality ${Math.min(r.cap, r.target)}` +
    (r.cap < r.maxQuality ? `, as far as ${where} goes (it reaches level ${r.stationMaxLevel}).` : "."));
  for (const g of r.gear || []) facts.push(`Each copy also takes a new ${g.name}, counted as what it takes to craft: ` +
    g.parts.map((p) => `${p.amount} ${p.name}`).join(", ") + ".");
  if (r.notRefunded && r.notRefunded.length) facts.push(`Its upgrade recipe leaves out the ${r.notRefunded.join(", ")} that ` +
    "the craft takes, so a break never refunds it. That looks like a game bug.");
  if (r.neverRefunded && r.neverRefunded.length) facts.push(`Never refunded on a break: ${r.neverRefunded.join(", ")}.`);
  if (r.season) facts.push(`Its recipe is seasonal: only available during ${r.season}.`);
  if (!r.reached) facts.push(`Not reached: still breaking after ${r.copies.toLocaleString()} copies, where the page stops. ` +
    "The totals are for those copies; the command-line version can go further.");
  C.facts.replaceChildren(...facts.map((t) => el("li", "", t)));
  C.rows.replaceChildren(...r.rows.map((row) => {
    const tr = el("tr", row.idol ? "idol" : "");
    for (const v of [row.name, row.spent, row.refunded, row.net]) tr.append(el("td", "", typeof v === "number" ? v.toLocaleString() : v));
    return tr;
  }));
  showCopies(r);
}

const LIST_SHOWN = 5000;   // lines shown on the page; the download always has every copy
let copyText = "";         // the full list, for the download button
let copyFile = "";

function copyLine(steps, i, start) {
  return `copy ${i + 1}: ${start} → ` + [...steps].map((ok, k) => `${start + k + 1}${ok === "1" ? "✓" : "✗"}`).join(" ");
}

function showCopies(r) {
  const start = Math.min(r.cap, r.target);
  C.copies.hidden = r.target <= r.cap;        // no Forge attempts, nothing to list
  if (C.copies.hidden) return;
  // how far the copies got: the quality each one reached before it broke (or the target, for the last one)
  const reached = new Map();
  for (const steps of r.list) {
    const q = start + steps.split("").filter((c) => c === "1").length;
    reached.set(q, (reached.get(q) || 0) + 1);
  }
  C.hist.replaceChildren(...[...reached.keys()].sort((a, b) => a - b).map((q) => {
    const tr = el("tr");
    tr.append(el("td", "", q === start ? `${q} (broke on its first attempt)` : q === r.target && r.reached ? `${q} (the one that made it)` : String(q)),
      el("td", "", reached.get(q).toLocaleString()));
    return tr;
  }));
  const lines = r.list.map((steps, i) => copyLine(steps, i, start));
  copyText = `${r.item} to quality ${r.target}, upgraded by ${r.character}: ${r.copies} copies, ${r.attempts} Forge attempts\n` +
    lines.join("\n") + "\n";
  copyFile = `${r.item} to ${r.target} - ${r.character}.txt`.replace(/[\\/:*?"<>|]/g, "_");
  C.list.textContent = lines.slice(0, LIST_SHOWN).join("\n");
  C.listNote.textContent = lines.length > LIST_SHOWN
    ? `Showing the first ${LIST_SHOWN.toLocaleString()} of ${lines.length.toLocaleString()} copies; the download has all of them.`
    : `${lines.length.toLocaleString()} cop${lines.length === 1 ? "y" : "ies"}.`;
}

C.download.addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([copyText], { type: "text/plain;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: copyFile || "copies.txt" });
  a.click();
  URL.revokeObjectURL(url);
});

C.form.addEventListener("submit", (e) => { e.preventDefault(); calculate(); });
C.item.addEventListener("focus", () => {
  if (costItemsLoaded) return;
  C.status.hidden = false;
  C.statusText.textContent = "Loading the item list…";
  (worker || startWorker()).postMessage({ type: "costItems" });
}, { once: true });

// the cost tool's character file: dropped or chosen in the small drop area, used instead of the typed name
let costFile = null;

function chooseCostFile(file) {
  costFile = file || null;
  C.file.value = "";
  C.drop.classList.toggle("chosen", !!costFile);
  C.clearFile.hidden = !costFile;
  C.name.disabled = !!costFile;
  C.dropText.textContent = costFile ? `Using ${costFile.name}` : "";
  if (!costFile) C.dropText.append("Or drop the character's ", el("code", "", ".fch"), " file here");
  C.dropHint.textContent = costFile ? "its name and saved rolls are used; drop or click to choose another file"
    : "or click to choose one; its name and saved rolls are used instead of the name above";
}

C.file.addEventListener("change", () => C.file.files[0] && chooseCostFile(C.file.files[0]));
C.clearFile.addEventListener("click", () => chooseCostFile(null));
C.drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); C.file.click(); } });
for (const ev of ["dragenter", "dragover"]) C.drop.addEventListener(ev, (e) => { e.preventDefault(); C.drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) C.drop.addEventListener(ev, (e) => { e.preventDefault(); C.drop.classList.remove("over"); });
C.drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) chooseCostFile(f); });
