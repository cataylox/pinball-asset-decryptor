# A multi-boot image as a base card plus an edits folder (PAD-241, was queue item 113)

## The problem

A compact multi-boot card stores a song-set variant as the byte ranges it changed (item 95's
store, item 107's deltas), so forty sets of one title fit a few GB of card. The input did not
shrink with it: `mkmulticard build --extra` and the tab's rows took whole card images, so every
set was built with Write, kept on the PC as a full 8 GB `.raw`, and fed in whole.

The app already writes the light form. Try it on the Emulate tab builds an **override set**
(`engine.write_overrides`): the card files the edits touch, whole, under their games-partition
paths, beside `overrides.json`, which names the card they were patched out of. `write_image`
and `write_overrides` share `_compute_patches`, so the set's files are the bytes the built card
would hold, in the files it would hold them in.

## The source spec

    <base.raw>+<edits folder>

`tools/spike2_emu/editsource.py` owns it. A path that exists is never split. Otherwise each '+'
is tried from the right until the left half is a file and the right half holds an
`overrides.json`, so a card with a '+' in its name stays a card, and a folder name with a '+'
still splits.

- **Manifest:** the base's cached manifest with the edited files re-described. Their sha256
  and size come from the folder (only they are hashed, and the digests are cached beside the
  tree cache). Mode, owner and mtime come from the base inode, since an in-place patch moves
  none of them.
- **Bytes:** `EditsReader` wraps the base's `Ext4Reader` and serves the edited inodes' content
  from the folder. The overlay is by inode, as the in-place patch is, so a hardlinked file is
  edited under every name. `disk_ranges` on an edited inode is refused; it has no place on
  the base card.
- **Stamp:** the base's size and mtime plus an `edits` token (the set's generation plus every
  file's size and mtime). `stamps_equal` compares that token, so an update never takes the
  pair for its base, or one set for another.
- **Where it goes:** anywhere mkmulticard takes an extra image (`--extra`, `--member`,
  `--members-list`, and verify's and update's lists). It forces `--layout store`: parts and
  multi copy a partition, and the pair has none. It is refused as the primary, because p1–p3
  are copied from the primary verbatim.

## Refusals (all in `editsource.check`)

- no `overrides.json`, or a stub one (`building`): a half-built set;
- a set version newer than this tool reads (update the app), or older (press Try it again);
- `card` size+mtime ≠ the base given: patched copies of another card's files;
- `run_card` ≠ `card`: its game program carries another build (PAD-172);
- custom modes (`modes` in the manifest, or `overrides.new`): they live on the system
  partition, and a member's system partition is never read;
- a file whose size or mtime moved since the build wrote it, or a file missing;
- a set with no files (that member is just the base);
- a file the base does not have (checked when the reader opens).

## The tab

- **Add base card + edits folder…** picks the card, then the folder.
- **Add random group from edits folders…** picks the card, then a folder whose subfolders are
  sets, and makes one random card of them (the forty-song-sets case).

Both check the pair with `editsource.check` before the row goes in. A row holding a pair locks
the compact tick, with its own tooltip. `wsl()` / `host_path()` translate each half. The row's
title is the base's, and its subtitle, or a group member's name, is the folder's. The menu's
auto art and sounds come off the base card (`selectmedia.open_card`).

## Proof

- `tests/test_multiboot_edits_source.py` (Windows and WSL): over the tiny ext4 fixture in a
  card table, base + edits describes the same manifest, and writes the same bytes through
  `apply_changes`, as a copy of the base with the same edits patched in place. Also covers
  the spec, the refusals, the stamps, and the layout and output guards.
- `tests/test_webui_multiboot.py`: the two add choices, the refusal text, the compact lock,
  and the tool arguments.
- Real card: see the ticket's ready note (Beatles 1.29.0, one stock raw + two sets, against
  the same card built from two full variant images).
