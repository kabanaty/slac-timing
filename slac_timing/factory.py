from slac_timing.buffer import Buffer
from slac_timing.bsa_buffer import BSABuffer
from slac_timing.event_definition import EventDefinition


_BEAMCODE_MAP = {
    "CU_HXR": 1,
    "CU_SXR": 2,
}


def create_buffer(
    beampath: str,
    n_measurements: int,
    user: str,
    name: str = "SLAC Tools",
    n_avg: int = 1,
) -> Buffer:
    """Create and reserve the appropriate buffer type based on beampath.

    CU_HXR / CU_SXR → EventDefinition
    SC_* → BSABuffer (destination_masks=[beampath])
    """
    if beampath in _BEAMCODE_MAP:
        return EventDefinition(
            name=name,
            user=user,
            n_measurements=n_measurements,
            n_avg=n_avg,
            beamcode=_BEAMCODE_MAP[beampath],
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
