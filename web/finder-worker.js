"use strict";

/* Web Worker for the upgrade name finder. It runs upgrade_oracle.py itself with Pyodide, in the background so the page
   stays responsive while it searches. Messages in: {type: "items"}, {type: "find", item, quality, limit, after} or
   {type: "findAdvanced", item, quality, upgrades, copies, limit, after} {type: "predict", bytes} (a dropped save file)
   or {type: "predictItem", item, quality, name}.
   Messages out: {type: "items", items}, {type: "result", ...} or {type: "error", message}. */

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";
importScripts(PYODIDE_URL + "pyodide.js");

let ready = null;

function load() {
  if (!ready) {
    ready = (async () => {
      const [py, source] = await Promise.all([
        loadPyodide({ indexURL: PYODIDE_URL }),
        fetch("../upgrade_oracle.py").then((r) => {
          if (!r.ok) throw new Error("Could not load upgrade_oracle.py");
          return r.text();
        }),
      ]);
      py.FS.writeFile("upgrade_oracle.py", source);
      return py.pyimport("upgrade_oracle");
    })();
    ready.catch(() => { ready = null; });
  }
  return ready;
}

self.onmessage = async (e) => {
  try {
    const mod = await load();
    if (e.data.type === "items") {
      self.postMessage({ type: "items", items: JSON.parse(mod.web_items()) });
    } else if (e.data.type === "predict") {
      self.postMessage({ type: "predicted", ...JSON.parse(mod.web_predict(new Uint8Array(e.data.bytes))) });
    } else if (e.data.type === "predictItem") {
      const d = e.data;
      self.postMessage({ type: "predictedItem", ...JSON.parse(mod.web_predict_item(d.item, d.quality, d.name)) });
    } else if (e.data.type === "findAdvanced") {
      const d = e.data;
      self.postMessage({ type: "result", ...JSON.parse(mod.web_find_advanced(d.item, d.quality, d.upgrades, d.copies, d.limit, d.after || "")) });
    } else {
      self.postMessage({ type: "result", ...JSON.parse(mod.web_find(e.data.item, e.data.quality, e.data.limit, e.data.after || "")) });
    }
  } catch (err) {
    self.postMessage({ type: "error", message: (err && err.message) || "Something went wrong." });
  }
};
