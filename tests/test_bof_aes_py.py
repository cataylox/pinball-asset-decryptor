"""The pure-Python AES fallback (plugins/bof/aes_py.py) that lets the
emulator read Dune's encrypted PCK directory inside the app's Linux, where
pycryptodome is not installed (PAD-257)."""

import os

import pytest

from pinball_decryptor.plugins.bof import aes_py


def test_fips197_vectors():
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    for key, ct in (
            ("000102030405060708090a0b0c0d0e0f",
             "69c4e0d86a7b0430d8cdb78070b4c55a"),
            ("000102030405060708090a0b0c0d0e0f1011121314151617",
             "dda97ca4864cdfe06eaf70a0ec0d7191"),
            ("000102030405060708090a0b0c0d0e0f"
             "101112131415161718191a1b1c1d1e1f",
             "8ea2b7ca516745bfeafc49904b496089")):
        assert aes_py.ecb_encrypt_block(bytes.fromhex(key), pt).hex() == ct


def test_cfb_matches_pycryptodome_both_ways():
    AES = pytest.importorskip("Crypto.Cipher.AES")
    key, iv = os.urandom(32), os.urandom(16)
    data = os.urandom(16 * 20 + 7)            # a ragged last segment too
    ref = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128)
    ct = ref.encrypt(data)
    assert aes_py.cfb128(key, iv, data, encrypt=True) == ct
    assert aes_py.cfb128(key, iv, ct) == data
