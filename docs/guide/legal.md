# Disclaimer

[← Back to the README](../../README.md)

This project is an independent interoperability utility. It is **not
affiliated with, endorsed by, or sponsored by** American Pinball, Chicago
Gaming Company, Planetary Pinball Supply, Bally, Williams, Stern Pinball,
Jersey Jack Pinball, Pinball Brothers, Spooky Pinball, Barrels of Fun,
Dutch Pinball, or any other
pinball manufacturer, publisher, or rights holder. All trademarks and
game titles referenced are the property of their respective owners and
are used here in their nominative/descriptive sense only — to identify
which file formats this tool can read.

The tool ships **no game content** of any kind — no ROMs, no audio
samples, no graphics, no executables from any pinball machine. It is
inert until the user supplies their own file that they obtained
legitimately (typically by purchasing the machine, downloading the
official update from the manufacturer's support portal, or imaging
their own physical media).

Intended use is **personal customization of a machine you own** — the
same kind of fair-use modification covered by Sega v. Accolade (1992)
for reverse engineering interoperability and by the general right to
modify property you've legally purchased. Distributing modified game
assets to others, hosting copyrighted ROMs, or reselling modified
firmware is not supported by this tool and is **your responsibility to
avoid** — those activities have separate legal considerations the tool
does not address.

## A note on the DMCA

Some formats this tool reads sit behind a technical protection measure,
so U.S. users should be aware of the DMCA's anti-circumvention rules
(17 U.S.C. §1201). Two design choices keep this project on the
defensible side of that line:

- **It ships no keys and no protected content.** Where a manufacturer
  key is involved, the tool either derives it or reads it from *your
  own* hardware/media at runtime — nothing secret is embedded in, or
  distributed by, this repository.
- **Its purpose is interoperability and repair of a device you own** —
  the use case the Copyright Office has repeatedly recognized in its
  triennial §1201 exemptions for software-enabled devices, and the
  spirit of Sega v. Accolade. This is a non-commercial hobbyist utility;
  it is not sold and derives no revenue from circumvention.

None of this is legal advice, and §1201 is broad — its criminal
provisions (§1204) turn on *willful* circumvention *for commercial
advantage or private financial gain*, which this project is built to
stay clear of. Redistributing decrypted game assets, keys, or ROMs is
where real exposure lives; the tool doesn't do that and you shouldn't
either. If you ever receive a takedown notice or cease-and-desist,
consult a lawyer rather than responding solo — organizations like the
EFF have taken §1201 cases involving exactly this kind of repair and
interoperability work.

## Manufacturer license terms (EULAs)

Separate from copyright and the DMCA, the software on some machines is
licensed to the owner under an end-user license agreement (EULA) — a
private contract. Manufacturer EULAs are often written far more broadly
than copyright law requires and may **prohibit reverse engineering,
modification, creating derivative works, circumventing security
measures, and using or distributing "unauthorized" content or
software** — which can cover both modding a machine and building or
sharing a tool that helps others do so. A contract you agreed to can
restrict things that copyright law alone would permit, and the fair-use
/ interoperability framing above does **not** override it.

Stern Pinball's EULA is a notable example: it expressly bars owners
from reverse engineering the software, defeating its security measures,
and creating or **assisting anyone else** in creating unauthorized
content or software for a Stern machine. Using this tool on a Stern
machine you own would be inconsistent with those terms, and Stern warns
that unauthorized content or circumvention **may cause the machine to
stop working permanently or lose access to its online network**, either
immediately or after a later official update.

This project does not claim to be compatible with any manufacturer's
EULA. Whether a EULA applies to you, and whether its broadest clauses
are enforceable where you live, are legal questions that vary by
jurisdiction — decide for yourself, on a machine you own, and accept
that modding it may violate the license and disable the machine or its
online features. Breach of a EULA is a civil matter between you and the
manufacturer; it is a different (and generally lower) category of risk
than the criminal provisions discussed above, but it is real.

No warranty. Use entirely at your own risk. **Always make a complete,
working backup before modifying a machine** — a failed, interrupted, or
incorrect update can leave it unbootable ("bricked"), and without a
known-good backup image you may be unable to recover it. Flashing a
modified `.img` or installing a modified update can render a machine
inoperable until you restore a known-good image. The maintainers accept
no liability for bricked machines, damaged hardware, lost data, voided
warranties, or any other consequence of using this tool.

The app shows a short version of this disclaimer in a modal dialog the
first time you launch it, including a request to **not contact the
manufacturer's support team** about issues that may have been caused by
modified code — revert to stock firmware before opening a ticket, and
disclose any past modifications. The acceptance is stored in
`settings.json` and survives app updates; you're only asked to accept
once, and the full text stays re-readable any time via the ⚙ settings
menu → **View disclaimer…**.
