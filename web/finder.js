"use strict";

/* Upgrade name finder. Asks web/finder-worker.js (upgrade_oracle.py in Pyodide) for character names that give upgrades on
   an item. The default mode asks for 8 upgrades on one copy; advanced mode takes the wanted upgrades and the number of
   copies, and shows an upgrade path for every name. Nothing is uploaded and no save file is needed.

   The predictor at the bottom of the page takes a dropped character file instead and asks the same worker what happens
   to every upgradable item in its inventory. */

const byId = (id) => document.getElementById(id);
const F = {
  form: byId("finderForm"), item: byId("fItem"), items: byId("fItems"), quality: byId("fQuality"), go: byId("fGo"), cancel: byId("fCancel"),
  advanced: byId("fAdvanced"), adv: byId("fAdv"), upgrades: byId("fUpgrades"), copies: byId("fCopies"),
  status: byId("fStatus"), statusText: byId("fStatusText"), error: byId("fError"),
  result: byId("fResult"), summary: byId("fSummary"), names: byId("fNames"), more: byId("fMore"), note: byId("fNote"),
};

const P = {
  drop: byId("uDrop"), file: byId("uFile"), status: byId("uStatus"), statusText: byId("uStatusText"), error: byId("uError"),
  result: byId("uResult"), summary: byId("uSummary"), items: byId("uItems"),
  form: byId("uForm"), item: byId("uItem"), quality: byId("uQuality"), name: byId("uName"), go: byId("uGo"),
};

const STEP = 5;      // names added by each "Find more"
let worker = null;
let itemsLoaded = false;
let found = [];      // the names listed so far: { name, path? }
let asked = 0;       // how many names the last request asked for
let request = null;  // the settings of the current search, reused by "Find more"
let predicting = false; // a dropped file is being read, so worker errors belong to the predictor

function startWorker() {
  worker = new Worker("web/finder-worker.js");
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
  } else if (msg.type === "predicted" || msg.type === "predictedItem") {
    predicting = false;
    if (msg.error) return predictFail(msg.error[0].toUpperCase() + msg.error.slice(1) + ".");
    if (msg.type === "predicted") showPrediction(msg);
    else showPrediction({ character: msg.character, items: [msg.item], manual: true });
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
      : path.length === 1
      ? `Upgrade path: ${copy.upgrades} upgrade${copy.upgrades === 1 ? "" : "s"}, then stop`
      : copy.role === "keep"
        ? `Copy ${copy.copy}, the one you keep: ${copy.upgrades} upgrade${copy.upgrades === 1 ? "" : "s"}, then stop`
        : `Copy ${copy.copy}, a sacrifice: upgrade it until it breaks`;
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
  F.summary.textContent = r.copies
    ? `${r.item}, starting at quality ${r.from}: names that give ${r.upgrades} upgrade${r.upgrades === 1 ? "" : "s"} on the copy you keep` +
      (r.copies > 1 ? `, after ${r.copies - 1} other cop${r.copies === 2 ? "y" : "ies"} upgraded until ${r.copies === 2 ? "it breaks" : "they break"}` : "")
    : `${r.item}, starting at quality ${r.from}: names that give exactly ${r.upgrades} upgrades before it breaks`;
  const withPaths = found.some((n) => n.path);
  F.names.classList.toggle("paths", withPaths);
  F.names.replaceChildren(...found.map(({ name, path }) => {
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
    if (path) {
      const d = el("details", "path");
      d.append(el("summary", "", "Upgrade path"), renderPath(path));
      li.append(d);
    }
    return li;
  }));
  F.more.hidden = over;                        // fewer than asked for: the search is over
  F.note.textContent = found.length === 0
    ? "No name found in the search range. Try fewer upgrades or more copies."
    : over ? "That is every name the search could find." : `${r.tried.toLocaleString()} names tried this time.`;
}

function search(more) {
  F.error.hidden = true;
  if (!more) {
    const item = F.item.value.trim();
    if (!item) return fail("Enter the name of an item.");
    found = [];
    request = F.advanced.checked
      ? { type: "findAdvanced", item, quality: F.quality.value, upgrades: F.upgrades.value, copies: F.copies.value }
      : { type: "find", item, quality: F.quality.value };
  }
  asked = STEP;
  const slow = request.type === "findAdvanced" ? " Rare combinations can take a few minutes." : "";
  busy((itemsLoaded ? "Searching names…" : "Starting the Python runtime (about 10 MB, cached after the first visit), then searching…") + slow);
  (worker || startWorker()).postMessage({ ...request, limit: STEP, after: more && found.length ? found[found.length - 1].name : "" });
}

F.form.addEventListener("submit", (e) => { e.preventDefault(); search(false); });
F.more.addEventListener("click", () => search(true));
F.cancel.addEventListener("click", () => {
  if (worker) { worker.terminate(); worker = null; itemsLoaded = false; }
  busy("");
});
F.advanced.addEventListener("change", () => { F.adv.hidden = !F.advanced.checked; });

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

function showPrediction(r) {
  P.status.hidden = true;
  P.drop.classList.remove("busy");
  P.go.disabled = false;
  P.result.hidden = false;
  P.summary.textContent = r.manual
    ? `As a new character named “${r.character}” (no saved seeds)`
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
