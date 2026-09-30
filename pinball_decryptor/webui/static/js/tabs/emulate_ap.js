// Emulate (American Pinball): run an AP game on this PC from its .pkg.
// Python half: webui/tabs/emulate_ap.py.  The machine's switches are a window
// of their own (tools/ap_emu/appf.py), as the other rigs' are; it opens by
// itself when the game is up, and "Switches window" brings it back.

import { html, PageHead, Card, Button, PathField, Chip, Note, Check, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;

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
    ${up ? html`<${Button} kind="ghost" title=${s.switches_tip}
      onClick=${() => call("emulate_ap.switches")}>Switches window<//>` : null}
    <span class="emu-sp"></span>
    <${Check} ns="emulate_ap" k="mute" checked=${!!s.mute} label="Mute" title=${s.sound_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <label class="small">Game code (.pkg)</label>
          <${PathField} ns="emulate_ap" k="pkg" value=${s.pkg} title=${s.pkg_tip} history=${hist}
            placeholder="lov-gamecode_25.08.27.pkg - or a build from Write" onBrowse=${() => call("emulate_ap.browse")} />
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
  </div>`;
}
