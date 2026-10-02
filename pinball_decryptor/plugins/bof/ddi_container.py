"""Unwrap a Barrels of Fun systemd-DDI ``.fun`` update image.

Bon Jovi (2026) abandoned the old GPG-symmetric tarball ``.fun`` for a
systemd Discoverable Disk Image: a GPT whose payload partition
(``bof-update``) is an **EROFS** (zstd + big-pcluster) holding exactly two
files -- a UKI (``*.efi``) and a second, *uncompressed* EROFS
(``*.img.root-x86-64``) that is the OS root.  The game binaries live in that
inner root at ``/usr/lib/game/*.x86_64``.

This module extracts those game binaries with no external tools (WSL has no
EROFS driver) and without materialising the 7 GB inner root: the outer
EROFS is decompressed on demand, only over the byte ranges the inner root's
inodes actually point at, and each game binary is streamed straight to disk.

Only the read path is implemented -- repacking a DDI (rebuilding both EROFS
layers + dm-verity + the vendor signature) is out of scope and, per PAD-308,
not possible without the vendor's signing key.
"""

import os
import struct

# EROFS on-disk constants
_EROFS_MAGIC = 0xE0F5E1E2
_EROFS_SB_OFF = 1024
_CBLKCNT = 1 << 11            # z_erofs "chunk count" marker bit in a nonhead lcluster
_T_PLAIN, _T_HEAD1, _T_NONHEAD, _T_HEAD2 = 0, 1, 2, 3

# GPT constants
_GPT_SIG = b"EFI PART"
_LBA = 512


class DdiError(Exception):
    """Raised when a ``.fun`` is not a readable BoF DDI."""


# ---------------------------------------------------------------------------
# GPT
# ---------------------------------------------------------------------------

def _find_payload_partition(f):
    """Return (byte_offset, byte_length) of the GPT partition that holds the
    update payload (the first/largest data partition; BoF labels it
    ``bof-update``).  Raises :class:`DdiError` if the file is not a GPT."""
    f.seek(_LBA)
    hdr = f.read(92)
    if hdr[:8] != _GPT_SIG:
        raise DdiError("not a GPT disk image (no 'EFI PART' header)")
    pe_lba, npe, pesz = struct.unpack_from("<QII", hdr, 72)
    f.seek(pe_lba * _LBA)
    table = f.read(npe * pesz)
    best = None
    for i in range(npe):
        e = table[i * pesz:(i + 1) * pesz]
        if e[:16] == b"\x00" * 16:
            continue
        first, last = struct.unpack_from("<QQ", e, 32)
        name = e[56:128].decode("utf-16le").rstrip("\x00")
        length = (last - first + 1) * _LBA
        # Prefer a partition literally named for the update; else the largest.
        score = (name.lower().startswith("bof") or "update" in name.lower(),
                 length)
        if best is None or score > best[0]:
            best = (score, first * _LBA, length)
    if best is None:
        raise DdiError("GPT has no partitions")
    return best[1], best[2]


# ---------------------------------------------------------------------------
# EROFS reader (over an arbitrary read(off, n) backend)
# ---------------------------------------------------------------------------

class Erofs:
    """Minimal read-only EROFS reader.

    ``read(off, n)`` supplies filesystem bytes (``off`` relative to the EROFS
    superblock's partition).  Supports flat (uncompressed) inodes and the
    z_erofs compact-index layout with big pclusters, zstd frames and the
    ZERO_PADDING feature -- the exact subset BoF's mkosi images use.
    """

    def __init__(self, read):
        self._read = read
        sb = read(_EROFS_SB_OFF, 128)
        if struct.unpack_from("<I", sb, 0)[0] != _EROFS_MAGIC:
            raise DdiError("bad EROFS superblock magic")
        self.blkszbits = sb[12]
        self.blk = 1 << self.blkszbits
        self.root_nid = struct.unpack_from("<H", sb, 14)[0]
        self.meta = struct.unpack_from("<I", sb, 40)[0]
        self._zstd = None

    def _zstd_dctx(self):
        if self._zstd is None:
            import zstandard
            self._zstd = zstandard.ZstdDecompressor()
        return self._zstd

    # -- inodes -----------------------------------------------------------
    def inode(self, nid):
        off = self.meta * self.blk + nid * 32
        h = self._read(off, 64)
        fmt = struct.unpack_from("<H", h, 0)[0]
        xic = struct.unpack_from("<H", h, 2)[0]
        mode = struct.unpack_from("<H", h, 4)[0]
        ext = fmt & 1
        layout = (fmt >> 1) & 7
        if ext:
            size = struct.unpack_from("<Q", h, 8)[0]
            raw = struct.unpack_from("<I", h, 16)[0]
            isz = 64
        else:
            size = struct.unpack_from("<I", h, 8)[0]
            raw = struct.unpack_from("<I", h, 16)[0]
            isz = 32
        xsz = 0 if xic == 0 else 12 + (xic - 1) * 4
        return {"nid": nid, "off": off, "layout": layout, "mode": mode,
                "size": size, "raw": raw, "isz": isz, "xsz": xsz,
                "inline_off": off + isz + xsz}

    # -- flat (uncompressed) data ----------------------------------------
    def _read_flat(self, ino, start, n):
        blk, size, lay = self.blk, ino["size"], ino["layout"]
        if lay == 0:                               # plain, block-aligned
            return self._read(ino["raw"] * blk + start, n)
        if lay == 2:                               # inline tail after the inode
            nblocks = size // blk
            out = b""
            if start < nblocks * blk:
                m = min(n, nblocks * blk - start)
                out += self._read(ino["raw"] * blk + start, m)
                start += m
                n -= m
            if n > 0:
                out += self._read(ino["inline_off"] + (start - nblocks * blk), n)
            return out
        raise DdiError("inode layout %d is compressed; use file_reader" % lay)

    def listdir(self, ino):
        blk = self.blk
        data = self._read_flat(ino, 0, ino["size"])
        ents = []
        for b in range(0, len(data), blk):
            block = data[b:b + blk]
            if len(block) < 12:
                break
            name0 = struct.unpack_from("<H", block, 8)[0]
            cnt = name0 // 12
            for i in range(cnt):
                nid, noff, _ft = struct.unpack_from("<QHB", block, i * 12)
                nend = (struct.unpack_from("<H", block, (i + 1) * 12 + 8)[0]
                        if i + 1 < cnt else len(block))
                name = block[noff:nend].split(b"\x00")[0].decode("latin1")
                ents.append((name, nid))
        return ents

    def resolve(self, path):
        """Return the inode dict for an absolute path, or None."""
        nid = self.root_nid
        for part in [p for p in path.split("/") if p]:
            d = dict(self.listdir(self.inode(nid)))
            if part not in d:
                return None
            nid = d[part]
        return self.inode(nid)

    # -- compressed data: build a random-access reader --------------------
    def _zmap(self, ino):
        """Return the compression map header fields for a compressed inode."""
        end = ino["off"] + ino["isz"] + ino["xsz"]
        mh_off = (end + 7) & ~7
        h = self._read(mh_off, 8)
        advise = struct.unpack_from("<H", h, 4)[0]
        alg = h[6]
        clbits = h[7]
        lcb = self.blkszbits + (clbits & 7)
        if lcb != 12:
            raise DdiError("unsupported lclusterbits")
        if advise & 0x28:                          # fragments / ztailpacking
            raise DdiError("unsupported EROFS compression feature")
        return {"ebase": mh_off + 8, "advise": advise,
                "alg0": alg & 15, "alg1": alg >> 4, "lcb": lcb}

    def _extents(self, ino):
        """Yield (logical_addr, logical_len, phys_off, phys_len, alg) for every
        pcluster of a compact-index (layout 1/3) inode, in order."""
        blk, size = self.blk, ino["size"]
        z = self._zmap(ino)
        lcb, ebase, advise = z["lcb"], z["ebase"], z["advise"]
        big = bool(advise & 0x2)
        totalidx = (size + blk - 1) // blk
        lobits = max(lcb, 12)
        # compact 2-byte / 4-byte index packing (compat feature bit 0)
        c4b_init = (32 - ebase % 32) // 4
        if c4b_init == 8:
            c4b_init = 0
        if (advise & 0x1) and c4b_init < totalidx:
            c2b = ((totalidx - c4b_init) // 16) * 16
        else:
            c2b = 0
        nbytes = c4b_init * 4 + c2b * 2 + (totalidx - c4b_init - c2b) * 4
        nbytes = ((nbytes + 31) // 32) * 32 + 32
        raw = self._read(ebase, nbytes)

        ents = [None] * totalidx
        packinfo = [None] * totalidx

        def decode(lcn0, count, pos0, ashift):
            vcnt = 2 if ashift == 2 else 16
            packsz = vcnt << ashift
            encodebits = (packsz - 4) * 8 // vcnt
            for k in range(count):
                lcn = lcn0 + k
                pos = pos0 + k * (1 << ashift)
                pstart = (pos // packsz) * packsz
                i = (pos - pstart) >> ashift
                rel = pstart - ebase
                pack = raw[rel:rel + packsz]
                bitpos = encodebits * i
                v = struct.unpack_from("<I", pack, bitpos // 8)[0] >> (bitpos & 7)
                lo = v & ((1 << lobits) - 1)
                t = (v >> lobits) & 3
                ents[lcn] = (t, lo)
                packinfo[lcn] = (pack, i, vcnt, encodebits)

        decode(0, min(c4b_init, totalidx), ebase, 2)
        pos = ebase + c4b_init * 4
        decode(c4b_init, c2b, pos, 1)
        pos += c2b * 2
        rest = totalidx - c4b_init - c2b
        if rest > 0:
            decode(c4b_init + c2b, rest, pos, 2)

        def dec(pack, encodebits, i):
            bitpos = encodebits * i
            v = struct.unpack_from("<I", pack, bitpos // 8)[0] >> (bitpos & 7)
            return v & ((1 << lobits) - 1), (v >> lobits) & 3

        def head_pblk(lcn):
            pack, i, vcnt, encodebits = packinfo[lcn]
            nblk = 1 if not big else 0
            j = i
            while j > 0:
                j -= 1
                lo, t = dec(pack, encodebits, j)
                if t == _T_NONHEAD:
                    if big:
                        if lo & _CBLKCNT:
                            j -= 1
                            nblk += lo & ~_CBLKCNT
                            continue
                        j -= lo - 2
                        continue
                    nblk += 1
                else:
                    nblk += 1
            base = struct.unpack_from("<I", pack, (vcnt << (1 if vcnt == 16 else 2)) - 4)[0]
            return base + nblk

        cblk = {i: (e[1] & ~_CBLKCNT) for i, e in enumerate(ents)
                if e[0] == _T_NONHEAD and (e[1] & _CBLKCNT)}
        heads = [(i, e[1]) for i, e in enumerate(ents) if e[0] != _T_NONHEAD]
        for hi, (lcn, cofs) in enumerate(heads):
            t = ents[lcn][0]
            la = (lcn << lcb) | cofs
            if hi + 1 < len(heads):
                nl, ncofs = heads[hi + 1]
                end = (nl << lcb) | ncofs
            else:
                end = size
            llen = end - la
            pblk = head_pblk(lcn)
            if t == _T_PLAIN:
                plen, alg = 1 << lcb, "plain"
            else:
                if big and (lcn + 1) in cblk:
                    plen = cblk[lcn + 1] * blk
                else:
                    plen = 1 << lcb
                alg = z["alg0"] if t == _T_HEAD1 else z["alg1"]
            yield la, llen, pblk * blk, plen, alg

    def file_reader(self, ino):
        """Return a ``read_range(start, n)`` for a compressed inode, with a
        one-pcluster decompression cache (so sequential reads cost one
        decompress per pcluster)."""
        if ino["layout"] in (0, 2):
            return lambda start, n: self._read_flat(ino, start, n)
        extents = list(self._extents(ino))            # (la, llen, pa, plen, alg)
        starts = [e[0] for e in extents]
        import bisect
        cache = {"la": -1, "data": b""}
        dctx = self._zstd_dctx()

        def _decompress(la, llen, pa, plen, alg):
            if cache["la"] == la:
                return cache["data"]
            raw = self._read(pa, plen)
            if alg == "plain":
                out = raw[:llen]
            elif alg == 3:                            # zstd (ZERO_PADDING: right-aligned)
                out = dctx.decompress(raw.lstrip(b"\x00"),
                                      max_output_size=llen, allow_extra_data=True)
            else:
                raise DdiError("unsupported EROFS compressor %r" % (alg,))
            if len(out) < llen:
                raise DdiError("short pcluster: %d < %d" % (len(out), llen))
            cache["la"], cache["data"] = la, out
            return out

        def read_range(start, n):
            out = bytearray()
            while n > 0:
                idx = bisect.bisect_right(starts, start) - 1
                la, llen, pa, plen, alg = extents[idx]
                chunk = _decompress(la, llen, pa, plen, alg)
                o = start - la
                take = min(n, llen - o)
                out += chunk[o:o + take]
                start += take
                n -= take
            return bytes(out)

        return read_range


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def is_ddi(path):
    """True if *path* looks like a BoF systemd-DDI ``.fun`` (GPT + EROFS)."""
    try:
        with open(path, "rb") as f:
            f.seek(_LBA)
            if f.read(8) != _GPT_SIG:
                return False
            off, _ = _find_payload_partition(f)
            f.seek(off + _EROFS_SB_OFF)
            return struct.unpack_from("<I", f.read(4), 0)[0] == _EROFS_MAGIC
    except (OSError, DdiError, struct.error):
        return False


def extract_game_binaries(fun_path, out_dir, log_cb=None, progress_cb=None):
    """Extract every ``/usr/lib/game/*.x86_64`` from a BoF DDI ``.fun`` into
    *out_dir*.  Returns the list of written file paths (host paths).

    The outer EROFS is decompressed on demand; each binary is streamed to
    disk in chunks so peak memory stays flat on a multi-GB game.
    """
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    long = "\\\\?\\" if os.name == "nt" else ""
    f = open(long + os.path.abspath(fun_path), "rb")
    try:
        payload_off, _payload_len = _find_payload_partition(f)

        def outer_read(off, n):
            f.seek(payload_off + off)
            return f.read(n)

        outer = Erofs(outer_read)
        # The payload EROFS holds the UKI + the inner root image.
        root_entry = None
        for name, nid in outer.listdir(outer.inode(outer.root_nid)):
            if name in (".", ".."):
                continue
            if name.endswith(".img.root-x86-64") or name.endswith("root-x86-64"):
                root_entry = (name, nid)
        if root_entry is None:
            raise DdiError("no inner root image (*.img.root-x86-64) in payload")
        _log("Found inner root image: %s" % root_entry[0])

        inner_ino = outer.inode(root_entry[1])
        inner_read = outer.file_reader(inner_ino)
        inner = Erofs(inner_read)

        game_dir = inner.resolve("/usr/lib/game")
        if game_dir is None:
            raise DdiError("/usr/lib/game not found in the inner root")

        bins = [(n, nid) for n, nid in inner.listdir(game_dir)
                if n.endswith(".x86_64")]
        if not bins:
            raise DdiError("no *.x86_64 game binaries under /usr/lib/game")

        os.makedirs(out_dir, exist_ok=True)
        written = []
        total = sum(inner.inode(nid)["size"] for _n, nid in bins)
        done = 0
        chunk = 64 << 20
        for name, nid in sorted(bins):
            ino = inner.inode(nid)
            reader = inner.file_reader(ino)
            size = ino["size"]
            dst = os.path.join(out_dir, name)
            _log("Extracting %s (%.0f MB)..." % (name, size / 1e6))
            with open(long + os.path.abspath(dst), "wb") as o:
                off = 0
                while off < size:
                    n = min(chunk, size - off)
                    o.write(reader(off, n))
                    off += n
                    done += n
                    if progress_cb:
                        progress_cb(done, total, "Extracting %s..." % name)
            written.append(dst)
            _log("  wrote %s" % name, "success")
        return written
    finally:
        f.close()
