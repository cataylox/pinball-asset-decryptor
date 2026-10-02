# Bon Jovi (Barrels of Fun) — extract support + the image-build wall

Bon Jovi (released Oct 2026) is the first Barrels of Fun title to drop the old
GPG-symmetric `.fun` (a passphrase-protected gzip tarball) for a **signed
systemd Discoverable Disk Image**. Extracting its assets works fully; building
an *installable* update does not, and cannot without either the vendor's signing
key or physical access to a machine, so edits can't be applied back yet. This
note records the format, what the plugin now does, and the realistic path to
asset mods.

## Container format

`bon-jovi_YYYY.MM.DD.fun` is a **GPT disk image** (systemd DDI):

| partition | type | contents |
|-----------|------|----------|
| `bof-update` | root-x86-64 | EROFS (zstd + big-pcluster), holds the payload files |
| `root-x86-64-verity` | verity | dm-verity hash tree for the payload |
| `root-x86-64-verity-sig` | verity-sig | JSON `{rootHash, certificateFingerprint, signature}`, PKCS7 signed by `CN=Barrels of Fun LLC` |

The payload EROFS holds exactly two files: a UKI (`*.efi`, kernel+initrd,
unsigned) and a second, **uncompressed** EROFS (`*.img.root-x86-64`, ~7 GB) that
is the OS root. The game binaries live in that inner root at
`/usr/lib/game/*.x86_64` (`BonJovi.x86_64` ~5.9 GB, plus a bundled second title
`JayAndBob.x86_64`).

WSL has no EROFS driver, so [`ddi_container.py`](../../pinball_decryptor/plugins/bof/ddi_container.py)
is a pure-Python reader: it parses the GPT, reads the outer EROFS, and
decompresses it on demand only over the byte ranges the inner root's inodes
point at, streaming each game binary straight to disk (no 7 GB intermediate,
flat peak memory). Supports the exact EROFS subset mkosi emits: compact 2B/4B
z_erofs indices, big pclusters, zstd frames, and the ZERO_PADDING feature
(frames right-aligned in their pcluster).

## The PCK: new magic + new key

`BonJovi.x86_64` is a **Godot 4.7.2** export with an appended PCK, same shape as
Dune's encrypted v3 directory but with two changes that made
`pck_directory` refuse it:

- **Magic `RHBP`** at the header and trailer (was `GDPC`/`GBOF`). Now accepted.
- **New directory-key derivation.** The directory is still a
  `FileAccessEncrypted` blob (`[md5][u64 len][iv][ct]`, AES-256-CFB) whose key
  is derived from two in-binary constants, but the transform changed from Dune's
  to:

      key[i] = ((CONST[i] | TOKEN[i]) + TOKEN[i]) ^ 0x5d      (i = 0..31)

  `CONST` is a 32-byte `.data` constant (brute-forced over the writable sections
  against the directory md5 oracle, like Dune's script key); `TOKEN` is a
  32-byte `.rodata` table loaded by a `lea` just before the derivation loop. The
  loop (`or; add; xor imm8` on one register pair) is matched
  register-agnostically, and both the Dune and Bon Jovi transforms are tried per
  candidate, so one path serves every BoF build and survives a recompile that
  reshuffles registers. Recovered from `try_open_pack` /
  `FileAccessEncrypted::open_and_parse` in the engine; verified against the real
  binary (key in ~4 s, all 2980 entries md5-checked).

From the recovered binary onward the existing `may_extractor` (directory path)
+ `source_converter` chain is unchanged.

## What works: extract (to view or reuse)

Proven end-to-end on the real image: DDI unwrap -> largest binary -> RHBP
directory -> **2980 files (5.78 GB) extracted, 2916 md5-verified** ->
**970 decoded assets, 0 conversion failures** (560 `.wav`, 376 `.webp`,
21 `.ogg`, 13 `.ttf`), plus 52 standalone `.ogv` mode videos. (64 directory
entries fail their md5 — all `.gd`/`.gd.uid` script/uid sidecars, not media;
the media verify and convert cleanly.)

The decoded files are editable, but there is nothing to apply them to yet: the
Write/build step is walled (below), so for now extraction is useful for viewing
and reusing assets (for example the video library) or staging mods for when
image building is unlocked, not for modding a running machine.

Detection: `bon-jovi_*.fun` by name, with a GPT+EROFS content sniff as a
fallback for a renamed file.

## What's blocked: building an installable update

The `ModifyPipeline` refuses Bon Jovi with a clear message. Building an
installable `.fun` would mean re-signing the dm-verity root hash with the
vendor's key (we don't have it) or getting our own cert into the machine's
verity trust store (a single file, `/usr/lib/verity.d/barrels-of-fun.crt`).
The whole trust path was audited: the USB/network updater mounts with
`systemd-dissect --image-policy root=signed` (fail-closed, hardcoded), and
systemd 261's own verity verification is the standard secure idiom
(`PKCS7_verify` against the on-disk cert dirs, embedded certs ignored). There is
no software-only remote/USB bypass.

## Emulation

Also not available yet. The Emulate (BoF) tab runs the game on the PC against
emulated FAST boards, but its decrypt step uses the GPG flow (`watch.sh` with
`title:passphrase`), which Bon Jovi has no key for, and there is no hardware
profile (`tools/bof_emu/profiles/bonjovi.json`) describing its boards/switches.
The tab guards Bon Jovi up front with a clear message (`BONJOVI_EMU`) instead of
failing deep in `watch.sh`. Wiring it would mean teaching the rig's decrypt the
DDI unwrap (reuse `ddi_container`) and building a profile from a real machine's
drive image, which is folded into the same volunteer ask below.

## The realistic path (and the volunteer call-to-action)

The installed machine **boots completely unsigned**: kernel cmdline
`root=PARTLABEL=... ro` with no verity, and the UKI carries no signature
(Secure Boot effectively off). The signature only guards the *update transport*.
So a modified root written **directly to the machine's NVMe** boots as-is — no
vendor key, no updater. That makes the volunteer ask simple and shown in the app
(Image Info / Write): image your machine's internal NVMe and send it, and ideally
confirm a modified image can be written back and boots. The `.fun` already gives
us all the shipped software; what a drive image adds is the live partition layout
and a base to modify in place.

## Key files

- [`ddi_container.py`](../../pinball_decryptor/plugins/bof/ddi_container.py) — GPT + nested EROFS reader; `extract_game_binaries`, `is_ddi`.
- [`pck_directory.py`](../../pinball_decryptor/plugins/bof/pck_directory.py) — `RHBP` magic + `_derive_key_bj` / `_find_bj_schemes` key recovery.
- [`pipeline.py`](../../pinball_decryptor/plugins/bof/pipeline.py) — `detect_game` (bonjovi), `_extract_ddi_binaries`, the DDI/GPG branch, and the Write refusal.
- [`games.py`](../../pinball_decryptor/plugins/bof/games.py) — the `bonjovi` entry (`container: "ddi"`, no passphrase).
- [`manufacturer.py`](../../pinball_decryptor/plugins/bof/manufacturer.py) — `BONJOVI_*` status strings, `image_info` notice, help text.
- Tests: [`test_bof_ddi.py`](../../tests/test_bof_ddi.py) (synthetic nested DDI + messaging), [`test_bof_pck_directory.py`](../../tests/test_bof_pck_directory.py) (RHBP + BJ key, crafted ELF).
