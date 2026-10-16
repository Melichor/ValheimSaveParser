"use strict";

/* Upgrade name finder. Asks web/finder-worker.js (upgrade_oracle.py in Pyodide) for character names that give 8 upgrades
   on an item. Nothing is uploaded and no save file is needed. */

const F = {
  form: document.getElementById("finderForm"), item: document.getElementById("fItem"), items: document.getElementById("fItems"),
  quality: document.getElementById("fQuality"), go: document.getElementById("fGo"), cancel: document.getElementById("fCancel"),
  status: document.getElementById("fStatus"), statusText: document.getElementById("fStatusText"), error: document.getElementById("fError"),
  result: document.getElementById("fResult"), summary: document.getElementById("fSummary"), names: document.getElementById("fNames"),
  more: document.getElementById("fMore"), note: document.getElementById("fNote"),
};

const STEP = 5;      // names added by each "Find more"
let worker = null;
let itemsLoaded = false;
let found = [];      // the names listed so far
let asked = 0;       // how many names were asked for in the last request

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
  busy("");
  F.error.textContent = message;
  F.error.hidden = false;
}

function handle(msg) {
  if (msg.type === "items") {
    itemsLoaded = true;
    F.items.replaceChildren(...msg.items.map((name) => Object.assign(document.createElement("option"), { value: name })));
    busy("");
  } else if (msg.type === "error" || msg.error) {
    fail(msg.error || msg.message);
  } else if (msg.type === "result") {
    busy("");
    found = found.concat(msg.names);
    showResult(msg, msg.names.length < asked);
  }
}

function showResult(r, over) {
  F.result.hidden = false;
  F.summary.textContent = `${r.item}, starting at quality ${r.from}: names that give exactly ${r.upgrades} upgrades before it breaks`;
  F.names.replaceChildren(...found.map((name) => {
    const li = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = name;
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(name); copy.textContent = "Copied"; } catch { copy.textContent = "Select it by hand"; }
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    li.append(code, copy);
    return li;
  }));
  F.more.hidden = over;                        // fewer than asked for: the search is over
  F.note.textContent = found.length === 0
    ? "No name found in the search range."
    : over ? "That is every name the search could find." : `${r.tried.toLocaleString()} names tried this time.`;
}

function search(more) {
  F.error.hidden = true;
  const item = F.item.value.trim();
  if (!item) return fail("Enter the name of an item.");
  if (!more) found = [];
  asked = STEP;
  busy(itemsLoaded ? "Searching names…" : "Starting the Python runtime (about 10 MB, cached after the first visit), then searching…");
  (worker || startWorker()).postMessage({ type: "find", item, quality: F.quality.value, limit: STEP, after: found[found.length - 1] || "" });
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
