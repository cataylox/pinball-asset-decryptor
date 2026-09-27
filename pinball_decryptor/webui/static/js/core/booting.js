// The "machine is starting" look, shared by every picture of a machine's
// screen that takes a while to come (the Select card tab's loading screen,
// the Multi-boot tab's menu): while it is worked on, a ball rolls the length
// of the screen over a row of chasing insert lamps and the stage says what
// is happening; when the picture lands it comes on like a CRT.  The styles
// are app.css's .boot / .crt-on.

import { html } from "./ui.js";

export function Booting({ stage, sub }) {
  return html`<div class="boot" role="status" aria-live="polite">
    <div class="boot-sweep"></div>
    <div class="boot-lane"><span class="boot-ball"></span></div>
    <div class="boot-lamps" aria-hidden="true">${[0, 1, 2, 3, 4, 5, 6].map((i) => html`<i style=${`--i:${i}`}></i>`)}</div>
    <div class="boot-txt">${stage || "Reading the card…"}</div>
    ${sub ? html`<div class="boot-sub">${sub}</div>` : null}
  </div>`;
}
