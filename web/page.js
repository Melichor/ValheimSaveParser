"use strict";

/* The page around the tools: the tabs that switch between them, and the "Where is my character file?" help shown under
   every place that asks for a .fch file. The tools themselves are in app.js (achievements) and finder.js (upgrades). */

// the help is written once in a <template> and copied into each [data-where] placeholder
const whereHelp = document.getElementById("whereHelp");
for (const slot of document.querySelectorAll("[data-where]")) slot.replaceWith(whereHelp.content.cloneNode(true));

// ---------- tabs ----------

const tablist = document.querySelector('[role="tablist"]');
const tabs = [...tablist.querySelectorAll('[role="tab"]')];
const panelOf = (tab) => document.getElementById(tab.getAttribute("aria-controls"));

function selectTab(tab) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    panelOf(t).hidden = !on;
  }
  tab.scrollIntoView({ block: "nearest", inline: "nearest" });   // on a narrow screen the tab bar scrolls sideways
}

// a link to a panel (#cost) or to something inside one (#relay) opens that panel's tab; no hash opens the first one
function openHash() {
  const target = location.hash ? document.getElementById(location.hash.slice(1)) : null;
  const panel = target ? target.closest('[role="tabpanel"]') : panelOf(tabs[0]);
  if (!panel) return;
  selectTab(tabs.find((t) => panelOf(t) === panel));
  if (target && target !== panel) target.scrollIntoView();
}

for (const tab of tabs) {
  tab.addEventListener("click", () => {
    selectTab(tab);
    history.replaceState(null, "", "#" + panelOf(tab).id);   // the address links to the open tab, without a jump
  });
}

// arrow keys, Home and End move between the tabs
tablist.addEventListener("keydown", (e) => {
  const i = tabs.indexOf(document.activeElement);
  const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (i < 0 || to === undefined) return;
  e.preventDefault();
  const tab = tabs[(to + tabs.length) % tabs.length];
  tab.click();
  tab.focus();
});

window.addEventListener("hashchange", openHash);
if (location.hash) openHash();
