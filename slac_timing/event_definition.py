import time
from typing import Optional

import epics
from pydantic import model_validator

from slac_timing.buffer import Buffer, ReservationError


_PREFIX = "EDEF:SYS0"
_NUM_EDEF_SLOTS = 11
_RESERVE_TIMEOUT_S = 5.0


class EventDefinition(Buffer):
    """CU linac eDef buffer."""

    beamcode: int
    inclusion_masks: Optional[list] = None
    exclusion_masks: Optional[list] = None

    @property
    def pv_prefix(self) -> str:
        return f"{_PREFIX}:{self.number}"

    @model_validator(mode="after")
    def _init_reserve(self) -> "EventDefinition":
        if self.number is None:
            self.number = self._reserve()
            self._configure()
        return self

    def _reserve(self) -> int:
        epics.caput(f"IOC:IN20:EV01:EDEFNAME", self.name, wait=True)
        elapsed = 0.0
        while elapsed < _RESERVE_TIMEOUT_S:
            for num in range(1, _NUM_EDEF_SLOTS + 1):
                edef_name = epics.caget(f"{_PREFIX}:{num}:NAME")
                if edef_name == self.name:
                    epics.caput(f"{_PREFIX}:{num}:USERNAME", str(self.user))
                    return num
            time.sleep(0.05)
            elapsed += 0.05

        available = epics.caget(f"IOC:IN20:EV01:EDEFAVAIL")
        if available is not None and available < 1:
            raise ReservationError("No event definitions available.")
        raise ReservationError("Could not reserve an EDEF.")

    def _configure(self) -> None:
        self._set_n_avg(self.n_avg)
        self._set_n_measurements(self.n_measurements)
        epics.caput(f"{self.pv_prefix}:BEAMCODE", self.beamcode)
        if self.inclusion_masks is not None:
            self._set_masks("INCLUSION", self.inclusion_masks)
        if self.exclusion_masks is not None:
            self._set_masks("EXCLUSION", self.exclusion_masks)

    def _set_n_avg(self, value: int) -> None:
        epics.caput(f"{self.pv_prefix}:AVGCNT", value)

    def _set_n_measurements(self, value: int) -> None:
        epics.caput(f"{self.pv_prefix}:MEASCNT", value)

    # --- Lifecycle ---

    def release(self) -> None:
        if not self.is_reserved():
            raise ReservationError("EDEF was not reserved, cannot release.")
        epics.caput(f"{self.pv_prefix}:FREE", 1)

    # --- Acquisition ---

    def start(self) -> None:
        if not self.is_reserved():
            raise ReservationError("EDEF was not reserved, cannot start.")
        epics.caput(f"{self.pv_prefix}:CTRL", 1)

    def stop(self) -> None:
        if not self.is_reserved():
            raise ReservationError("EDEF was not reserved, cannot stop.")
        epics.caput(f"{self.pv_prefix}:CTRL", 0)

    def is_complete(self) -> bool:
        if not self.is_reserved():
            raise ReservationError("EDEF was not reserved.")
        acquired = epics.caget(f"{self.pv_prefix}:CNT")
        to_acquire = epics.caget(f"{self.pv_prefix}:CNTMAX")
        return acquired == to_acquire

    @property
    def num_acquired(self) -> int:
        return epics.caget(f"{self.pv_prefix}:CNT")

    # --- Masks ---

    def _set_masks(self, mask_type: str, masks: list) -> None:
        self._clear_masks(mask_type)
        cache = self._get_mask_cache()
        bit_mask = 0
        for mask in masks:
            bit_num = cache[mask]
            bit_mask = bit_mask | (1 << (bit_num + 32))
        for modifier_num in (5, 4, 3, 2, 1):
            mod_mask = (bit_mask >> 32 * (modifier_num + 1)) & 0xFFFFFFFF
            epics.caput(
                f"{self.pv_prefix}:{mask_type}{modifier_num}",
                mod_mask,
                wait=True,
            )
            time.sleep(0.05)

    def _clear_masks(self, mask_type: str) -> None:
        for n in range(1, 6):
            epics.caput(
                f"{self.pv_prefix}:{mask_type}{n}", 0, wait=True
            )

    def _get_mask_cache(self) -> dict:
        bit_name_pvs = [f"PNBN:SYS0:{n}:NAME" for n in range(1, 141)]
        bit_pos_pvs = [f"PNBN:SYS0:{n}:BITP" for n in range(1, 141)]
        names = epics.caget_many(bit_name_pvs)
        positions = epics.caget_many(bit_pos_pvs)
        return dict(zip(names, positions))
