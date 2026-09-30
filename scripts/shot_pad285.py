"""PAD-285 proof shot: selecting a layer inside a switchable part whose look is off.

    python scripts/shot_pad285.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig selects,
never edits), opens Scenes on Godzilla's Kaiju Battle Select (resting on Ebirah), clicks
Gigan's name box in the Layers list (shown on top while selected, with the Gigan picture it
sits in), then clicks the Gigan picture right next to it, and writes:

- <prefix>_select.png   the page after the second click
- <prefix>_notes.txt    what is selected and which Gigan layers are drawn
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SELECT = ("/godzilla_le/assets/lcd/auto_loaded/"
          "cac32730af42b9d26d26c4bb6e667b07da53113e")
GIGAN_TEXT = 1061       # Gigan_Textbox_instance, inside GiganFullBody_instance (look off)
GIGAN_PIC = 1063        # unnamed_instance_23, the picture beside it


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad285-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["repo %s" % repo]

    def describe(tag):
        tv = state()["text_scenes"]["tree_view"]
        gig = [(l["name"], l["drawn"], l["state_off"], l.get("part_off"))
               for l in tv["layers"] if 1057 <= l["id"] <= 1063]
        p = tv.get("props") or {}
        notes.append("%s: frame %s, sel %s, peek %s, box %s, gigan layers %s"
                     % (tag, tv["frame"], tv["sel"], p.get("peek"), p.get("x"), gig))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", SELECT)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            time.sleep(1.5)
            describe("opened")

            def click(nid):
                row = page.locator('.tree-layers [data-node="%d"] .sc-t' % nid)
                row.scroll_into_view_if_needed()
                row.click()
                time.sleep(0.5)
                rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
                time.sleep(2.0)
            click(GIGAN_TEXT)
            describe("name box selected")
            click(GIGAN_PIC)
            describe("picture selected")
            page.mouse.move(5, 995)                     # no tooltip over the list
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out, "%s_select.png" % prefix))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
