// The American Pinball switch window (appf.py owns every decision; this draws
// what it is told and sends back what was pressed).  Plain JavaScript, served
// by tools/spike2_emu/pfweb.py like the other rigs' switch pages - the Dutch
// Pinball page (tools/dp_emu/dppage) with the ball controls an AP game needs:
// the rig serves a ball to the shooter lane, and Plunge / Drain move it on.
"use strict";

const Q = new URLSearchParams(location.search);
const TOKEN = Q.get("t") || "";

function api(m, ...a) {
  return fetch("/api?t=" + encodeURIComponent(TOKEN), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ m, a }),
  }).then((r) => r.json()).then((j) => (j.ok ? j.r : null)).catch(() => null);
}
let seq = 0;
const handlers = {};
function listen() {
  let opened = false;
  let es = null;
  try {
    es = new EventSource("/events?t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
    es.onopen = () => { opened = true; };
    es.onmessage = (m) => { seq = Number(m.lastEventId) || seq; const ev = JSON.parse(m.data); (handlers[ev.type] || (() => {}))(ev.data); };
  } catch (e) { es = null; }
  setTimeout(() => { if (!opened) { if (es) es.close(); poll(); } }, 4000);
}
async function poll() {
  for (;;) {
    try {
      const r = await fetch("/events?poll=1&wait=20&t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
      const j = await r.json();
      for (const ev of j.events) { seq = ev.seq; (handlers[ev.e.type] || (() => {}))(ev.e.data); }
    } catch (e) { await new Promise((ok) => setTimeout(ok, 1000)); }
  }
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
const tip = document.getElementById("tip");
function showTip(text, x, y) {
  tip.textContent = text; tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let tx = x + 16, ty = y + 14;
  if (tx + w > innerWidth - 6) tx = Math.max(6, x - w - 12);
  if (ty + h > innerHeight - 6) ty = Math.max(6, y - h - 10);
  tip.style.left = tx + "px"; tip.style.top = ty + "px";
}
function hideTip() { tip.hidden = true; }

let M = null;                    // the model (dppf.page_model)
let active = new Set();
const latched = new Set();
const views = {};                // n -> [marker, row]

function describe(s) {
  return s.label + "  (" + s.name + ", " + s.num + (s.opto ? ", an opto: active = blocked" : "") + ")" +
    (s.key ? "  key " + s.key : "") + "\nHold to make it active; right-click to latch.";
}

// Pressing: held while the button (or key) is down; a latch overrides.
function press(s, on) {
  if (latched.has(s.n)) return;
  api("hold", s.n, on);
}
function toggleLatch(s) {
  if (latched.has(s.n)) { latched.delete(s.n); api("hold", s.n, false); }
  else { latched.add(s.n); api("hold", s.n, true); }
  paint();
}
function bindPress(node, s) {
  let down = false;
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault(); down = true; node.setPointerCapture(e.pointerId); press(s, true);
  });
  const up = () => { if (down) { down = false; press(s, false); } };
  node.addEventListener("pointerup", up);
  node.addEventListener("pointercancel", up);
  node.addEventListener("contextmenu", (e) => { e.preventDefault(); toggleLatch(s); });
  node.addEventListener("mousemove", (e) => showTip(describe(s), e.clientX, e.clientY));
  node.addEventListener("mouseleave", hideTip);
}

function paint() {
  for (const [n, [mk, row]] of Object.entries(views)) {
    const on = active.has(Number(n));
    if (mk) mk.classList.toggle("on", on);
    row.classList.toggle("on", on);
    row.classList.toggle("latched", latched.has(Number(n)));
  }
  // the balls the game sees in the trough (the shooter lane is not in it)
  const balls = document.getElementById("balls");
  if (balls) {
    const n = M.switches.filter((s) => s.group === "Trough" && s.n !== M.shooter && active.has(s.n)).length;
    balls.textContent = n + " in the trough" + (M.shooter != null && active.has(M.shooter) ? ", 1 in the shooter lane" : "");
  }
  const door = document.getElementById("door");
  if (door) door.textContent = active.has(M.coin_door) ? "Open coin door" : "Close coin door";
}

function build() {
  const app = document.getElementById("app");
  app.textContent = "";
  const bar = el("div", "bar");
  bar.append(el("h1", "", M.title || "Switches"), el("span", "balls mono", ""));
  bar.lastChild.id = "balls";
  bar.append(el("span", "sp"));
  // No physics: the ball in the shooter lane goes when you plunge it, and a
  // ball on the playfield only drains when you say so.
  if (M.shooter != null) {
    const plunge = el("button", "btn", "Plunge");
    plunge.append(el("span", "k", "P"));
    plunge.title = "Launch the ball in the shooter lane";
    plunge.onclick = () => api("plunge");
    bar.append(plunge);
  }
  const drain = el("button", "btn", "Drain");
  drain.append(el("span", "k", "D"));
  drain.title = "A ball on the playfield drains into the trough: the game ends the ball - or, while its ball save runs (the first seconds of play), serves it again";
  drain.onclick = () => api("drain");
  bar.append(drain);
  if (M.coin_door != null) {
    const door = el("button", "btn", "Open coin door");
    door.id = "door";
    door.title = "Open or close the coin door (the game warns while it is open)";
    door.onclick = () => api("hold", M.coin_door, !active.has(M.coin_door));
    bar.append(door);
  }
  const body = el("div", "body");
  const pf = el("div", "pf");
  const box = el("div", "pf-box");
  pf.append(box);
  const placed = M.switches.filter((s) => s.placed);
  const place = (w, h) => {
    box.style.setProperty("--ar", w + " / " + h);
    for (const s of placed) {
      const mk = views[s.n][0];
      mk.style.left = (100 * s.x / w) + "%";
      mk.style.top = (100 * s.y / h) + "%";
    }
  };
  const list = el("div", "list");
  let group = null;
  for (const s of M.switches) {
    let mk = null;
    if (s.placed) { mk = el("div", "m"); box.append(mk); bindPress(mk, s); }
    if (s.group !== group) { group = s.group; list.append(el("div", "grp", group)); }
    const row = el("div", "row");
    row.append(el("span", "n", s.num || String(s.n)), el("span", "dot"), el("span", "l", s.label), el("span", "k", s.key || ""));
    bindPress(row, s);
    list.append(row);
    views[s.n] = [mk, row];
  }
  if (M.art) {
    const img = new Image();
    img.draggable = false;
    img.onload = () => place(img.naturalWidth, img.naturalHeight);
    img.src = M.art + "?t=" + encodeURIComponent(TOKEN);
    box.prepend(img);
  } else {
    box.classList.add("noart");
    const w = Math.max(...placed.map((s) => s.x), 300) + 12;
    const h = Math.max(...placed.map((s) => s.y), 600) + 12;
    place(w, h);
  }
  // no drawing and nothing placed (Alice): the list is the window
  if (!M.art && !placed.length) { body.classList.add("listonly"); body.append(list); }
  else body.append(pf, list);
  app.append(bar, body);
  paint();
}

// Keyboard: this window focused.  Keys that hold (flippers) hold; one key
// can drive several switches (Legends of Valhalla's two left flippers).
function keyTargets(e) {
  return M.switches.filter((s) => s.codes.includes(e.code));
}
addEventListener("keydown", (e) => {
  if (!M || e.repeat) return;
  if (e.code === "KeyP") { e.preventDefault(); api("plunge"); return; }
  if (e.code === "KeyD") { e.preventDefault(); api("drain"); return; }
  const ss = keyTargets(e); if (!ss.length) return;
  e.preventDefault();
  for (const s of ss) { if (s.hold) press(s, true); else api("tap", s.n); }
});
addEventListener("keyup", (e) => {
  if (!M) return;
  for (const s of keyTargets(e)) if (s.hold) press(s, false);
});

handlers.live = (live) => {
  M.live = live;
  active = new Set(live.active || []);
  paint();
};
handlers.close = () => { try { window.close(); } catch (e) { /* the host closes it */ } };

(async () => {
  const r = await fetch("/state?t=" + encodeURIComponent(TOKEN) + "&page=main");
  M = await r.json();
  seq = M._seq || 0;
  active = new Set((M.live && M.live.active) || []);
  document.title = (M.title || "American Pinball") + " - switches";
  build();
  listen();
})();
