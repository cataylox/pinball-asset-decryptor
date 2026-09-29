// Emulate (Barrels of Fun): run a BoF game on this PC.  Python half:
// webui/tabs/emulate_bof.py.  Unlike the other rigs the switch panel is on
// this page: the game window is the machine's screens, this is its cabinet.

import { html, useEffect, PageHead, Card, Button, PathField, Chip, Note, Check, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;

// Keyboard, while this page has focus and a game is up.  Held keys hold
// their switch (flippers); the rest tap.
const KEYS = {
  z: "flipper_left", ShiftLeft: "flipper_left",
  "/": "flipper_right", ShiftRight: "flipper_right",
  "1": "start", "5": "coin", " ": "launch", a: "action",
};

function SwitchButton({ sw, active, hold }) {
  const n = sw.n;
  const down = (e) => { e.preventDefault(); if (hold) call("emulate_bof.hold", n, true); };
  const up = () => { if (hold) call("emulate_bof.hold", n, false); };
  const click = () => { if (!hold) call("emulate_bof.press", n, 150); };
  // right-click latches: the switch stays as it is until clicked again
  const latch = (e) => { e.preventDefault(); call("emulate_bof.hold", n, !active); };
  return html`<button type="button" class=${"bof-sw" + (active ? " on" : "") + (sw.opto ? " opto" : "")}
    title=${sw.label + " - switch " + n + (sw.opto ? ", opto" : "") + ". Click to press, right-click to latch."}
    onPointerDown=${down} onPointerUp=${up} onPointerLeave=${up} onClick=${click} onContextMenu=${latch}>
    <span class="mono bof-n">${n}</span><span class="bof-l">${sw.label}</span></button>`;
}

function Panel({ s }) {
  const p = s.panel;
  const active = new Set(s.active || []);
  useEffect(() => {
    if (!p || !s.up) return undefined;
    const find = (name) => (p.quick || []).find((q) => q.key === name);
    const lookup = (e) => KEYS[e.code] || KEYS[e.key];
    const target = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "");
    const onDown = (e) => {
      const k = lookup(e); if (!k || target(e) || e.repeat) return;
      const q = find(k); if (!q) return;
      e.preventDefault();
      if (q.hold) call("emulate_bof.hold", q.n, true); else call("emulate_bof.press", q.n, 150);
    };
    const onUp = (e) => {
      const k = lookup(e); if (!k || target(e)) return;
      const q = find(k); if (q && q.hold) call("emulate_bof.hold", q.n, false);
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => { window.removeEventListener("keydown", onDown); window.removeEventListener("keyup", onUp); };
  }, [p, s.up]);
  if (!p) return null;
  const doorClosed = p.coin_door != null && active.has(p.coin_door);
  return html`<${Card} title="Cabinet" cls="bof-panel"
      extra=${html`<span class="small muted">Z / Shift: flippers · 1 Start · 5 Coin · Space Launch</span>`}>
    <div class="row bof-quick">
      ${(p.quick || []).map((q) => html`<${SwitchButton} sw=${q} hold=${q.hold} active=${active.has(q.n)} />`)}
      <${Button} kind="ghost" icon="play" title="The ball in the shooter lane goes into play (no launch coil needed)"
        onClick=${() => call("emulate_bof.plunge")}>Plunge<//>
      <${Button} kind="ghost" title="One ball in play drains to the trough"
        onClick=${() => call("emulate_bof.drain")}>Drain<//>
      ${p.coin_door != null ? html`<${Button} kind="ghost"
        title="Open or close the coin door (the game cuts coil power while it is open)"
        onClick=${() => call("emulate_bof.hold", p.coin_door, !doorClosed)}>${doorClosed ? "Open coin door" : "Close coin door"}<//>` : null}
    </div>
    <div class="row bof-quick">
      <span class="small muted">Service</span>
      ${(p.service || []).map((q) => html`<${SwitchButton} sw=${q} active=${active.has(q.n)} />`)}
    </div>
    ${(p.groups || []).map((g) => html`<details class="bof-group" open=${g.name === "Playfield"}>
      <summary>${g.name} <span class="muted small">${g.switches.length} switches</span></summary>
      <div class="bof-grid">${g.switches.map((sw) => html`<${SwitchButton} sw=${sw} active=${active.has(sw.n)} />`)}</div>
    </details>`)}
  <//>`;
}

export default function EmulateBoF() {
  const s = useNs("emulate_bof");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const hist = (shell.path_history && shell.path_history.bof_emulate_fun) || [];
  const goKind = s.go_busy ? "" : up ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${up ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_bof.toggle")}>${s.go_label || "Start"}<//>
    <span class="emu-sp"></span>
    <${Check} ns="emulate_bof" k="mute" checked=${!!s.mute} label="Mute" title=${s.sound_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game file" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <${PathField} ns="emulate_bof" k="fun" value=${s.fun} title=${s.fun_tip} history=${hist}
            placeholder="dune.fun, winchester.fun, lab.fun - or a build from Write" onBrowse=${() => call("emulate_bof.browse")} />
          <span class="small muted">${s.fun_tip}</span>
        <//>
        ${s.note ? html`<${Note} kind="warn">${s.note}<//>` : null}
        ${up ? html`<${Panel} s=${s} />` : null}
      </div>
      <div class="stack emu-col">
        <${Card} title="Status" extra=${html`<${StateChip} tone=${s.tone} label=${s.state_label} />`}>
          ${s.state_hint ? html`<div class=${"emu-hint " + (s.tone === "warn" ? "warn" : "")}>${s.state_hint}</div>` : null}
          <div class="kv emu-kv">
            ${cells.map((c) => html`<span class="k">${c.label}</span><span class="mono v">${c.value}</span>`)}
          </div>
        <//>
      </div>
    </div>
  </div>`;
}
