// Emulate (American Pinball): run an AP game on this PC from its .pkg.
// Python half: webui/tabs/emulate_ap.py.  The machine's switches are a window
// of their own (tools/ap_emu/appf.py), as the other rigs' are; it opens by
// itself when the game is up, and "Playfield window" brings it back (or to
// the front).  A real button, not a ghost one: as ghost text beside Stop it
// read as a caption, and a player never found it (PAD-295).

import { html, PageHead, Card, Button, PathField, Chip, Note, Modal, Table, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { VolumeControl, StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;

// The Cache window, as the Stern tab's: what the rig keeps in the app's
// Linux (each unpacked .pkg, and the one-time setup), and deleting it.
const CACHE_COLS = [
  { key: "label", label: "Item", width: "minmax(160px,1.1fr)", cls: "mono", titleOf: (r) => r.label },
  { key: "size", label: "On disk", width: "90px", num: true },
  { key: "used", label: "Last played", width: "140px" },
  { key: "src", label: "From", width: "minmax(0,1.6fr)", cls: "mono dim", titleOf: (r) => r.src || undefined },
];

function CacheModal({ c }) {
  const rows = c.rows || [];
  const sel = new Set(c.sel || []);
  // a click picks one row; Ctrl/Cmd-click adds or removes one
  const pick = (r, _i, e) => {
    if (!r) return;
    let next;
    if (e && (e.ctrlKey || e.metaKey)) {
      next = new Set(sel);
      if (next.has(r.name)) next.delete(r.name); else next.add(r.name);
    } else next = new Set([r.name]);
    call("emulate_ap.cache_select", [...next]);
  };
  const close = () => call("emulate_ap.cache_close");
  return html`<${Modal} title="Cache — American Pinball emulator" icon="disk" xwide onClose=${close} cls="emu-cache"
    footer=${html`<span class="small muted grow emu-cache-hint">${c.hint}</span>
      <${Button} kind="danger" disabled=${c.busy || !sel.size} onClick=${() => call("emulate_ap.cache_delete")}>Delete selected<//>
      <${Button} disabled=${c.busy} onClick=${() => call("emulate_ap.cache_refresh")}>Refresh<//>
      <${Button} onClick=${close}>Close<//>`}>
    <div class="row">${c.busy ? html`<span class="spin"></span>` : null}<span>${c.head}</span></div>
    <div class="emu-cache-tbl">
      <${Table} columns=${CACHE_COLS} rows=${rows} rowKey=${(r) => r.name} selected=${sel}
        onSelect=${pick} style="height:300px" />
    </div>
  <//>`;
}

export default function EmulateAP() {
  const s = useNs("emulate_ap");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const hist = (shell.path_history || {}).ap_emulate_pkg || [];
  // while a start is in flight the button is Cancel
  const stopish = up || !!s.starting;
  const goKind = s.go_busy ? "" : stopish ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${stopish ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_ap.toggle")}>${s.go_label || "Start"}<//>
    ${up ? html`<${Button} icon="external" title=${s.switches_tip}
      onClick=${() => call("emulate_ap.switches")}>Playfield window<//>` : null}
    <span class="emu-sp"></span>
    <${VolumeControl} ns="emulate_ap" s=${s} title=${s.volume_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <label class="small">Game code (.pkg)</label>
          <${PathField} ns="emulate_ap" k="pkg" value=${s.pkg} title=${s.pkg_tip} history=${hist}
            placeholder="lov-gamecode_25.08.27.pkg - or a build from Write" onBrowse=${() => call("emulate_ap.browse")}
            extra=${html`<${Button} kind="ghost" disabled=${!s.rig_ok} onClick=${() => call("emulate_ap.open_cache")}
              title="Shows and manages what the emulator keeps in the app's Linux: each game unpacked from its .pkg, and the one-time setup. Deleting frees the space now; it is unpacked (or downloaded) again on the next Start.">Cache…<//>`} />
          <span class="small muted">${s.pkg_tip}</span>
        <//>
        ${s.note ? html`<${Note} kind="warn">${s.note}<//>` : null}
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
    ${s.cache ? html`<${CacheModal} c=${s.cache} />` : null}
  </div>`;
}
