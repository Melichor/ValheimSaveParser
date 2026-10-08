"use strict";

/* Valheim Achievement Hunter web page.
   The analysis is done by achi_hunter.py itself, run in the browser with Pyodide (Python compiled to WebAssembly).
   This file only loads the runtime, hands it the uploaded file and draws the JSON that the script returns. */

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";

const $ = (id) => document.getElementById(id);
const els = {
  drop: $("drop"), file: $("file"), status: $("status"), statusText: $("statusText"), error: $("error"),
  intro: $("intro"), results: $("results"), fname: $("fname"), worlds: $("worlds"), cards: $("cards"),
  biome: $("biome"), search: $("search"), showDone: $("showDone"), hideDone: $("hideDone"), reset: $("reset"), download: $("download"),
};

// ---------- Python runtime ----------

let runtime = null; // Promise of the imported achi_hunter module

function loadScript() {
  if (!runtime) {
    runtime = (async () => {
      const [py, source] = await Promise.all([
        loadPyodide({ indexURL: PYODIDE_URL }),
        fetch("achi_hunter.py").then((r) => {
          if (!r.ok) throw new Error("Could not load achi_hunter.py");
          return r.text();
        }),
      ]);
      py.FS.writeFile("achi_hunter.py", source);
      return py.pyimport("achi_hunter");
    })();
    runtime.catch(() => { runtime = null; }); // allow a retry on the next upload
  }
  return runtime;
}

// ---------- UI ----------

let report = null; // JSON returned by achi_hunter.analyze_json
let model = [];    // one entry per list: { section, card, head, body }

function setStatus(text) {
  els.status.hidden = !text;
  els.statusText.textContent = text || "";
}

function showError(msg) {
  els.error.textContent = msg;
  els.error.hidden = !msg;
}

async function analyse(file) {
  showError("");
  els.drop.classList.add("busy");
  setStatus("Starting the Python runtime (about 10 MB, cached after the first visit)…");
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const mod = await loadScript();
    setStatus("Running achi_hunter.py…");
    const out = JSON.parse(mod.analyze_json(bytes));
    if (out.error) throw new Error(out.error[0].toUpperCase() + out.error.slice(1) + ".");
    report = out;
    render(file.name);
  } catch (e) {
    showError(e.message || "Something went wrong while analysing that file.");
  } finally {
    setStatus("");
    els.drop.classList.remove("busy");
    els.file.value = "";
  }
}

function render(name) {
  els.fname.textContent = name;
  els.worlds.textContent = "Worlds: " + (report.worlds.join(", ") || "none");
  els.biome.replaceChildren(...report.biomes.map((b) => new Option(b, b)));
  els.biome.value = report.biomes[report.biomes.length - 1];   // default: the last biome, so nothing is hidden
  els.cards.replaceChildren();
  model = report.sections.map((section) => {
    const entry = { section, ...buildCard(section) };
    els.cards.append(entry.card);
    return entry;
  });
  els.intro.hidden = true;
  els.results.hidden = false;
  update();
}

function buildCard(section) {
  const card = document.createElement("article");
  card.className = "card";

  const head = document.createElement("button");
  head.type = "button";
  head.className = "head";
  head.setAttribute("aria-expanded", "false");
  head.innerHTML = `<div class="row"><span class="title"></span><span class="count"></span></div>
    <div class="hint"></div><div class="meter"><i></i></div>`;
  head.querySelector(".title").textContent = section.title;

  const body = document.createElement("div");
  body.className = "body";
  body.hidden = true;
  card.append(head, body);
  head.addEventListener("click", () => {
    const open = body.hidden;
    body.hidden = !open;
    head.setAttribute("aria-expanded", String(open));
  });
  return { card, head, body };
}

// Entries with no biome (ways to die, ...) are always shown. Otherwise an entry is shown when its biome is the
// selected one or an earlier one in the progression order.
function inReach(e) {
  const limit = report.biomes.indexOf(els.biome.value);
  const at = report.biomes.indexOf(e.biome);
  return !e.biome || at < 0 || at <= limit;
}

function fillBody(entry, query) {
  const { section, body } = entry;
  // earliest biome first, so the next things to do come on top; entries without a biome go last
  const rank = (e) => { const i = report.biomes.indexOf(e.biome); return i < 0 ? 99 : i; };
  const pool = section.entries.filter(inReach).sort((x, y) => rank(x) - rank(y) || x.name.localeCompare(y.name));
  const match = (e) => !query || e.name.toLowerCase().includes(query) || e.token.toLowerCase().includes(query);
  const todo = pool.filter((e) => e.count === 0 && match(e));
  const done = pool.filter((e) => e.count > 0 && match(e));
  body.replaceChildren();

  const add = (heading, list, cls) => {
    if (!list.length) return;
    const h = document.createElement("h3");
    h.textContent = `${heading} (${list.length})`;
    const ul = document.createElement("ul");
    for (const e of list) {
      const li = document.createElement("li");
      li.className = cls;
      const l = document.createElement("span");
      l.className = "l";
      l.textContent = e.name;
      li.append(l);
      if (e.biome) {
        const b = document.createElement("span");
        b.className = "b";
        b.textContent = e.biome;
        li.append(b);
      }
      if (cls === "done") {
        const n = document.createElement("span");
        n.className = "n";
        n.textContent = "×" + e.count;
        li.append(n);
      }
      ul.append(li);
    }
    body.append(h, ul);
  };
  add("Missing", todo, "todo");
  if (els.showDone.checked) add("Completed", done, "done");
  if (!body.children.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = query ? "Nothing matches." : `Nothing missing up to ${els.biome.value}.`;
    body.append(p);
  }
  return todo.length + (els.showDone.checked ? done.length : 0);
}

function updateHeader(entry) {
  const pool = entry.section.entries.filter(inReach);
  const done = pool.filter((e) => e.count > 0).length;
  const later = entry.section.entries.length - pool.length;
  const head = entry.head;
  head.querySelector(".count").textContent = `${done} / ${pool.length}`;
  head.querySelector(".hint").textContent = entry.section.hint + (later ? ` · ${later} more in later biomes` : "");
  head.querySelector(".meter i").style.width = (pool.length ? (100 * done) / pool.length : 0) + "%";
  entry.card.classList.toggle("complete", pool.length > 0 && done === pool.length);
  return { total: pool.length, done };
}

function update() {
  const query = els.search.value.trim().toLowerCase();
  for (const entry of model) {
    const { total, done } = updateHeader(entry);
    const shown = fillBody(entry, query);
    const finished = total > 0 && done === total;
    entry.card.hidden = total === 0 || (els.hideDone.checked && finished) || (query !== "" && shown === 0);
    if (query) { // searching opens the lists that have matches
      entry.body.hidden = shown === 0;
      entry.head.setAttribute("aria-expanded", String(shown > 0));
    }
  }
}

els.biome.addEventListener("change", update);
els.search.addEventListener("input", update);
els.showDone.addEventListener("change", update);
els.hideDone.addEventListener("change", update);
els.file.addEventListener("change", () => els.file.files[0] && analyse(els.file.files[0]));
els.reset.addEventListener("click", () => {
  els.results.hidden = true;
  els.intro.hidden = false;
  showError("");
});
els.download.addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: "valheim-achievements.json" });
  a.click();
  URL.revokeObjectURL(url);
});
els.drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); els.file.click(); } });
for (const ev of ["dragenter", "dragover"]) els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.remove("over"); });
els.drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) analyse(f); });

// start downloading the runtime right away so the first upload is quick
window.addEventListener("load", () => { loadScript().catch(() => {}); });
