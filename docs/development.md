# Development

[← Back to the README](../README.md)

This app is a unified replacement for separate decryptor apps that all shared
the same GUI shell, queue-based pipeline contract, checksum tracking,
and mod-pack workflow. Each manufacturer is a plugin under
[pinball_decryptor/plugins/](../pinball_decryptor/plugins/); the shared shell
lives in [pinball_decryptor/core/](../pinball_decryptor/core/) and the
web UI in [pinball_decryptor/webui/](../pinball_decryptor/webui/).

## Running from source

```bash
git clone https://github.com/davidvanderburgh/pinball-asset-decryptor.git
cd pinball-asset-decryptor
pip install -r requirements.txt
pip install pycryptodome UnityPy fsb5 pyogg   # only needed for Spooky
python -m pinball_decryptor
```

Or double-click [Pinball Asset Decryptor.pyw](../Pinball Asset Decryptor.pyw)
on Windows / [launch.vbs](../launch.vbs) for a no-console launch.

## Architecture

The app is a web page in a native window (Edge WebView2 on Windows,
WKWebView on macOS, Qt WebEngine on Linux) over a thin Python shell that
loads manufacturer plugins:

```
pinball_decryptor/
├── core/                         # manufacturer-agnostic shell
│   ├── pipeline_base.py          # 4-callback pipeline contract
│   ├── checksums.py              # baseline .checksums.md5 generator
│   ├── modpack.py                # mod-pack zip export/import
│   ├── executor.py               # WSL/Mac/Native subprocess wrapper
│   ├── updater.py                # GitHub release-check
│   ├── clonezilla.py             # generic gunzip+debugfs ISO extraction
│   └── registry.py               # Manufacturer ABC + plugin discovery
├── webui/                        # the UI: a web page in a native window
│   ├── host.py                   # local server + the native window (pywebview)
│   ├── window.py                 # the shell: manufacturer, project, log, tabs
│   ├── tabs/                     # one service per tab (Python), driving...
│   └── static/                   # ...the page (plain JavaScript, no build step)
├── plugins/
│   ├── ap/                       # American Pinball (AES-256 .pkg -> zip)
│   ├── bof/                      # Barrels of Fun (gpg + GDRE Tools)
│   ├── cgc/                      # Chicago Gaming Company (nested .img -> ext4)
│   ├── dp/                       # Dutch Pinball (TBL zip deltas + AAIW Clonezilla)
│   ├── jjp/                      # Jersey Jack Pinball (+ private Docker)
│   ├── pb/                       # Pinball Brothers
│   ├── spooky/                   # Spooky Pinball (+ private Docker)
│   ├── stern/                    # Stern Spike 2 (ext4 card; image.bin codec via unicorn)
│   └── williams/                 # WPC-era (static ROM scrape + PinMAME capture)
├── app.py                        # controller — wires GUI ↔ plugins
└── icon.{ico,png}
```

For a deep dive on any one plugin — its container/encryption format, extract and
write pipelines, audio handling, detection, and gotchas — see the per-manufacturer
architecture docs in [docs/architecture/](../docs/architecture/README.md).

The Spike 2 emulator itself is deliberately *not* part of the app. It lives in
[`tools/spike2_emu/`](../tools/spike2_emu) as a rig of shell scripts, `LD_PRELOAD`
hardware shims and a native GL host that run inside WSL; the Emulate tab
(`webui/tabs/emulate.py`)
only starts it, stops it and reports what it is doing. See that folder's README
for how the shims work and which titles boot.

Each plugin subclasses [`Manufacturer`](../pinball_decryptor/core/registry.py) and
sets a few attributes — `key`, `display`, `games`, `capabilities`,
`input_spec`, plus `extract_phases` / `write_phases` for the GUI's phase
indicator. Then it implements `detect(path)` and the pipeline factories
appropriate for its capabilities.

Pipelines all speak the same callback contract:

```python
log_cb(text, level)              # append to log pane ("info"/"success"/"error")
phase_cb(index)                  # light up phase indicator N
progress_cb(current, total, desc) # drive the progress bar
done_cb(success, summary)        # terminal message
```

Settings persist per-manufacturer at
`%APPDATA%\pinball_decryptor\settings.json` (or
`~/Library/Application Support/pinball_decryptor/` on macOS,
`~/.config/pinball_decryptor/` on Linux), keyed by mfr key:

```json
{
  "theme": "dark",
  "last_manufacturer": "spooky",
  "manufacturers": {
    "pb":     {"extract_input": "...", "extract_output": "...", ...},
    "spooky": {"extract_input": "...", ...}
  }
}
```

A path you've browsed to under one manufacturer doesn't bleed into
another's saved settings — the App's save logic validates the path with
that manufacturer's `detect()` before persisting.

## Adding a new manufacturer plugin

1. Copy [plugins/pb/](../pinball_decryptor/plugins/pb/) to `plugins/<mfr>/`.
2. Replace [games.py](../pinball_decryptor/plugins/pb/games.py) with that
   manufacturer's GAME_DB.
3. Rewrite [formats.py](../pinball_decryptor/plugins/pb/formats.py) for that
   manufacturer's detection logic.
4. Lift the pipelines from the upstream decryptor into
   [pipeline.py](../pinball_decryptor/plugins/pb/pipeline.py); change imports to
   use `...core.checksums`, `...core.tar_utils`, etc. Lift any
   format-specific helpers (`audio.py`, `crypto.py`, `godot.py`, etc.)
   into the plugin directory alongside.
5. Update [manufacturer.py](../pinball_decryptor/plugins/pb/manufacturer.py) —
   change `key`, `display`, `capabilities`, `input_spec`, `extract_phases`,
   `write_phases`, `detect`, factory methods, `extract_input_help`,
   `write_install_help`.
6. Append `"pinball_decryptor.plugins.<mfr>"` to `_PLUGIN_MODULES` in
   [core/registry.py](../pinball_decryptor/core/registry.py).
7. Add a manufacturer entry to the prereq manifest in
   [installer/install_prerequisites.ps1](../installer/install_prerequisites.ps1).
8. Smoke-test: load all plugins, run `detect()` against real sample files,
   instantiate the pipelines.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests
```

The suite exercises the full Extract → Write round-trip per manufacturer
against synthetic fixtures generated at test time — no real game files
are shipped or required. Coverage:

| Manufacturer | Tested | How |
|---|---|---|
| American Pinball | Detection (filename + key-validated probe) + Extract + Write round-trip | Synthetic `.pkg` (AES-256-CBC ZIP) encrypted with the plugin's own universal key; real 6-image regression (Houdini, Oktoberfest, Hot Wheels, LOV, Tank, BBQ) is local-only — packages are 1.5–6.7 GB each |
| Barrels of Fun | Extract + Write round-trip, all 3 games | Synthetic `.fun` (gpg-symmetric tar.gz) — *skipped automatically when gpg isn't installed* |
| Chicago Gaming Company | Detection (filename + MBR signature) + contract + JPS .bnk extract/repack round-trip on synthetic banks | Full Extract walks 3 nested layers of ext4 disk images and needs WSL + a real installer .img (7-15 GB), not testable in CI; the JPS sound-bank extractor/repacker is unit-tested against synthetic in-memory bnks |
| Jersey Jack | Detection + write-output-rename wrapper | Full Extract needs WSL + real ISO (gigabytes), not testable in CI |
| Pinball Brothers | Extract + Write round-trip, all 4 games | Synthetic `.upd` (gzip+tar) |
| Spooky Pinball | Extract + Write round-trip for `.ed`, `.scooby`, `.looney`, P3 `.zip`, `.pkg` (RM, AC) | Synthetic format-correct files; AES rounds use the known plugin keys |
| Williams (WPC) | Static extract end-to-end on Fish Tales + Attack From Mars; per-game switch-profile + game-script contract validation across all 41 titles | Synthetic ROM zips with valid WPC font/animation tables; PinMAME capture path needs libpinmame + a real ROM so it's `@pytest.mark.requires_libpinmame` and skipped in CI |

Plus: per-mfr contract validation (capabilities, prereqs, phase labels,
game lists), GUI smoke (picker, mfr switch, per-mfr log persistence,
Back navigation), and `detect()` against synthetic filenames.

[CI runs this matrix on every push + PR](../.github/workflows/test.yml):

| Runner | gpg |
|---|---|
| `ubuntu-latest` | apt |
| `macos-latest` | brew |

There is no Windows runner: the release flow's ship gate is the full suite
green on the developer's own Windows machine, and a Windows CI job only
repeated that check on the slowest, scarcest runner.

Tests that need WSL or Docker (full Clonezilla / JJP extraction) are
marked `@pytest.mark.requires_wsl` / `requires_docker` and skip
automatically when those aren't available. Adding new manufacturers
should come with at least a detection test + a contract test in
[tests/](../tests/).

## Building installers locally

### Windows

```powershell
# Requires: Python 3.10+, Inno Setup 6
installer\build.ps1
# Output: installer\Output\Pinball_Asset_Decryptor_vX.Y.Z_Windows.exe
```

### macOS

```bash
# Requires: Python 3.10+, brew install create-dmg
bash installer/build_macos.sh
# Output: installer/Output/Pinball_Asset_Decryptor_vX.Y.Z_macOS_<arch>.dmg
# (<arch> = AppleSilicon or Intel — PyInstaller targets the host arch,
#  so build on the kind of Mac you want to ship for)
```

### Linux

```bash
# Requires: Python 3.10+, wget (for appimagetool fetch)
#   apt-get install wget
bash installer/build_linux.sh
# Output: installer/Output/Pinball_Asset_Decryptor_vX.Y.Z_Linux_x86_64.AppImage
```

CI does all three automatically on a `v*` tag push and uploads to a
GitHub release. See [.github/workflows/release.yml](../.github/workflows/release.yml).

To cut a release: use the `/release` slash command in Claude Code
(`.claude/commands/release.md`), which bumps `__version__`, audits the
README for content drift, runs the test suite, commits, pushes,
tags, and publishes the GitHub release in the right order — designed
to never again ship a tag where `__version__` lags the tag string.
