"""Unit tests for the Barrels of Fun DDI (systemd disk image) container
reader used for Bon Jovi.

The real ``.fun`` is a GPT whose payload is a zstd-compressed EROFS holding a
second, uncompressed EROFS (the OS root) that carries the game binaries.  The
compressed decode path is validated against the real 6 GB image out-of-band;
here we build a *synthetic* nested DDI with an uncompressed EROFS so the GPT
parse, the EROFS inode/dir walk, and the nested extraction all run for real in
CI without the big file or an EROFS compressor.
"""

import struct

from pinball_decryptor.plugins.bof import ddi_container as dc

_BLK = 4096


def _build_erofs(tree):
    """Build a minimal uncompressed EROFS image for *tree*.

    *tree* is a dict mapping a name to either ``bytes`` (a file) or another
    dict (a directory).  Returns the image bytes.  Inodes use the 32-byte
    compact form with plain (layout 0, block-aligned) data; directories are
    assumed to fit in a single block.
    """
    # Flatten the tree into nodes, assigning a nid (inode table lives in
    # block 0 starting at byte 2048 -> nids from 64 up) and, later, a data
    # block each.
    nodes = []          # list of dicts: {is_dir, children|data, nid, blk}

    def alloc(node):
        nid = 64 + len(nodes)
        rec = {"nid": nid, "node": node}
        nodes.append(rec)
        if isinstance(node, dict):
            rec["children"] = {}
            for name, child in node.items():
                rec["children"][name] = alloc(child)
        return rec

    root = alloc(tree)

    # Assign one+ data block(s) to every node, after the inode table (block 0).
    next_blk = 1
    for rec in nodes:
        rec["blk"] = next_blk
        node = rec["node"]
        if isinstance(node, dict):
            next_blk += 1                      # one dir block
        else:
            next_blk += (len(node) + _BLK - 1) // _BLK or 1

    total = next_blk * _BLK
    buf = bytearray(total)

    # Superblock at 1024.
    struct.pack_into("<I", buf, 1024 + 0, dc._EROFS_MAGIC)
    buf[1024 + 12] = 12                        # blkszbits -> 4096
    struct.pack_into("<H", buf, 1024 + 14, root["nid"])   # root_nid
    struct.pack_into("<I", buf, 1024 + 40, 0)             # meta_blkaddr

    for rec in nodes:
        node = rec["node"]
        ino_off = rec["nid"] * 32              # meta=0
        is_dir = isinstance(node, dict)
        mode = (0o040000 | 0o755) if is_dir else (0o100000 | 0o644)
        if is_dir:
            # directory block: dirent array + names
            block = rec["blk"] * _BLK
            ents = list(rec["children"].items())
            dirent_sz = 12 * len(ents)
            names = bytearray()
            dirents = bytearray()
            for name, child in ents:
                noff = dirent_sz + len(names)
                ft = 2 if isinstance(child["node"], dict) else 1
                dirents += struct.pack("<QHBB", child["nid"], noff, ft, 0)
                names += name.encode("latin1")
            blob = bytes(dirents + names)
            buf[block:block + len(blob)] = blob
            size = len(blob)
        else:
            block = rec["blk"] * _BLK
            buf[block:block + len(node)] = node
            size = len(node)
        # compact inode: fmt(layout 0, not ext)=0, xattr=0, mode, nlink, size, _, i_u=blk
        struct.pack_into("<H", buf, ino_off + 0, 0)       # i_format (plain)
        struct.pack_into("<H", buf, ino_off + 2, 0)       # i_xattr_icount
        struct.pack_into("<H", buf, ino_off + 4, mode)
        struct.pack_into("<H", buf, ino_off + 6, 1)       # i_nlink
        struct.pack_into("<I", buf, ino_off + 8, size)
        struct.pack_into("<I", buf, ino_off + 16, rec["blk"])  # i_u.raw_blkaddr
    return bytes(buf)


def _build_gpt(payload, part_name="bof-update"):
    """Wrap *payload* bytes in a minimal GPT at LBA 2048."""
    lba = 512
    part_lba = 2048
    pesz = 128
    npe = 1
    pe_lba = 2
    nlba = (len(payload) + lba - 1) // lba
    total_lba = part_lba + nlba + 34
    disk = bytearray(total_lba * lba)
    # protective MBR left mostly empty (our parser only reads the GPT header)
    # GPT header at LBA 1
    h = bytearray(92)
    h[0:8] = b"EFI PART"
    struct.pack_into("<QII", h, 72, pe_lba, npe, pesz)
    disk[lba:lba + 92] = h
    # partition entry at LBA 2
    e = bytearray(pesz)
    e[0:16] = bytes(range(1, 17))              # non-zero type GUID
    e[16:32] = bytes(range(17, 33))            # unique GUID
    struct.pack_into("<QQ", e, 32, part_lba, part_lba + nlba - 1)
    e[56:56 + len(part_name) * 2] = part_name.encode("utf-16le")
    disk[pe_lba * lba:pe_lba * lba + pesz] = e
    disk[part_lba * lba:part_lba * lba + len(payload)] = payload
    return bytes(disk)


def _nested_fun(game_files):
    """A synthetic ``.fun``: GPT -> outer EROFS -> inner root EROFS whose
    /usr/lib/game holds *game_files* ({name: bytes})."""
    inner = _build_erofs({"usr": {"lib": {"game": dict(game_files)}}})
    outer = _build_erofs({
        "bon-jovi_test.efi": b"UKI-placeholder",
        "bon-jovi_test.img.root-x86-64": inner,
    })
    return _build_gpt(outer)


def test_is_ddi_detects_gpt_erofs(tmp_path):
    fun = tmp_path / "bon-jovi_test.fun"
    fun.write_bytes(_nested_fun({"BonJovi.x86_64": b"GODOTBINARY" * 100}))
    assert dc.is_ddi(str(fun))
    # a plain non-GPT file is not a DDI
    other = tmp_path / "dune.fun"
    other.write_bytes(b"\x00" * 100000)
    assert not dc.is_ddi(str(other))


def test_extract_game_binaries(tmp_path):
    big = bytes((i * 7) & 0xFF for i in range(9000))     # spans >1 block
    games = {"BonJovi.x86_64": big, "JayAndBob.x86_64": b"second game"}
    fun = tmp_path / "bon-jovi_test.fun"
    fun.write_bytes(_nested_fun(games))

    out = tmp_path / "out"
    written = dc.extract_game_binaries(str(fun), str(out))
    names = {__import__("os").path.basename(p) for p in written}
    assert names == {"BonJovi.x86_64", "JayAndBob.x86_64"}
    assert (out / "BonJovi.x86_64").read_bytes() == big
    assert (out / "JayAndBob.x86_64").read_bytes() == b"second game"
