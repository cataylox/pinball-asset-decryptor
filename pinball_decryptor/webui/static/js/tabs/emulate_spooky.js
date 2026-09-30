// Emulate (Spooky Pinball): run a Spooky game on this PC - Beetlejuice only
// so far, which the page says before anything else.  Python half:
// webui/tabs/emulate_spooky.py.  The switches are a window of their own
// (tools/spooky_emu/spkpf.py); it opens by itself when the game reaches
// attract, and "Switches window" brings it back.

import { html, PageHead, Card, Button, PathField, Chip, Note, Check, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;

export default function EmulateSpooky() {
  const s = useNs("emulate_spooky");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const supported = s.supported || [];
  const hist = (shell.path_history && shell.path_history.spooky_emulate_file) || [];
  // while a start is in flight the button is Cancel
  const stopish = up || !!s.starting;
  const goKind = s.go_busy ? "" : stopish ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${stopish ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_spooky.toggle")}>${s.go_label || "Start"}<//>
    ${up ? html`<${Button} kind="ghost" title=${s.switches_tip}
      onClick=${() => call("emulate_spooky.switches")}>Switches window<//>` : null}
    <span class="emu-sp"></span>
    <${Check} ns="emulate_spooky" k="mute" checked=${!!s.mute} label="Mute" title=${s.sound_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Supported games" cls="spk-supported">
          <div class="spk-games">
            ${supported.map((g) => html`<${Chip} kind="ok" dot>${g}<//>`)}
          </div>
          <span class="small muted">Other Spooky games can't be emulated yet.</span>
        <//>
        <${Card} title="Update file" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <${PathField} ns="emulate_spooky" k="file" value=${s.file} title=${s.file_tip} history=${hist}
            placeholder="v2026.09.15.11.beetlejuice - or a build from Write" onBrowse=${() => call("emulate_spooky.browse")} />
          <span class="small muted">${s.file_tip}</span>
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
