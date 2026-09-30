// Emulate (Pinball Brothers): run a Pinball Brothers game on this PC from its
// update file - Predator only so far, which the page says up front.  Python
// half: webui/tabs/emulate_pb.py.  Laid out as the American Pinball tab is
// (the template every maker's Emulate tab follows): the setup notice, the
// game file with Cache…, Start / Playfield window / Volume, and the status.
// The virtual playfield is AP's window (tools/pb_emu/pbpf.py ->
// tools/ap_emu/appf.py); it opens by itself when the game reaches attract.

import { html, PageHead, Card, Button, PathField, Chip, Note, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { VolumeControl, StateChip, introLines } from "./emulate_jjp_shared.js";
import { CacheModal } from "./emulate_ap.js";

export const css = true;

export default function EmulatePB() {
  const s = useNs("emulate_pb");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const supported = s.supported || [];
  const hist = (shell.path_history || {}).pb_emulate_file || [];
  // while a start is in flight the button is Cancel
  const stopish = up || !!s.starting;
  const goKind = s.go_busy ? "" : stopish ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${stopish ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_pb.toggle")}>${s.go_label || "Start"}<//>
    ${up ? html`<${Button} icon="external" title=${s.switches_tip}
      onClick=${() => call("emulate_pb.switches")}>Playfield window<//>` : null}
    <span class="emu-sp"></span>
    <${VolumeControl} ns="emulate_pb" s=${s} title=${s.volume_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    ${s.setup_msg ? html`<div class="stack emu-notices"><${Note} kind="warn"
      action=${s.setup_btn ? html`<${Button} kind="primary" size="sm" disabled=${!s.setup_enabled}
        busy=${!s.setup_enabled} onClick=${() => call("emulate_pb.setup")}>${s.setup_label}<//>` : null}>${s.setup_msg}<//></div>` : null}
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <label class="small">Update file (.upd)</label>
          <${PathField} ns="emulate_pb" k="file" value=${s.file} title=${s.file_tip} history=${hist}
            placeholder="pbpp_predator_game_1_0_1.upd" onBrowse=${() => call("emulate_pb.browse")}
            extra=${html`<${Button} kind="ghost" disabled=${!s.rig_ok} onClick=${() => call("emulate_pb.open_cache")}
              title="Shows and manages what the emulator keeps in the app's Linux: each game unpacked from its updates, and the one-time setup. Deleting frees the space now; it is unpacked (or downloaded) again on the next Start.">Cache…<//>`} />
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
        <${Card} title="Supported games" cls="pb-supported">
          <div class="pb-games">
            ${supported.map((g) => html`<${Chip} kind="ok" dot>${g}<//>`)}
          </div>
          <span class="small muted">Alien, Queen and ABBA run on different boards and can't be emulated yet.</span>
        <//>
      </div>
    </div>
    ${s.cache ? html`<${CacheModal} c=${s.cache} ns="emulate_pb" title="Cache — Pinball Brothers emulator" />` : null}
  </div>`;
}
