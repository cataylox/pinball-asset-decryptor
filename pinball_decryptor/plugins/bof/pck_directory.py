"""Read and rewrite BOF's Godot 4 PCK directory.

Two pack formats (``pack_format_version`` at header offset 4):

* **v3** (Godot 4.5: Dune, Winchester) - the directory is at the header's
  ``dir_offset``, after the file data.  Everything below is about v3.
* **v2** (Godot 4.0-4.4: Labyrinth's January 2026 code, PAD-223) - no
  ``dir_offset``; the u32 ``file_count`` and the entries follow the header
  at offset 96, before the file data at ``file_base``.  Same entry layout
  and same encryption flag.  ``rewrite`` keeps it in place: new entries are
  the same width, so the header and ``file_base`` never move.

Both BOF May/April builds ship a **Godot v3 PCK directory** at the byte
offset stored in the PCK header (header offset 32, a u64 ``dir_offset``).
The stock ``file_count`` slot at header offset 96 is 0 — which is why
GDRE/stock tools refuse the pack and why ``may_extractor`` falls back to
marker-scanning the inline sidecars — but the *running engine* (stock
Godot 4.5.2) reads the real directory at ``dir_offset`` and locates every
resource by an **absolute** offset stored there.  That is why a
size-changing repack that doesn't update this directory black-screens the
game: the engine reads shifted resources at stale offsets.

Two flavours (auto-detected from ``pack_flags`` bit0 = ``PACK_DIR_ENCRYPTED``):

* **Encrypted (Dune, magic ``GBOF``)** — the directory body after the
  cleartext ``file_count`` is wrapped in a Godot ``FileAccessEncrypted``
  blob ``[md5(16)][u64 plaintext_len][iv(16)][AES-256-CFB128 ciphertext]``.
  The AES key is *derived* from the binary's compiled-in
  ``script_encryption_key`` (a 32-byte ``.data`` constant) using a fixed
  ``Security::TOKEN`` table (a 32-byte ``.rodata`` constant) — the
  transform was recovered from the engine's own derivation code:
  ``v = (TOKEN[i] + 2*key[i]) | key[i]`` (NOT masked to a byte),
  ``out[i] = ((v << 4) | (v >> 4)) & 0xff``.  We discover both constants
  per-binary (no hard-coded offsets): TOKEN from the derivation-code
  fingerprint, ``script_encryption_key`` by brute-forcing 32-byte ``.data``
  windows against the directory's own md5 oracle.

* **Plaintext (Winchester, magic ``GDPC``, flag clear)** — the directory
  body is the raw entry table, no encryption, no key needed.

Directory body = ``file_count`` × entry, each:
``{u32 path_len (incl. NUL pad to 4), path bytes, u64 ofs, u64 size,
md5[16], u32 flags}``; the file's data lives at
``pck_start + file_base + ofs``.

``rewrite()`` produces a new binary with substituted files of *any* size:
every entry's ``ofs`` is shifted by the cumulative byte delta of edits
physically before it, each edited entry's ``size``/``md5`` is updated, the
body is re-serialised (and re-encrypted with the same key+iv, which is
byte-deterministic), the directory is re-pointed (header ``dir_offset`` +
trailer ``pck_size``), and the whole thing is streamed to disk.
"""

import hashlib
import os
import re
import struct
import sys

PACK_DIR_ENCRYPTED = 1   # pack_flags bit0
PACK_REL_FILEBASE = 2    # pack_flags bit1: file_base is pack-relative
V2_DIR_OFFSET = 96       # format v2: file_count right after the header

# Byte fingerprint of the engine's key-derivation arithmetic
# (lea eax,[rax+rcx*2]; or eax,ecx; mov r12d,eax; sar eax,4; shl r12d,4; or r12d,eax)
_KEY_XFORM_FP = bytes.fromhex("8d044809c84189c4c1f80441c1e40441" "09c4")
_COPY_CHUNK = 8 * 1024 * 1024


class DirectoryError(Exception):
    """Raised when the PCK directory can't be read or its key recovered."""


# ---------------------------------------------------------------------------
# Encryption-key recovery (encrypted directories only)
# ---------------------------------------------------------------------------

def _derive_key(sek, token):
    out = bytearray(32)
    for i in range(32):
        v = (token[i] + 2 * sek[i]) | sek[i]      # NOT masked to 8 bits
        out[i] = ((v << 4) | (v >> 4)) & 0xff
    return bytes(out)


def _aes_cfb(key, iv, data, encrypt=False):
    try:
        from Crypto.Cipher import AES   # pycryptodome; lazy import
    except ImportError:
        # the app's Linux has no pycryptodome (the emulator reads the
        # playfield picture there, PAD-257): slow, correct, pure Python
        from . import aes_py
        return aes_py.cfb128(key, iv, bytes(data), encrypt=encrypt)
    cipher = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128)
    return cipher.encrypt(data) if encrypt else cipher.decrypt(data)


def _aes_ecb_block(key, block16):
    try:
        from Crypto.Cipher import AES
    except ImportError:
        from . import aes_py
        return aes_py.ecb_encrypt_block(key, bytes(block16))
    return AES.new(key, AES.MODE_ECB).encrypt(block16)


def _lea_rip_target(binary, lo, hi):
    """Return the file offset loaded by the LAST ``lea reg,[rip+disp32]``
    in ``binary[lo:hi]`` (closest to ``hi``), or None.  Matches REX.W/.R
    (0x48/0x4c) + 0x8d + ModRM mod=00 rm=101 (``..000101`` -> the eight
    bytes 05/0d/15/1d/25/2d/35/3d).  The ELF is identity-mapped (vaddr ==
    file offset for the loaded binaries we read), so the target offset is
    ``insn_end + disp``."""
    found = None
    i = max(0, lo)
    end = min(hi, len(binary) - 7)
    while i < end:
        if binary[i] in (0x48, 0x4c) and binary[i + 1] == 0x8d \
                and (binary[i + 2] & 0xc7) == 0x05:
            disp = struct.unpack("<i", binary[i + 3:i + 7])[0]
            off = i + 7 + disp
            if 0 <= off <= len(binary) - 32:
                found = off
        i += 1
    return found


def _find_token(binary):
    """Locate the 32-byte Security::TOKEN by finding the key-derivation
    code fingerprint and decoding the ``lea r15,[rip+disp32]`` that loads
    TOKEN just before it.  Returns the bytes, or None.  (Dune/Winchester-era
    transform; see :func:`_derive_key`.)"""
    fp = binary.find(_KEY_XFORM_FP)
    if fp < 0:
        return None
    for back in range(max(0, fp - 220), fp):
        if binary[back:back + 3] == b"\x4c\x8d\x3d":   # lea r15, [rip+disp32]
            disp = struct.unpack("<i", binary[back + 3:back + 7])[0]
            off = back + 7 + disp                       # identity-mapped ELF
            if 0 <= off and off + 32 <= len(binary):
                return binary[off:off + 32]
    return None


# Godot-4.7 (Bon Jovi) directory-key derivation, recovered from
# FileAccessEncrypted::open_and_parse:
#     key[i] = ((CONST[i] | TOKEN[i]) + TOKEN[i]) ^ XOR      (i = 0..31)
# CONST is a 32-byte .data constant (brute-forced like the Dune script key),
# TOKEN a 32-byte .rodata table loaded by a ``lea`` just before the loop.
# The loop body is ``or r1,r2 ; add r1,r2 ; xor r1,imm8`` on the same two
# registers; we match it register-agnostically and read XOR + TOKEN from it.
_BJ_DERIV_RE = re.compile(rb"\x09(.)\x01\1\x83([\xf0-\xf7])(.)", re.DOTALL)


def _derive_key_bj(const, token, xor_imm):
    return bytes(
        (((const[i] | token[i]) + token[i]) ^ xor_imm) & 0xff
        for i in range(32))


def _exec_progbits(binary):
    """Yield (file_off, size) of executable PROGBITS sections (.text)."""
    if binary[:4] != b"\x7fELF":
        return
    try:
        e_shoff = struct.unpack("<Q", binary[0x28:0x30])[0]
        ent = struct.unpack("<H", binary[0x3a:0x3c])[0]
        num = struct.unpack("<H", binary[0x3c:0x3e])[0]
    except struct.error:
        return
    for i in range(num):
        sh = binary[e_shoff + i * ent: e_shoff + (i + 1) * ent]
        if len(sh) < 40:
            break
        sh_type = struct.unpack("<I", sh[4:8])[0]
        sh_flags = struct.unpack("<Q", sh[8:16])[0]
        sh_off = struct.unpack("<Q", sh[24:32])[0]
        sh_size = struct.unpack("<Q", sh[32:40])[0]
        if sh_type == 1 and (sh_flags & 0x4):           # PROGBITS + SHF_EXECINSTR
            yield sh_off, sh_size


def _find_bj_schemes(binary):
    """Yield ``(token_bytes, xor_imm)`` for every Godot-4.7 key-derivation
    loop found in the binary's executable sections."""
    ranges = list(_exec_progbits(binary))
    if not ranges:
        ranges = [(0, len(binary))]
    seen = set()
    for off, size in ranges:
        region = binary[off:off + size]
        for m in _BJ_DERIV_RE.finditer(region):
            xor_imm = m.group(3)[0]      # imm8 of `xor r32, imm8` (83 /6 ib)
            pos = off + m.start()
            tok_off = _lea_rip_target(binary, pos - 256, pos)
            if tok_off is None:
                continue
            token = bytes(binary[tok_off:tok_off + 32])
            key = (token, xor_imm)
            if key not in seen:
                seen.add(key)
                yield token, xor_imm


def _writable_progbits(binary):
    """Yield (file_off, size) of writable PROGBITS sections (.data) from
    the ELF section table — where the script_encryption_key constant lives."""
    if binary[:4] != b"\x7fELF":
        return
    try:
        e_shoff = struct.unpack("<Q", binary[0x28:0x30])[0]
        ent = struct.unpack("<H", binary[0x3a:0x3c])[0]
        num = struct.unpack("<H", binary[0x3c:0x3e])[0]
    except struct.error:
        return
    for i in range(num):
        sh = binary[e_shoff + i * ent: e_shoff + (i + 1) * ent]
        if len(sh) < 40:
            break
        sh_type = struct.unpack("<I", sh[4:8])[0]
        sh_flags = struct.unpack("<Q", sh[8:16])[0]
        sh_off = struct.unpack("<Q", sh[24:32])[0]
        sh_size = struct.unpack("<Q", sh[32:40])[0]
        if sh_type == 1 and (sh_flags & 0x1):           # PROGBITS + SHF_WRITE
            yield sh_off, sh_size


def _discover_key(binary, iv, ciphertext, plaintext_len, dir_md5):
    """Recover the directory AES key with no hard-coded offsets.

    The 32-byte constant (Dune's ``script_encryption_key`` / Bon Jovi's
    CONST) is brute-forced over the writable ``.data`` sections, using the
    directory's stored md5 as the success oracle.  Two key-derivation
    transforms are tried per candidate so one path serves every BoF build:
    the Dune/Winchester transform (TOKEN via :func:`_find_token`) and the
    Godot-4.7/Bon Jovi transform (TOKEN + XOR via :func:`_find_bj_schemes`).
    """
    # Bind each recovered TOKEN to a derive(sek)->key closure.
    derivers = []
    dune_tok = _find_token(binary)
    if dune_tok is not None:
        derivers.append(lambda sek, t=dune_tok: _derive_key(sek, t))
    for tok, xor_imm in _find_bj_schemes(binary):
        derivers.append(
            lambda sek, t=tok, x=xor_imm: _derive_key_bj(sek, t, x))
    if not derivers:
        raise DirectoryError(
            "couldn't find the key-derivation code — unknown BOF build?")

    full_ct = ciphertext[:((plaintext_len + 15) // 16 * 16)]
    ct16 = full_ct[:16]
    for sec_off, sec_size in _writable_progbits(binary):
        for w in range(sec_off, sec_off + sec_size - 31):
            sek = binary[w:w + 32]
            if len(set(sek)) < 24:        # a real 32-byte key has high diversity
                continue
            for derive in derivers:
                key = derive(sek)
                # CFB first block: pt[0:16] = ct[0:16] ^ AES_ECB(key, iv)
                f16 = bytes(a ^ b for a, b in zip(ct16, _aes_ecb_block(key, iv)))
                pl = struct.unpack("<I", f16[:4])[0]
                if not (4 < pl < 512):
                    continue
                # entry path should start with a printable res path char
                if not all(48 <= c < 123 or c in (46, 47, 95, 45)
                           for c in f16[4:11]):
                    continue
                body = _aes_cfb(key, iv, full_ct)[:plaintext_len]
                if hashlib.md5(body).digest() == dir_md5:
                    return key
    raise DirectoryError(
        "couldn't recover the directory AES key (script key not in .data?)")


# ---------------------------------------------------------------------------
# Directory model
# ---------------------------------------------------------------------------

class PckDirectory:
    """Parsed Godot v3 PCK directory + everything needed to rewrite it."""

    def __init__(self, binary_path, pck_off, base, flags, dir_off,
                 file_count, entries, encrypted, key, iv,
                 version=3, pck_size=None):
        self.binary_path = binary_path
        self.pck_off = pck_off          # file offset of the PCK section
        self.base = base                # file_base (offsets are relative to this)
        self.flags = flags
        self.dir_off = dir_off          # pck-relative directory offset
        self.file_count = file_count
        self.entries = entries          # list of dicts: praw/ofs/size/md5/flags
        self.encrypted = encrypted
        self.key = key                  # AES key (encrypted dirs) or None
        self.iv = iv                    # AES iv (encrypted dirs) or None
        self.version = version          # pack_format_version (2 or 3)
        self.pck_size = pck_size        # trailer pck_size (pck_off..end)

    def by_path(self):
        """Map pck-relative path (bytes, NUL-trimmed) -> entry dict."""
        return {e["praw"].rstrip(b"\x00"): e for e in self.entries}


def _serialize_body(entries):
    out = bytearray()
    for e in entries:
        out += struct.pack("<I", len(e["praw"]))
        out += e["praw"]
        out += struct.pack("<QQ", e["ofs"], e["size"])
        out += e["md5"]
        out += struct.pack("<I", e["flags"])
    return bytes(out)


def read(binary_path):
    """Parse the v3 PCK directory from a BOF binary.  Returns a
    ``PckDirectory`` or ``None`` if the binary has no usable v3 directory
    (e.g. the synthetic test stubs, or a pre-May pack).

    The binary is memory-mapped (not read into RAM) so this stays cheap on
    a 2.7 GB game on a low-memory machine — only the resident pages touched
    by the header parse, the key-derivation fingerprint scan, and the .data
    key brute are paged in."""
    import mmap
    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""
    f = open(long_prefix + os.path.abspath(binary_path), "rb")
    try:
        size = os.fstat(f.fileno()).st_size
        if size < 12:
            return None
        binary = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            return _parse(binary_path, binary)
        finally:
            binary.close()
    finally:
        f.close()


def _parse(binary_path, binary):
    if len(binary) < 12:
        return None
    pck_size = struct.unpack("<Q", binary[-12:-4])[0]
    pck_off = len(binary) - 12 - pck_size
    if pck_off < 0 or pck_off + 104 > len(binary):
        return None
    hdr = binary[pck_off:pck_off + 104]
    if hdr[:4] not in (b"GDPC", b"GBOF", b"RHBP"):
        return None
    version = struct.unpack("<I", hdr[4:8])[0]           # pack_format_version
    if version < 2:
        return None
    flags = struct.unpack("<I", hdr[20:24])[0]
    base = struct.unpack("<Q", hdr[24:32])[0]
    if version == 2:
        # Godot 4.0-4.4: no dir_offset field; the directory follows the
        # 16 reserved u32s at once.  Labyrinth's January 2026 code is one
        # (Godot 4.4.1, PAD-223).  Without PACK_REL_FILEBASE the stored
        # file_base is absolute in the file, not relative to the pack.
        dir_off = V2_DIR_OFFSET
        if not flags & PACK_REL_FILEBASE:
            base -= pck_off
        if not V2_DIR_OFFSET + 4 <= base <= pck_size:
            return None
        if struct.unpack("<I", binary[pck_off + dir_off:
                                      pck_off + dir_off + 4])[0] == 0:
            return None
    else:
        dir_off = struct.unpack("<Q", hdr[32:40])[0]
    if dir_off == 0 or pck_off + dir_off + 4 > len(binary):
        return None
    o = pck_off + dir_off
    file_count = struct.unpack("<I", binary[o:o + 4])[0]
    o += 4
    encrypted = bool(flags & PACK_DIR_ENCRYPTED)
    key = iv = None
    if encrypted:
        dir_md5 = binary[o:o + 16]
        plen = struct.unpack("<Q", binary[o + 16:o + 24])[0]
        iv = binary[o + 24:o + 40]
        ct = binary[o + 40:o + 40 + ((plen + 15) // 16 * 16)]
        key = _discover_key(binary, iv, ct, plen, dir_md5)
        body = _aes_cfb(key, iv, ct)[:plen]
        if hashlib.md5(body).digest() != dir_md5:
            raise DirectoryError("directory md5 mismatch after decrypt")
    else:
        body = binary[o:]

    entries = []
    p = 0
    for _ in range(file_count):
        pl = struct.unpack("<I", body[p:p + 4])[0]
        p += 4
        praw = body[p:p + pl]
        p += pl
        ofs, size = struct.unpack("<QQ", body[p:p + 16])
        p += 16
        md5 = body[p:p + 16]
        p += 16
        ef = struct.unpack("<I", body[p:p + 4])[0]
        p += 4
        entries.append({"praw": praw, "ofs": ofs, "size": size,
                        "md5": md5, "flags": ef})
    return PckDirectory(binary_path, pck_off, base, flags, dir_off,
                        file_count, entries, encrypted, key, iv,
                        version=version, pck_size=pck_size)


def rewrite(pckdir, substitutions, output_path, log_cb=None, progress_cb=None):
    """Write a new binary with ``substitutions`` applied, of any size.

    ``substitutions``: dict ``{ofs: new_bytes}`` keyed by the entry's
    original ``ofs`` (the data start, file_base-relative).  Files not in
    the dict keep their original bytes; everything physically after a
    grown/shrunk file is shifted and its directory ``ofs`` updated."""
    def _log(m, s="info"):
        if log_cb:
            log_cb(m, s)

    pck_off, base, dir_off = pckdir.pck_off, pckdir.base, pckdir.dir_off
    # subs sorted by physical offset, with (ofs, old_size, new_bytes)
    by_ofs = {e["ofs"]: e for e in pckdir.entries}
    subs = []
    for ofs, new_bytes in substitutions.items():
        e = by_ofs.get(ofs)
        if e is None:
            continue
        subs.append((ofs, e["size"], new_bytes))
    subs.sort()
    deltas = [(ofs, len(nb) - osz) for ofs, osz, nb in subs]
    total_delta = sum(d for _, d in deltas)

    def cum_delta(entry_ofs):
        return sum(d for ofs, d in deltas if ofs < entry_ofs)

    # Build the updated directory body in memory (small: ~0.6–3 MB).
    new_md5_by_ofs = {ofs: hashlib.md5(nb).digest() for ofs, _osz, nb in subs}
    new_size_by_ofs = {ofs: len(nb) for ofs, _osz, nb in subs}
    new_entries = []
    for e in pckdir.entries:
        ne = dict(e)
        if e["ofs"] in new_size_by_ofs:
            ne["size"] = new_size_by_ofs[e["ofs"]]
            ne["md5"] = new_md5_by_ofs[e["ofs"]]
        ne["ofs"] = e["ofs"] + cum_delta(e["ofs"])
        new_entries.append(ne)
    new_body = _serialize_body(new_entries)
    new_dir_off = dir_off + total_delta

    if pckdir.encrypted:
        pad = (16 - len(new_body) % 16) % 16
        new_ct = _aes_cfb(pckdir.key, pckdir.iv, new_body + b"\x00" * pad,
                          encrypt=True)
        dir_blob = (struct.pack("<I", pckdir.file_count)
                    + hashlib.md5(new_body).digest()
                    + struct.pack("<Q", len(new_body))
                    + pckdir.iv + new_ct)
    else:
        dir_blob = struct.pack("<I", pckdir.file_count) + new_body

    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""
    in_path = long_prefix + os.path.abspath(pckdir.binary_path)
    out_path = long_prefix + os.path.abspath(output_path)
    _log(f"Rewriting PCK directory ({len(subs)} substitution(s), "
         f"net {total_delta:+d} bytes)...")
    if pckdir.version == 2:
        return _rewrite_v2(pckdir, subs, dir_blob, total_delta,
                           in_path, out_path, progress_cb)

    pck_bytes_written = 0
    total_out = pck_off + new_dir_off + len(dir_blob) + 12

    with open(in_path, "rb") as src, open(out_path, "wb") as dst:
        def _copy(start, end):           # copy src[start:end] in chunks
            nonlocal pck_bytes_written
            src.seek(start)
            remaining = end - start
            while remaining > 0:
                chunk = src.read(min(_COPY_CHUNK, remaining))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
                pck_bytes_written += len(chunk)
                if progress_cb:
                    progress_cb(pck_bytes_written, total_out, "Writing binary…")

        # 1) ELF prefix + PCK header up to file_base, patching dir_offset.
        _copy(0, pck_off + 32)
        dst.write(struct.pack("<Q", new_dir_off))         # header offset 32
        pck_bytes_written += 8
        _copy(pck_off + 40, pck_off + base)

        # 2) File-data region [base, dir_off): verbatim except substitutions.
        cursor = base
        for ofs, old_size, new_bytes in subs:
            _copy(pck_off + cursor, pck_off + base + ofs)
            dst.write(new_bytes)
            pck_bytes_written += len(new_bytes)
            cursor = base + ofs + old_size
        _copy(pck_off + cursor, pck_off + dir_off)

        # 3) New directory, then the 12-byte embedded-PCK trailer
        # (<u64 pck_size><4-byte magic>).  pck_size spans pck_off..end of
        # the directory; the magic is preserved from the original.
        dst.write(dir_blob)
        new_pck_size = new_dir_off + len(dir_blob)
        src.seek(-4, os.SEEK_END)
        magic = src.read(4)
        dst.write(struct.pack("<Q", new_pck_size) + magic)

    return {"substitutions": len(subs), "net_delta": total_delta,
            "new_dir_off": new_dir_off, "new_pck_size": new_pck_size,
            "new_binary_size": pck_off + new_pck_size + 12}


def _rewrite_v2(pckdir, subs, dir_blob, total_delta, in_path, out_path,
                progress_cb):
    """``rewrite`` for a format v2 pack (Godot 4.0-4.4).  Its directory sits
    in front of the file data at header offset 96, and a new one is the
    same length as the old (same paths, fixed-width fields), so the header
    and ``file_base`` stay put: only the directory, the data and the
    trailer's ``pck_size`` change."""
    pck_off, base, dir_off = pckdir.pck_off, pckdir.base, pckdir.dir_off
    pck_end = pck_off + pckdir.pck_size
    if dir_off + len(dir_blob) > base:
        raise DirectoryError("the new directory would overrun the file data")
    total_out = pck_end + total_delta + 12
    written = 0

    with open(in_path, "rb") as src, open(out_path, "wb") as dst:
        def _copy(start, end):
            nonlocal written
            src.seek(start)
            remaining = end - start
            while remaining > 0:
                chunk = src.read(min(_COPY_CHUNK, remaining))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
                written += len(chunk)
                if progress_cb:
                    progress_cb(written, total_out, "Writing binary…")

        # 1) ELF prefix + header, the new directory, padding up to file_base.
        _copy(0, pck_off + dir_off)
        dst.write(dir_blob)
        written += len(dir_blob)
        _copy(pck_off + dir_off + len(dir_blob), pck_off + base)

        # 2) File data to the end of the pack, with the substitutions.
        cursor = base
        for ofs, old_size, new_bytes in subs:
            _copy(pck_off + cursor, pck_off + base + ofs)
            dst.write(new_bytes)
            written += len(new_bytes)
            cursor = base + ofs + old_size
        _copy(pck_off + cursor, pck_end)

        # 3) Trailer: <u64 pck_size><magic>, the magic preserved.
        new_pck_size = pckdir.pck_size + total_delta
        src.seek(-4, os.SEEK_END)
        magic = src.read(4)
        dst.write(struct.pack("<Q", new_pck_size) + magic)

    return {"substitutions": len(subs), "net_delta": total_delta,
            "new_dir_off": dir_off, "new_pck_size": new_pck_size,
            "new_binary_size": pck_off + new_pck_size + 12}
