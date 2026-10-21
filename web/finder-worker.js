"use strict";

/* Web Worker for the upgrade tools on the page. It runs upgrade_oracle.py and upgrade_cost.py themselves with Pyodide,
   in the background so the page stays responsive while they work.
   Messages in:  {type: "items"}, {type: "find", item, quality, limit, after}, {type: "relay", item, from, to},
                 {type: "predict", bytes} (a dropped save file), {type: "predictItem", item, quality, name},
                 {type: "costItems"} or {type: "cost", item, target, name, bytes}.
   Messages out: {type: "items"}, {type: "result"}, {type: "relayed"}, {type: "predicted"}, {type: "predictedItem"},
                 {type: "costItems"}, {type: "costed"} or {type: "error", message}. */

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";
importScripts(PYODIDE_URL + "pyodide.js");

let ready = null;

let cost = null;     // the upgrade_cost module, imported the first time the cost tool is used

const fetchText = (path) => fetch(path).then((r) => {
  if (!r.ok) throw new Error("Could not load " + path.replace("../", "").split("?")[0]);
  return r.text();
});

function load() {
  if (!ready) {
    ready = (async () => {
      const [py, oracle, costSource] = await Promise.all([
        loadPyodide({ indexURL: PYODIDE_URL }), fetchText("../upgrade_oracle.py?v=7baa23c"), fetchText("../upgrade_cost.py?v=7baa23c"),
      ]);
      py.FS.writeFile("upgrade_oracle.py", oracle);
      py.FS.writeFile("upgrade_cost.py", costSource);   // imports upgrade_oracle, so both sit side by side
      cost = () => py.pyimport("upgrade_cost");
      return py.pyimport("upgrade_oracle");
    })();
    ready.catch(() => { ready = null; });
  }
  return ready;
}

self.onmessage = async (e) => {
  try {
    const mod = await load();
    if (e.data.type === "costItems") {
      self.postMessage({ type: "costItems", items: JSON.parse(cost().web_cost_items()) });
    } else if (e.data.type === "cost") {
      const d = e.data;
      const out = d.bytes ? cost().web_cost(d.item, d.target, d.name || "", new Uint8Array(d.bytes))
        : cost().web_cost(d.item, d.target, d.name || "");    // no file: leave the argument out (a JS null is not None)
      self.postMessage({ type: "costed", ...JSON.parse(out) });
    } else if (e.data.type === "items") {
      self.postMessage({ type: "items", items: JSON.parse(mod.web_items()) });
    } else if (e.data.type === "predict") {
      self.postMessage({ type: "predicted", ...JSON.parse(mod.web_predict(new Uint8Array(e.data.bytes))) });
    } else if (e.data.type === "relay") {
      const d = e.data;
      self.postMessage({ type: "relayed", ...JSON.parse(mod.web_relay(d.item, d.from, d.to)) });
    } else if (e.data.type === "predictItem") {
      const d = e.data;
      self.postMessage({ type: "predictedItem", ...JSON.parse(mod.web_predict_item(d.item, d.quality, d.name)) });
    } else {
      self.postMessage({ type: "result", ...JSON.parse(mod.web_find(e.data.item, e.data.quality, e.data.limit, e.data.after || "")) });
    }
  } catch (err) {
    self.postMessage({ type: "error", message: (err && err.message) || "Something went wrong." });
  }
};
