"""Barrels of Fun (BOF) game database + pipeline tunables."""

GAME_DB = {
    "labyrinth": {
        "display": "Jim Henson's Labyrinth",
        "fun_file": "lab.fun",
        "passphrase": "funkey",
        "platform": "Arch Linux, FAST hardware, Godot 4.4.1 (PCK format v2)",
    },
    "dune": {
        "display": "Dune",
        "fun_file": "dune.fun",
        "passphrase": "dunekey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
    "winchester": {
        "display": "Winchester Mystery House",
        "fun_file": "winchester.fun",
        "passphrase": "winchesterkey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
    "bonjovi": {
        "display": "Bon Jovi",
        # Real update files are version-stamped (bon-jovi_YYYY.MM.DD.fun), so
        # detection is by filename prefix + content, not an exact name.
        "fun_file": "bon-jovi.fun",
        # No GPG passphrase: Bon Jovi ships a signed systemd disk image (DDI),
        # not a GPG-symmetric tarball.  The container is unwrapped natively.
        "container": "ddi",
        "platform": "Arch Linux (systemd DDI), FAST hardware, Godot 4.7.2",
    },
}

# .fun filename -> game key.  Exact-match games only; Bon Jovi is matched by
# prefix + content in detect_game because its filename carries a version date.
FUN_FILE_TO_GAME = {info["fun_file"]: key for key, info in GAME_DB.items()
                    if info.get("container", "gpg") != "ddi"}


# Phase names retained for the BOF pipeline's internal logic.  The unified
# GUI uses its own EXTRACT_PHASES/WRITE_PHASES (4 phases each); BOF's 5-step
# flows render as the first 4 plus a silently-clamped tail.
DECRYPT_PHASES = ["Detect", "Decrypt", "Extract", "Checksums", "Cleanup"]
MODIFY_PHASES = ["Decrypt", "Patch", "Repack", "Encrypt", "Cleanup"]


# Timeouts for long-running shell ops (large .fun files take real time)
GPG_DECRYPT_TIMEOUT = 7200
TAR_EXTRACT_TIMEOUT = 7200
GDRE_TIMEOUT = 7200
CHECKSUM_TIMEOUT = 7200
GPG_ENCRYPT_TIMEOUT = 7200
TAR_PACK_TIMEOUT = 7200
