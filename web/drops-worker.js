"use strict";

/* Web Worker for the Drop counters tab. It runs drop_counters.py itself with Pyodide, in the background so the page
   stays responsive while the runtime starts.
   Messages in:  {type: "drops", filters, bytes} (bytes: the character file's contents; left out to show only the rules).
   Messages out: {type: "dropped", ...} (what drop_counters.web_drops returns) or {type: "error", message}. */

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";
importScripts(PYODIDE_URL + "pyodide.js");

let ready = null;

function load() {
  if (!ready) {
    ready = (async () => {
      const [py, source] = await Promise.all([
        loadPyodide({ indexURL: PYODIDE_URL }),
        fetch("../drop_counters.py?v=8c670f1").then((r) => {
          if (!r.ok) throw new Error("Could not load drop_counters.py");
          return r.text();
        }),
      ]);
      py.FS.writeFile("drop_counters.py", source);
      return py.pyimport("drop_counters");
    })();
    ready.catch(() => { ready = null; });
  }
  return ready;
}

self.onmessage = async (e) => {
  try {
    const mod = await load();
    const d = e.data;
    const out = d.bytes ? mod.web_drops(d.filters || "", new Uint8Array(d.bytes))
      : mod.web_drops(d.filters || "");          // no file: leave the argument out (a JS null is not None)
    self.postMessage({ type: "dropped", ...JSON.parse(out) });
  } catch (err) {
    self.postMessage({ type: "error", message: (err && err.message) || "Something went wrong." });
  }
};
