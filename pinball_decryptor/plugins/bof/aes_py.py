"""aes_py.py - AES block ENCRYPTION in pure Python, for where pycryptodome
is not installed.

pck_directory reads Dune's encrypted PCK directory with AES-256-CFB, and CFB
(both directions) needs only the forward cipher.  The app's Windows Python has
pycryptodome; the app's Linux (PAD-Runtime), where the emulator unpacks a
build and pulls its playfield picture out of it (PAD-257), does not - and no
user may be asked to install anything.  This is the textbook T-table-free
AES: slow (tens of microseconds a block) and only ever used for the one
directory read per build.  tests/test_bof_aes_py.py holds it to pycryptodome.
"""

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)


def _xt(a):
    a <<= 1
    return (a ^ 0x11b) if a & 0x100 else a


def expand_key(key):
    """Round keys (as 16-byte lists) for a 16/24/32-byte key."""
    nk = len(key) // 4
    if nk not in (4, 6, 8):
        raise ValueError("AES key must be 16, 24 or 32 bytes")
    rounds = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (rounds + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - nk], t)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(rounds + 1)]


def encrypt_block(round_keys, block):
    s = [a ^ b for a, b in zip(block, round_keys[0])]
    last = len(round_keys) - 1
    for r in range(1, last + 1):
        s = [_SBOX[b] for b in s]
        # ShiftRows (state is column-major: s[c*4 + row])
        s = [s[(c * 4 + row + 4 * row) % 16] for c in range(4) for row in range(4)]
        if r != last:
            m = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t = a0 ^ a1 ^ a2 ^ a3
                m += [a0 ^ t ^ _xt(a0 ^ a1), a1 ^ t ^ _xt(a1 ^ a2),
                      a2 ^ t ^ _xt(a2 ^ a3), a3 ^ t ^ _xt(a3 ^ a0)]
            s = m
        s = [a ^ b for a, b in zip(s, round_keys[r])]
    return bytes(s)


def ecb_encrypt_block(key, block16):
    return encrypt_block(expand_key(key), block16)


def cfb128(key, iv, data, encrypt=False):
    """AES-CFB with 128-bit segments, either direction."""
    rk = expand_key(key)
    out = bytearray()
    prev = bytes(iv)
    for i in range(0, len(data), 16):
        ks = encrypt_block(rk, prev)
        chunk = data[i:i + 16]
        res = bytes(a ^ b for a, b in zip(chunk, ks))
        out += res
        ct = res if encrypt else chunk
        prev = ct if len(ct) == 16 else prev
    return bytes(out)
