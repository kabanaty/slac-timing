"""EDEF inclusion masks for CU buffers downstream of the BYKIK/BYKIKS kickers.

When BYKIK is kicking, only a fraction of the beam reaches the LTU. Adding the
matching ``RATE_MPS_*`` modifier to the EDEF inclusion mask makes the buffer
record only the shots that get past the BSY. Mirrors MATLAB's
``whatEDefParams`` (wirescan_gui.m).
"""

import logging
from typing import Optional

from slac_tools import LazyPV

from slac_timing.buffer import ReservationError


logger = logging.getLogger(__name__)

POCKCEL_PERM = "pockcel_perm"

_RATE_PVS = {
    "CU_HXR": LazyPV("IOC:BSY0:MP01:BYKIK_RATE"),
    "CU_SXR": LazyPV("IOC:BSY0:MP01:BYKIKS_RATE"),
}
# MATLAB applies the rate bit only in these areas.
_BYKIK_AREAS = {"CU_HXR": "LTUH", "CU_SXR": "LTUS"}
_MASK_PATH = {"CU_HXR": "HXR", "CU_SXR": "SXR"}
# BYKIK*_RATE enum string -> (rate in Hz, RATE_MPS_* suffix).
_RATE_MASKS = {
    "1 Hz": (1.0, "01HZ"),
    "10 Hz": (10.0, "10HZ"),
    "30 Hz": (30.0, "30HZ"),
    "60 Hz": (60.0, "60HZ"),
}
_FULL_RATE = "120 Hz"
_NO_BEAM = "0 Hz"


class NoBeamError(ReservationError):
    """Raised when BYKIK lets no beam past the BSY."""

    pass


def bykik_inclusion_masks(
    beampath: str, area: Optional[str]
) -> tuple[list[str], Optional[float]]:
    """Return (inclusion masks, rate limit in Hz) for a CU buffer.

    The masks always include ``pockcel_perm``. In LTUH/LTUS the BYKIK rate PV is
    read and the matching ``RATE_MPS_*`` bit is added. The rate limit is the
    BYKIK rate when a rate bit is applied, otherwise None (full beam rate).

    Raises NoBeamError if BYKIK is at 0 Hz, ReservationError if the rate PV
    cannot be read.
    """
    masks = [POCKCEL_PERM]
    if beampath not in _BYKIK_AREAS or area != _BYKIK_AREAS[beampath]:
        return masks, None

    pv = _RATE_PVS[beampath]
    rate = pv.get(as_string=True)
    if rate is None:
        raise ReservationError(f"Could not read BYKIK rate pv={pv.pvname}")
    if rate == _NO_BEAM:
        raise NoBeamError(f"No beam past BSY for {area}: pv={pv.pvname}, value={rate!r}")
    if rate == _FULL_RATE:
        return masks, None
    if rate not in _RATE_MASKS:
        logger.warning(
            "Unmapped BYKIK rate pv=%s, value=%r; no rate mask applied.",
            pv.pvname,
            rate,
        )
        return masks, None

    rate_hz, suffix = _RATE_MASKS[rate]
    masks.append(f"RATE_MPS_{_MASK_PATH[beampath]}_{suffix}")
    return masks, rate_hz
