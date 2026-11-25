"use strict";

/* Web Worker for the upgrade tools on the page. It runs upgrade_oracle.py and upgrade_cost.py themselves with Pyodide,
   in the background so the page stays responsive while they work.
   Messages in:  {type: "items"}, {type: "find", item, quality, upgrades, limit, after, start, tz},
                 {type: "relay", item, from, to, start, per, tz}, {type: "predict", bytes, tz} (a dropped save file),
                 {type: "predictItem", item, quality, created, tz}, {type: "costItems"} or
                 {type: "cost", item, target, created, bytes, tz} or {type: "created", bytes, tz} (the timer's check).
   Times are local dates and times ("YYYY-MM-DDTHH:MM:SS") in time zone tz: the zone of the computer running the game
   (an IANA name or an offset; empty means the browser's own, which Pyodide's localtime follows). A dropped file's UTC
   creation stamp is read in it, the same way the game uses the time zone of the computer it runs on.
   Messages out: {type: "items"}, {type: "result"}, {type: "relayed"}, {type: "predicted"}, {type: "predictedItem"},
                 {type: "costItems"}, {type: "costed"}, {type: "createdRead"} or {type: "error", message}. */

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
        loadPyodide({ indexURL: PYODIDE_URL }), fetchText("../upgrade_oracle.py?v=cae414b"), fetchText("../upgrade_cost.py?v=cae414b"),
      ]);
      await py.loadPackage("tzdata");                   // the time zone database, for named zones (zoneinfo)
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
      // no file: pass undefined, which arrives as None (a JS null would not)
      const out = cost().web_cost(d.item, d.target, d.created || "", d.bytes ? new Uint8Array(d.bytes) : undefined, d.tz || "");
      self.postMessage({ type: "costed", ...JSON.parse(out) });
    } else if (e.data.type === "created") {
      self.postMessage({ type: "createdRead", ...JSON.parse(mod.web_created(new Uint8Array(e.data.bytes), e.data.tz || "")) });
    } else if (e.data.type === "items") {
      self.postMessage({ type: "items", items: JSON.parse(mod.web_items()) });
    } else if (e.data.type === "predict") {
      self.postMessage({ type: "predicted", ...JSON.parse(mod.web_predict(new Uint8Array(e.data.bytes), e.data.tz || "")) });
    } else if (e.data.type === "relay") {
      const d = e.data;
      self.postMessage({ type: "relayed", ...JSON.parse(mod.web_relay(d.item, d.from, d.to, d.start || "", d.per || 4, d.tz || "")) });
    } else if (e.data.type === "predictItem") {
      const d = e.data;
      self.postMessage({ type: "predictedItem", ...JSON.parse(mod.web_predict_item(d.item, d.quality, d.created || "", d.tz || "")) });
    } else {
      self.postMessage({ type: "result", ...JSON.parse(mod.web_find(e.data.item, e.data.quality, e.data.limit, e.data.after || "", e.data.start || "", e.data.upgrades || 8, e.data.tz || "")) });
    }
  } catch (err) {
    self.postMessage({ type: "error", message: (err && err.message) || "Something went wrong." });
  }
};
