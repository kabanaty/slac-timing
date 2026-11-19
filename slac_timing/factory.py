from typing import Optional

from slac_timing.buffer import Buffer
from slac_timing.bsa_buffer import BSABuffer
from slac_timing.event_definition import EventDefinition
from slac_timing.masks import bykik_inclusion_masks


def create_buffer(
    beampath: str,
    n_measurements: int,
    user: str,
    name: str = "SLAC Tools",
    n_avg: int = 1,
    area: Optional[str] = None,
) -> Buffer:
    """Create and reserve the appropriate buffer type based on beampath.

    CU_HXR / CU_SXR → EventDefinition with pockcel_perm, plus the BYKIK rate
        mask when area is LTUH / LTUS. The BYKIK rate is read here, so reserve
        a new buffer for each scan.
    SC_* → BSABuffer (destination_masks=[beampath])
    """
    if beampath.startswith("CU_"):
        inclusion_masks, rate_limit_hz = bykik_inclusion_masks(beampath, area)
        return EventDefinition(
            name=name,
            user=user,
            n_measurements=n_measurements,
            n_avg=n_avg,
            beamcode=EventDefinition.BEAMCODE_MAP[beampath],
            inclusion_masks=inclusion_masks,
            rate_limit_hz=rate_limit_hz,
        )

    if beampath.startswith("SC_"):
        return BSABuffer(
            name=name,
            user=user,
            n_measurements=n_measurements,
            n_avg=n_avg,
            destination_mode="Inclusion",
            destination_masks=[beampath],
        )

    raise ValueError(f"Unknown beampath: {beampath!r}")
