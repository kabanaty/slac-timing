# BYKIK rate mask for CU LTU buffers

Status: not implemented. These notes are the handoff for implementing it in slac-timing. The production checks are done; see "Production results" at the end.

## Summary

When BYKIK is kicking, only a fraction of the CU beam reaches the LTU. For example, at 120 Hz machine rate with BYKIK at 30 Hz, only 1 shot in 4 gets past the BSY. The MATLAB wirescan GUI handles this by adding an MPS rate modifier bit (e.g. `RATE_MPS_HXR_30HZ`) to the EDEF inclusion mask. The buffer then only records shots that actually reach the LTU.

slac-timing's `create_buffer()` never sets any inclusion mask for CU buffers. The rate filter is missing, and so is `pockcel_perm`. The buffer records every beamcode-1 (or 2) shot, so about 3 in 4 samples are beam-less points with only the PMT baseline.

Evidence: WS34 (WIRE:LTUH:775), PMT:LTUH:756, same wire, same detector:

| Buffer | Mask | Total shots | Points per peak |
|---|---|---|---|
| `QDCRAWHST2` | `RATE_MPS_HXR_30HZ` | ~400 | ~6–8 |
| `QDCRAWHST3` | none | ~1480 | ~25–30, interleaved with baseline points |

The unmasked buffer has about 4× the shots, but the extra shots carry no real signal. Inside each peak region, points jump between baseline and peak height. The Python fit came out with a narrower sigma (39 µm vs 62 µm) and a lower amplitude than MATLAB. Both are consistent with beam-less samples contaminating the profile.

## Reference implementation (MATLAB, `toolbox` repo)

### 1. Choosing the mask: `whatEDefParams` (`wirescan_gui.m`, also `+wirescan/whatEDefParams.m`)

Returns `{incmSet, incmReset, excmSet, excmReset, beamcode}`. The `RATE_MPS_*` names come from these lookups:

| beampath | sector | beamcode | rate PV read | `incmSet` |
|---|---|---|---|---|
| CU_HXR | LTUH | 1 | `IOC:BSY0:MP01:BYKIK_RATE` | `{RATE_MPS_HXR_{01,10,30}HZ, pockcel_perm}` |
| CU_HXR | other | 1 | — | `{pockcel_perm}` |
| CU_SXR | LTUS | 2 | `IOC:BSY0:MP01:BYKIKS_RATE` | `{RATE_MPS_SXR_{01,10,30}HZ, pockcel_perm}` |
| CU_SXR | other | 2 | — | `{pockcel_perm}` |

`incmReset`, `excmSet` and `excmReset` are always `{''}`, meaning no change.

The rate PV is read as a string, and the code matches on its first two characters:
- `'1 '` → `01HZ`
- `'10'` → `10HZ`
- `'30'` → `30HZ`
- anything else → no rate bit, `pockcel_perm` only

This runs fresh on every scan, immediately before the buffer is started (`scanStartWire`, `scanAutoRange`, `scanStartCorr`, `scanStartOrbit`, `scanStartStep`, `scanRMatCalib_btn_Callback`).

### 2. Applying the mask: `eDefParams.m`

`eDefParams(n, navg, nrpos, incmSet, incmReset, excmSet, excmReset, beamcode)`, with `sys = SYS0`:

1. `EDEF:SYS0:n:AVGCNT` ← navg, clamped to `.LOPR`/`.HOPR`
2. `EDEF:SYS0:n:MEASCNT` ← nrpos, clamped to `.LOPR`/`.HOPR`
3. `EDEF:SYS0:n:BEAMCODE` ← beamcode (if given)
4. Build a name → index table by reading `EDEF:SYS0:n:INCM{1..160}.DESC`, stopping at the first empty DESC.
5. For each name in `incmSet`, write `EDEF:SYS0:n:INCM<k>` ← 1, where k is the matching DESC.
6. Do the same for `incmReset` (writes 0), `excmSet` (`EXCM<k>` ← 1) and `excmReset` (`EXCM<k>` ← 0).
7. `pause(0.1)` to let the EVG pick up the change.

Important semantics:
- **Additive.** It only sets or clears the named bits. Every other bit keeps its reservation default, which the header says comes from `VX00:DGRP:1150:INCM`/`EXCM`. MATLAB never clears a mask.
- **Silent on unknown names.** If a name doesn't match any DESC, the bit is skipped with no error.
- **Name table cached once.** It is `persistent` across all EDEF numbers, so it assumes every EDEF has the same bit layout.
- **SC buffers.** For EDEF numbers above 20 the call is forwarded to `bsaParams` with only the first 4 arguments, so masks and beamcode are ignored. This feature only applies to CU.

### 3. Lifecycle around a scan

1. `gui_BSAControl` reserves the EDEF with `eDefParams(n, 1, 2800)`, which applies no masks.
2. At scan start: `eDefParams(n, 1, bufferNum, par{:})`, then `eDefOn`.
3. After the scan: `eDefOff`, and `gui_BSAControl(..., 0)` releases the EDEF.

The next scan reserves a fresh EDEF, so masks never carry over from one scan to the next.

## Current slac-timing state

- `EventDefinition` (`slac_timing/event_definition.py`) already accepts `inclusion_masks` and `exclusion_masks` and applies them in `_configure()` through `_set_masks()`.
- `_set_masks()` uses a different PV interface from MATLAB:
  - it looks up bit positions from `PNBN:SYS0:{1..140}:NAME` / `:BITP`
  - it packs them into a bitmask and writes the 32-bit words `EDEF:SYS0:n:INCLUSION{1..5}` / `EXCLUSION{1..5}`
  - this logic is ported from the legacy `edef/edef.py`
- `create_buffer()` (`slac_timing/factory.py`) builds a CU `EventDefinition` with only `beamcode`. It sets no inclusion masks: no `pockcel_perm` and no rate bit.
- The only caller found is `slac-measurements/slac_measurements/wires/collection/buffer.py::reserve_buffer` → `create_buffer(beampath, n_measurements, user, name)`. It has no sector or area argument, so the factory can't tell that the scan is in LTUH or LTUS.

## Gaps

### G1. No rate mask (the main bug)
CU LTU scans record shots that BYKIK removed. To fix this, the mask needs to depend on the BYKIK rate and the sector or area.

### G2. `pockcel_perm` missing from every CU buffer
MATLAB always includes `pockcel_perm` on CU, in every sector. slac-timing never sets it. Before closing this out, check whether the reservation defaults (`VX00:DGRP:1150:INCM`) already include it.

### G3. `_set_masks` clears first; MATLAB adds to the defaults
`_set_masks()` calls `_clear_masks()`, which zeroes all five INCLUSION words before writing the requested bits. Any default inclusion bits from reservation are lost. Passing `inclusion_masks=["RATE_MPS_HXR_30HZ", "pockcel_perm"]` gives an inclusion mask that contains only those two bits. MATLAB's mask would be "defaults + those two bits".

Action:
1. Read `INCLUSION1-5` right after a reservation on production to see what the defaults are.
2. If they're non-zero, decide whether to:
   - (a) switch to read-modify-write, OR-ing the requested bits into the existing words to match MATLAB, or
   - (b) keep clear-and-set but make callers pass the complete intended list.

Option (a) matches the MATLAB reference behavior.

### G4. Verify the INCLUSION word packing
`_set_masks` does `bit_mask |= 1 << (bit_num + 32)`, then sets word `m` (5..1) to `(bit_mask >> 32*(m+1)) & 0xFFFFFFFF`. Taken literally, word 1 holds BITP 32–63, word 2 holds BITP 64–95, and BITP 0–31 are never written. This could be correct if PNBN BITP values are offset, or if word 0 is intentionally skipped, since it matches legacy `edef.py`. Verify against production before trusting it:
- For each target mask name, read `PNBN:SYS0:<i>:NAME`/`BITP`.
- Set the mask with slac-timing.
- Read back `EDEF:SYS0:n:INCM<k>` (the per-bit view MATLAB uses) and confirm the intended bit is set.

Also check that PNBN entries 1..140 cover the `RATE_MPS_*` names. MATLAB scans up to 160 `INCM` DESCs.

### G5. Unknown mask names raise `KeyError`
`cache[mask]` raises `KeyError` instead of a domain error. Raising is the right call (better than MATLAB's silent skip), but it should be a `ReservationError` or `ValueError` that includes the missing name and the PV that was searched.

### G6. Fragile BYKIK rate parsing
MATLAB matches the first two characters of the rate string and quietly falls back to no rate filter for any other value. The Python version should:
- Read the enum/string PV, map it explicitly, and log a warning when it sees an unmapped rate (e.g. 0.5 Hz, 5 Hz, 120 Hz).
- Decide how to treat BYKIK disabled or "full rate". Most likely no rate bit, since all shots reach the LTU, but confirm the PV values for those states.
- Confirm the exact enum strings on production first. The two-character match suggests strings like `"1 Hz"`, `"10 Hz"`, `"30 Hz"`.

### G7. Mask chosen at reservation and never refreshed
MATLAB re-reads BYKIK_RATE on every scan. slac-timing configures masks once in `_configure()` at construction. If a buffer is reattached (`number=` given) or reused across scans, a BYKIK rate change won't be picked up. Either document that a buffer is single-scan, or add a public `set_inclusion_masks()` / `apply_rate_mask()` that callers run before `start()`.

### G8. No settle time after mask writes
MATLAB waits 0.1 s after mask writes for the EVG. `_set_masks` sleeps 0.05 s between words but not after the last one, and `start()` can follow immediately. Add a short settle at the end of `_configure()`.

## Downstream impact (slac-measurements / slac-devices; not slac-timing, but must be coordinated)

Once the mask works, the wire scan sees only about `bykik_rate` shots per second instead of `beam_rate`. Code that assumes the full beam rate then breaks:

- **Wire speed** (`slac-devices/slac_devices/wire.py`, `required_speed = beam_rate / scan_pulses * range`): `beam_rate` is `EVNT:SYS0:1:LCLSBEAMRATE`, the full machine rate. With a 30 Hz mask at 120 Hz, the wire moves 4× too fast and each plane gets about ¼ of the intended points. This is the same coarse sampling seen in MATLAB, which has the same flaw in `scanWireSpeedCheck` / `startFWS`.
- **Buffer size** (`slac-measurements/.../collection/buffer.py::_calculate_buffer_points`) is sized from `beam_rate`, so it's oversized but harmless.
- **Acquisition timeout** (`slac-measurements/.../collection/base.py::_calculate_acquisition_timeout_s`): `n_points / beam_rate` is too short by `beam_rate / bykik_rate`, which will cause spurious timeouts.

The fix is to use the effective rate seen by the buffer, `min(beam_rate, bykik_rate)`, everywhere the scan computes speed, size or timeout. slac-timing can help by exposing it, e.g. `EventDefinition.effective_rate`, or a helper that returns both the mask list and the effective rate.

## Suggested design (slac-timing)

1. Add a small module, e.g. `slac_timing/masks.py`:
   ```python
   BYKIK_RATE_PVS = {"CU_HXR": "IOC:BSY0:MP01:BYKIK_RATE",
                     "CU_SXR": "IOC:BSY0:MP01:BYKIKS_RATE"}
   RATE_MASKS = {"CU_HXR": {1: "RATE_MPS_HXR_01HZ", 10: "RATE_MPS_HXR_10HZ", 30: "RATE_MPS_HXR_30HZ"},
                 "CU_SXR": {1: "RATE_MPS_SXR_01HZ", 10: "RATE_MPS_SXR_10HZ", 30: "RATE_MPS_SXR_30HZ"}}
   LTU_AREAS = {"CU_HXR": "LTUH", "CU_SXR": "LTUS"}

   def cu_inclusion_masks(beampath: str, area: str | None) -> list[str]:
       """['pockcel_perm'] plus the BYKIK rate bit when area is downstream of BYKIK."""
   ```
   Use `LazyPV` for the rate PV to follow the repo conventions in CLAUDE.md (no direct `caget`).
   - **Areas.** MATLAB only applies the rate bit for exactly LTUH/LTUS. Every area downstream of the BYKIK/BYKIKS kicker (UNDH, DMPH, UNDS, DMPS, ...) is affected in the same way, so consider defining "downstream of BYKIK" as a set rather than one area per beampath. Confirm with operations.
2. Extend `create_buffer(..., area: str | None = None)` so that CU buffers get `inclusion_masks=cu_inclusion_masks(beampath, area)`. Leaving `area=None` keeps the current behavior plus `pockcel_perm`, pending the G2/G3 decision.
3. Resolve G3 (clear vs. additive) and G4 (verify packing) before the masks are relied on in production.
4. Raise a clear error for unknown mask names (G5).
5. Add a settle delay after mask writes (G8).
6. Tests, using the existing `ioc_yaml` fixture pattern in `tests/event_definition/`:
   - BYKIK rate `"30 Hz"` + LTUH → INCLUSION words contain the BITP for `RATE_MPS_HXR_30HZ` and `pockcel_perm`.
   - An unmapped rate string → no rate bit, and a warning is logged.
   - A non-LTU area → `pockcel_perm` only.
   - SXR equivalents.
   - An unknown mask name → a clear error.
7. Then, in slac-measurements: pass `area` from the wire (`beam_profile_device.area`) into `create_buffer`, and switch the speed, size and timeout calculations to the effective rate.

## Production results (2026-10-21, `notes/phase0_readback.py`)

Read on lcls-srv01. EDEF 2 = an LTUH scan that already had the mask set (cnt=401). EDEF 9 = a fresh `EventDefinition(..., beamcode=1)` with no masks passed.

### G2: closed. Reservation already includes `pockcel_perm`
Fresh EDEF 9 INCLUSION = `pockcel_perm` only (INCLUSION2 = 0x00080000). This matches `VX00:DGRP:1150:INCM = [8, 524288, 0]`.

### G3: decided. Use read-modify-write
Reservation defaults on a fresh EDEF:
- INCLUSION: `pockcel_perm`
- EXCLUSION1 = 0x36: TS2, TS3, TS5, TS6 (restricts the buffer to TS1/TS4)

EDEF 2 has the defaults plus `RATE_MPS_HXR_30HZ` and nothing else. MATLAB applies masks additively, as expected.

The current clear-then-set behavior would drop `pockcel_perm`. If any exclusion mask were passed, it would also drop the timeslot exclusions. Change `_set_masks` to OR the requested bits into the existing words.

### G4: closed. Packing is correct
BITP numbering starts at 32 (TS1=32 … TS6=37), so `word = bitp // 32` and `bit = bitp % 32`. On EDEF 2, INCLUSION2 = 0x00080010 decodes to BITP 68 (`RATE_MPS_HXR_30HZ`) and BITP 83 (`pockcel_perm`). These match MATLAB's per-bit view: INCM43 and INCM67 are set.

The PNBN table has 73 entries, highest index 135, so reading 1..140 is enough. All target names are present:

| Name | BITP | | Name | BITP |
|---|---|---|---|---|
| RATE_MPS_HXR_01HZ | 76 | | RATE_MPS_SXR_01HZ | 86 |
| RATE_MPS_HXR_10HZ | 69 | | RATE_MPS_SXR_10HZ | 84 |
| RATE_MPS_HXR_30HZ | 68 | | RATE_MPS_SXR_30HZ | 82 |
| RATE_MPS_HXR_60HZ | 67 | | RATE_MPS_SXR_60HZ | 81 |
| pockcel_perm | 83 | | | |

Masks also exist for 05/90/110/119 Hz, but no BYKIK enum state maps to them.

### G6: rate PV values known
`BYKIK_RATE` and `BYKIKS_RATE` are both `time_enum` with the states `[0] Invalid, [1] 0 Hz, [2,3] DEPRECATED, [4] 1 Hz, [5] 10 Hz, [6] 30 Hz, [7] 60 Hz, [8] 120 Hz, [9] Unknown`. Both 120 Hz and 0 Hz have been observed.

Proposed mapping (read with `as_string=True`):
- `1/10/30/60 Hz` → `RATE_MPS_<path>_{01,10,30,60}HZ`. Note that MATLAB has no 60 Hz case and silently drops the filter.
- `120 Hz` → no rate bit.
- `0 Hz` → no beam reaches the BSY, so raise an error and don't start the scan.
- `Invalid` / `Unknown` / `DEPRECATED` → no rate bit, with a logged warning.

### Side observation
Fresh EDEF 9 showed `cnt=406` with `ctrl=OFF`, so CNT appears to carry over from the slot's previous user. Check whether `start()` resets it. If it doesn't, `is_complete()` could return true early.

## Decisions (2026-10-21)
- `BYKIK*_RATE = 0 Hz` means no beam past the BSY. `create_buffer` raises an error.
- The rate bit applies only to LTUH (CU_HXR) and LTUS (CU_SXR), matching MATLAB. Other areas get no rate bit.

No open questions remain for slac-timing.
