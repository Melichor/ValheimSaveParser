"use strict";

/* The Drop counters tab. Asks web/drops-worker.js (drop_counters.py in Pyodide) how far a character is from each rare
   creature drop: every counter saved in a chosen character file, or the drops a filter picks, with or without a file.
   The file is read in the browser and never uploaded.

   Everything is inside this function: the page's scripts share one global scope, and finder.js already has a worker,
   a busy() and a fail() of its own. */
(() => {
  const byId = (id) => document.getElementById(id);
  const D = {
    form: byId("dForm"), drop: byId("dDrop"), file: byId("dFile"), dropText: byId("dDropText"), dropHint: byId("dDropHint"),
    filter: byId("dFilter"), go: byId("dGo"), clear: byId("dClearFile"), status: byId("dStatus"), statusText: byId("dStatusText"),
    error: byId("dError"), result: byId("dResult"), summary: byId("dSummary"), sort: byId("dSort"), note: byId("dNote"),
    head: byId("dHead"), rows: byId("dRows"),
  };
  const SHARED_SHOWN = 3;      // creatures named in the "shared with" cell before a "+N more" button

  let worker = null;
  let fileBytes = null;        // the chosen character file, kept to answer every new filter
  let answer = null;           // the last answer, drawn again when the sort changes

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function startWorker() {
    worker = new Worker("web/drops-worker.js?v=e607e5d");
    worker.onmessage = (e) => show(e.data);
    worker.onerror = () => fail("Could not start the Python runtime.");
    return worker;
  }

  function busy(text) {
    D.status.hidden = !text;
    D.statusText.textContent = text || "";
    D.go.disabled = !!text;
    D.drop.classList.toggle("busy", !!text);
  }

  function fail(message) {
    busy("");
    D.result.hidden = true;                   // the last table belongs to an earlier file or filter
    D.error.textContent = message;
    D.error.hidden = false;
  }

  function ask() {
    D.error.hidden = true;
    const filters = D.filter.value.trim();
    if (!filters && !fileBytes) return fail("Choose a character file, enter a filter, or both.");
    busy(worker ? "Reading the counters…" : "Starting the Python runtime (about 10 MB, cached after the first visit)…");
    const msg = { type: "drops", filters };
    if (fileBytes) msg.bytes = fileBytes.slice(0);   // a copy: the worker takes it over, and the next filter needs the file again
    (worker || startWorker()).postMessage(msg, msg.bytes ? [msg.bytes] : []);
  }

  function show(msg) {
    busy("");
    if (msg.type === "error" || msg.error) {
      const text = msg.error || msg.message;
      return fail(text[0].toUpperCase() + text.slice(1) + (/[.!?]$/.test(text) ? "" : "."));
    }
    answer = msg;
    draw();
  }

  // ---------- the table ----------

  const percent = (p) => (p * 100).toFixed(2).replace(/\.?0+$/, "") + "%";
  const kills = (n) => `${n} kill${n === 1 ? "" : "s"}`;

  // every row is a drop with a counter (30% or less): the script leaves out the ones every kill rolls for anew
  function nextCell(r) {
    if (r.next === null || r.next === undefined) {
      const td = el("td", "next quiet", "not started");
      td.append(el("span", "within", `within ${kills(r.within)}`));
      return td;
    }
    return el("td", "next" + (r.next === 1 ? " soon" : ""), r.next === 1 ? "next kill" : `in ${kills(r.next)}`);
  }

  function sharedCell(names) {
    const td = el("td", "shared");
    if (!names || !names.length) return td;
    if (names.length <= SHARED_SHOWN) {
      td.textContent = names.join(", ");
      return td;
    }
    td.textContent = names.slice(0, SHARED_SHOWN).join(", ") + ", ";
    const more = el("button", "more", `+${names.length - SHARED_SHOWN} more`);
    more.type = "button";
    more.addEventListener("click", () => { td.textContent = names.join(", "); });
    td.append(more);
    return td;
  }

  // soonest first: by the kills left, then the counters not started yet, by how soon their first drop can come at the latest
  function soonest(a, b) {
    const rank = (r) => (r.next != null ? r.next : 1000 + r.within);
    return rank(a) - rank(b);
  }

  function draw() {
    const r = answer;
    const withFile = r.character !== null;
    D.result.hidden = false;
    const matched = r.rows.length === 1 ? "1 drop matches" : `${r.rows.length} drops match`;
    D.summary.textContent = !withFile ? `${matched}. Choose the character's file to see how far it is from each.`
      : r.filtered ? `${r.character}: ${matched} · ${r.saved} counter${r.saved === 1 ? "" : "s"} saved`
      : `${r.character}: ${r.saved} drop counter${r.saved === 1 ? "" : "s"} saved` +
        (r.saved ? "" : ". None yet: it has not killed anything with a rare drop since Valheim 1.0.20, or not saved since");
    const notes = [];
    for (const why of r.unmatched) notes.push(why[0].toUpperCase() + why.slice(1) + ".");   // "no drop matches …", or a star level it never has
    if (r.rolled) notes.push(`${r.rolled} drop${r.rolled === 1 ? "" : "s"} above 30% ${r.rolled === 1 ? "is" : "are"} not shown: ` +
      `every kill rolls for ${r.rolled === 1 ? "it" : "them"} anew, with no counter.`);
    if (r.unknown.length) notes.push(`${r.unknown.length} saved counter${r.unknown.length === 1 ? " matches" : "s match"} no drop ` +
      "the page knows (a newer game version or a mod?).");
    D.note.textContent = notes.join(" ");
    D.note.hidden = !notes.length;

    const cols = [["Drop", ""], ["Chance", "num"]].concat(withFile ? [["Next drop", ""]] : [],
      [["Longest gap", "num"], ["Shared with", ""]]);
    const tr = el("tr");
    for (const [name, cls] of cols) tr.append(el("th", cls, name));
    D.head.replaceChildren(tr);

    const rows = D.sort.value === "next" && withFile ? [...r.rows].sort(soonest) : r.rows;
    D.rows.replaceChildren(...rows.map((row) => {
      const line = el("tr");
      const drop = el("td");
      const code = el("code", "label");            // creature.stars.item, allowed to wrap only after its dots
      row.drop.split(".").forEach((part, i) => { if (i) code.append(".", el("wbr")); code.append(part); });
      drop.append(el("strong", "", row.itemName), el("span", "from", `${row.creatureName} · ${row.stars}★`), code);
      line.append(drop, el("td", "num", percent(row.chance)));
      if (withFile) line.append(nextCell(row));
      line.append(el("td", "num", String(row.longestGap)), sharedCell(row.shared));
      return line;
    }));
    if (!rows.length) {
      const empty = el("tr");
      empty.append(Object.assign(el("td", "quiet", "Nothing to show."), { colSpan: cols.length }));
      D.rows.append(empty);
    }
  }

  // ---------- the character file ----------

  async function choose(file) {
    if (!file) return;
    D.file.value = "";
    try {
      fileBytes = await file.arrayBuffer();
    } catch (e) {
      return fail("Could not read that file.");
    }
    D.drop.classList.add("chosen");
    D.dropText.textContent = `Using ${file.name}`;
    D.dropHint.textContent = "drop or click to choose another file";
    D.clear.hidden = false;
    ask();
  }

  function forgetFile() {
    fileBytes = null;
    D.drop.classList.remove("chosen");
    D.dropText.replaceChildren("Drop your ", el("code", "", ".fch"), " file here");
    D.dropHint.textContent = "or click to choose one";
    D.clear.hidden = true;
    D.error.hidden = true;
    if (D.filter.value.trim()) ask();
    else D.result.hidden = true;
  }

  D.form.addEventListener("submit", (e) => { e.preventDefault(); ask(); });
  D.sort.addEventListener("change", () => answer && draw());
  D.clear.addEventListener("click", forgetFile);
  D.file.addEventListener("change", () => choose(D.file.files[0]));
  D.drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); D.file.click(); } });
  for (const ev of ["dragenter", "dragover"]) D.drop.addEventListener(ev, (e) => { e.preventDefault(); D.drop.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) D.drop.addEventListener(ev, (e) => { e.preventDefault(); D.drop.classList.remove("over"); });
  D.drop.addEventListener("drop", (e) => choose(e.dataTransfer.files[0]));
})();
