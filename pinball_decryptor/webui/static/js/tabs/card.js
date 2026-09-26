// Select card tab (PAD-224): pick the card image (or the card in a reader)
// the app works on, and see which tabs work on it straight away and which
// need it extracted first.  The card is the Extract tab's input, so the page
// renders the extract namespace and calls extract.*; the Python half is
// webui/tabs/card.py.

import { html, Button, Card, Chip, Icon, PageHead, Seg, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { NEEDS, WHAT, tabLock } from "../core/locks.js";
import { SourceBody, ExtractOverlays, inputPhrase, useNoStrayDrops } from "./extract.js";

export const css = true;

const HIDE = new Set(["card", "extract"]);

function TabRow({ t, lock }) {
  return html`<button type="button" class=${cx("c-row", lock && "locked")} onClick=${() => call("ui.select_tab", t.ns)}
      title=${lock ? lock.long : "Open the " + t.label + " tab"}>
    <${Icon} name=${t.icon} />
    <span class="c-name">${t.label}</span>
    <span class="c-what">${WHAT[t.ns] || ""}${lock ? html`<span class="c-why">${lock.short}</span>` : null}</span>
    ${lock ? html`<${Icon} name="lock" cls="c-state" />` : html`<${Icon} name="check" cls="c-state ok-ink" />`}
  </button>`;
}

function WhatCard({ shell }) {
  const ps = shell.project_state;
  const tabs = (shell.tabs || []).filter((t) => t.visible && !HIDE.has(t.ns));
  const direct = tabs.filter((t) => !NEEDS[t.ns]);
  const folder = tabs.filter((t) => NEEDS[t.ns] === "project");
  const needs = tabs.filter((t) => NEEDS[t.ns] === "extract");
  const anyLocked = folder.concat(needs).some((t) => tabLock(t.ns, t.label, ps));
  const project = ps ? html`<${Chip} kind="acc" title=${ps.folder}>${ps.name}<//>` : null;
  return html`<${Card} cls="c-what-card" title="What you can do with it">
    ${direct.length ? html`<div class="stack c-sec">
        <span class="lbl">Works straight from the card, no extract needed</span>
        ${direct.map((t) => html`<${TabRow} t=${t} lock=${null} />`)}
      </div>` : null}
    ${folder.length ? html`<div class="stack c-sec">
        <span class="lbl">Needs a project folder to save into, no extract needed</span>
        ${folder.map((t) => html`<${TabRow} t=${t} lock=${tabLock(t.ns, t.label, ps)} />`)}
      </div>` : null}
    ${needs.length ? html`<div class="stack c-sec">
        <span class="lbl">Needs the card extracted into a project folder</span>
        ${needs.map((t) => html`<${TabRow} t=${t} lock=${tabLock(t.ns, t.label, ps)} />`)}
      </div>` : null}
    <div class="note"><${Icon} name=${anyLocked ? "lock" : "info"} /><div class="body-text">
      ${!ps ? html`There is no project folder yet. Extract the card into one to unlock the tabs marked with a lock; until then they are greyed out in the list on the left.`
        : anyLocked && ps.archived ? html`Project ${project} is archived. Extract into it again to unlock the tabs marked with a lock; until then they are greyed out in the list on the left.`
        : anyLocked ? html`Project ${project} has no extract yet. Extract the card into it to unlock the tabs marked with a lock; until then they are greyed out in the list on the left.`
        : html`Project ${project} holds an extract, so every tab is ready.`}
    </div></div>
  <//>`;
}

export default function CardTab() {
  const s = useNs("extract");
  const shell = useNs("shell");
  useNoStrayDrops();
  const hist = shell.path_history || {};
  const drive = s.drive_label === "Game SSD" ? "game SSD" : (s.drive_label || "card");
  const have = s.ssd ? !!s.drive : !!s.input;
  const sub = "Pick " + inputPhrase(s.input_label) + (s.direct ? " or the " + drive + " in a reader" : "")
    + ". Some tabs work on it straight away; the rest need its files extracted into a project folder first.";
  return html`<div class="page x-page c-page">
    <${PageHead} title="Select card" sub=${sub} />
    <div class="cols c75 x-cols">
      <div class="stack x-col">
        <${Card} cls="x-source" title="Card"
            extra=${s.direct ? html`<${Seg} value=${s.source} onChange=${(v) => call("extract.set_source", v)}
              options=${[{ value: "iso", label: s.iso_label }, { value: "ssd", label: s.ssd_label }]} />` : null}
            footer=${html`<${Button} kind="primary" size="big" icon="extract" disabled=${!have}
                title=${have ? "" : "Pick a card first"} onClick=${() => call("ui.select_tab", "extract")}>Extract…<//>
              <span class="dim small grow">Only the tabs that need an extract wait for this step.</span>`}>
          <${SourceBody} s=${s} hist=${hist} />
        <//>
      </div>
      <div class="stack x-col">
        <${WhatCard} shell=${shell} />
      </div>
    </div>
    <${ExtractOverlays} s=${s} />
  </div>`;
}
