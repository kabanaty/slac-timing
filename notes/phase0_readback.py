"""Read-only production checks for the BYKIK rate mask work (see bykik-rate-mask.md).

Performs only caget / CA metadata reads — no puts, no reservations.

Answers:
  G2/G3  What inclusion/exclusion bits does a freshly reserved EDEF carry?
  G4     Do PNBN BITP values line up with the INCLUSION{1..5} word packing
         used by EventDefinition._set_masks?
  G6     What are the exact values/enum strings of the BYKIK rate PVs?

Because this script never reserves, defaults (G3) must be read from an EDEF
someone else just reserved. Reserve one with the MATLAB BSA control GUI (or
any tool) *without* starting a scan, then pass its number with --edef.

Usage:
    python phase0_readback.py                 # all reserved slots
    python phase0_readback.py --edef 4 --edef 7
"""

import argparse

import epics

N_PNBN = 160  # slac-timing reads 1..140; read further to see if that's enough
N_INCM = 160  # MATLAB scans INCM{1..160}.DESC
EDEF_SLOTS = range(1, 12)
TARGET_PREFIXES = ("RATE_MPS_", "pockcel_perm")
RATE_PVS = (
    "IOC:BSY0:MP01:BYKIK_RATE",
    "IOC:BSY0:MP01:BYKIKS_RATE",
    "EVNT:SYS0:1:LCLSBEAMRATE",
)
DEFAULT_MASK_PVS = ("VX00:DGRP:1150:INCM", "VX00:DGRP:1150:EXCM")


def caget_many(names, **kw):
    return epics.caget_many(list(names), connection_timeout=2.0, **kw)


def section(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def read_pnbn():
    """Return {name: bitp} and print the entries relevant to the rate mask."""
    section(f"PNBN:SYS0:1..{N_PNBN}  (G4)")
    idx = range(1, N_PNBN + 1)
    names = caget_many((f"PNBN:SYS0:{i}:NAME" for i in idx), as_string=True)
    bitps = caget_many(f"PNBN:SYS0:{i}:BITP" for i in idx)

    populated = [i for i, n in zip(idx, names) if n]
    print(f"populated entries: {len(populated)}, highest index: {max(populated, default=None)}")
    if any(i > 140 for i in populated):
        print("  !! entries above 140 exist; EventDefinitionPVs.pnbn_* (1..140) misses them")

    table = {}
    print(f"\n{'idx':>4}  {'BITP':>5}  NAME")
    for i, name, bitp in zip(idx, names, bitps):
        if not name:
            continue
        table[name] = bitp
        if name.startswith(TARGET_PREFIXES):
            print(f"{i:>4}  {bitp!s:>5}  {name}")
    for want in ("pockcel_perm",):
        if want not in table:
            print(f"  !! {want!r} not found in PNBN")
    return table


def read_rates():
    section("Rate PVs  (G6)")
    for name in RATE_PVS:
        pv = epics.PV(name, connection_timeout=2.0)
        if not pv.wait_for_connection(timeout=2.0):
            print(f"{name}: NOT CONNECTED")
            continue
        raw = pv.get(as_string=False)
        text = pv.get(as_string=True)
        ctrl = pv.get_ctrlvars() or {}
        print(f"{name}")
        print(f"  type={pv.type}  raw={raw!r}  as_string={text!r}")
        if ctrl.get("enum_strs"):
            for k, s in enumerate(ctrl["enum_strs"]):
                print(f"    [{k}] {s!r}")
        pv.disconnect()


def read_default_masks():
    section("Reservation defaults per eDefParams header  (G2/G3)")
    for name, raw, text in zip(
        DEFAULT_MASK_PVS,
        caget_many(DEFAULT_MASK_PVS),
        caget_many(DEFAULT_MASK_PVS, as_string=True),
    ):
        print(f"{name}: raw={raw!r} as_string={text!r}")


def decode_words(words, pnbn_by_bitp):
    """Print set bits under both candidate word layouts."""
    for m, w in enumerate(words, start=1):
        if w is None:
            print(f"    word{m}: NOT CONNECTED")
            continue
        w = int(w) & 0xFFFFFFFF
        bits = [b for b in range(32) if w >> b & 1]
        print(f"    word{m}: 0x{w:08X}  set bits={bits}")
        for b in bits:
            natural = 32 * (m - 1) + b  # word1 = BITP 0..31
            current = 32 * m + b  # what _set_masks writes: word1 = BITP 32..63
            print(
                f"      bit {b:>2}: BITP {natural:>3} -> {pnbn_by_bitp.get(natural, '?'):<24}"
                f" | BITP {current:>3} -> {pnbn_by_bitp.get(current, '?')}"
            )


def read_edef(n, pnbn, pnbn_by_bitp):
    p = f"EDEF:SYS0:{n}"
    name, user, beamcode, ctrl, cnt = caget_many(
        (f"{p}:NAME", f"{p}:USERNAME", f"{p}:BEAMCODE", f"{p}:CTRL", f"{p}:CNT"),
        as_string=True,
    )
    print(f"\n--- EDEF {n}: name={name!r} user={user!r} beamcode={beamcode} ctrl={ctrl} cnt={cnt}")

    for kind, per_bit in (("INCLUSION", "INCM"), ("EXCLUSION", "EXCM")):
        words = caget_many(f"{p}:{kind}{m}" for m in range(1, 6))
        print(f"  {kind}1..5  (columns: natural layout | current _set_masks layout)")
        decode_words(words, pnbn_by_bitp)

        k = range(1, N_INCM + 1)
        descs = caget_many((f"{p}:{per_bit}{i}.DESC" for i in k), as_string=True)
        vals = caget_many(f"{p}:{per_bit}{i}" for i in k)
        set_bits = [(i, d) for i, d, v in zip(k, descs, vals) if d and v]
        print(f"  {per_bit}<k> set (MATLAB per-bit view):")
        for i, d in set_bits or [(None, "(none)")]:
            print(f"    {per_bit}{i}: {d}  (PNBN BITP={pnbn.get(d)})" if i else f"    {d}")
        targets = [(i, d) for i, d in zip(k, descs) if d and d.startswith(TARGET_PREFIXES)]
        print(f"  {per_bit}<k> DESC for target names:")
        for i, d in targets:
            print(f"    {per_bit}{i}: {d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edef", type=int, action="append", help="EDEF number(s) to inspect")
    args = ap.parse_args()

    pnbn = read_pnbn()
    pnbn_by_bitp = {bitp: name for name, bitp in pnbn.items() if bitp is not None}
    read_rates()
    read_default_masks()

    section("EDEF slots  (G3/G4)")
    slots = args.edef
    if not slots:
        names = caget_many((f"EDEF:SYS0:{n}:NAME" for n in EDEF_SLOTS), as_string=True)
        slots = [n for n, name in zip(EDEF_SLOTS, names) if name]
        print(f"reserved slots: {slots or 'none'}")
    for n in slots:
        read_edef(n, pnbn, pnbn_by_bitp)


if __name__ == "__main__":
    main()
