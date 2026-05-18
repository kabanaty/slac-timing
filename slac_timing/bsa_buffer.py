import time
from typing import Optional

import epics
from pydantic import model_validator

from slac_timing.buffer import Buffer, ReservationError


_PREFIX = "BSA:SYS0:1"
_NUM_MASK_BITS = 9
_RESERVE_TIMEOUT_S = 5.0


class BSABuffer(Buffer):
    """SC linac BSA buffer."""

    destination_mode: Optional[str] = None
    destination_masks: Optional[list] = None
    rate_mode: Optional[str] = None
    fixed_rate: Optional[str] = None
    ac_rate: Optional[str] = None
    timeslots: Optional[list] = None

    @property
    def pv_prefix(self) -> str:
        return f"{_PREFIX}:{self.number}"

    @model_validator(mode="after")
    def _init_reserve(self) -> "BSABuffer":
        if self.number is None:
            self.number = self._reserve()
            self._configure()
        return self

    def _reserve(self) -> int:
        available = epics.caget(f"{_PREFIX}:NFREEBSA")
        if available is not None and available < 1:
            raise ReservationError("No BSA buffers available.")

        epics.caput(f"{_PREFIX}:BSANAME", self.name, wait=True)
        elapsed = 0.0
        while elapsed < _RESERVE_TIMEOUT_S:
            for num in range(21, 50):
                buffer_name = epics.caget(f"{_PREFIX}:{num}:NAME")
                if buffer_name == self.name:
                    epics.caput(f"{_PREFIX}:{num}:USERNAME", str(self.user))
                    return num
            time.sleep(0.05)
            elapsed += 0.05

        if not epics.caget(f"{_PREFIX}:NFREEBSA"):
            raise ReservationError("No BSA buffers available.")
        raise ReservationError("Could not reserve a BSA buffer.")

    def _configure(self) -> None:
        epics.caput(f"{self.pv_prefix}:AVGCNT", self.n_avg)
        epics.caput(f"{self.pv_prefix}:MEASCNT", self.n_measurements)
        if self.destination_mode is not None:
            epics.caput(f"{self.pv_prefix}:DESTMODE", self.destination_mode)
        if self.destination_masks is not None:
            self._set_destination_masks(self.destination_masks)
        if self.rate_mode is not None:
            epics.caput(f"{self.pv_prefix}:RATEMODE", self.rate_mode)
        if self.fixed_rate is not None:
            epics.caput(f"{self.pv_prefix}:FIXEDRATE", self.fixed_rate)
        if self.ac_rate is not None:
            epics.caput(f"{self.pv_prefix}:ACRATE", self.ac_rate)
        if self.timeslots is not None:
            self._set_timeslots(self.timeslots)

    # --- Lifecycle ---

    def release(self) -> None:
        if not self.is_reserved():
            raise ReservationError("BSA buffer was not reserved, cannot release.")
        epics.caput(f"{self.pv_prefix}:FREE", 1)

    # --- Acquisition ---

    def start(self) -> None:
        if not self.is_reserved():
            raise ReservationError("BSA buffer was not reserved, cannot start.")
        epics.caput(f"{self.pv_prefix}:CTRL", 1)
        deadline = time.time() + 1.0
        while self.is_complete():
            time.sleep(0.01)
            if time.time() > deadline:
                raise ReservationError("BSA buffer was not able to start.")

    def stop(self) -> None:
        if not self.is_reserved():
            raise ReservationError("BSA buffer was not reserved, cannot stop.")
        epics.caput(f"{self.pv_prefix}:CTRL", 0)

    def is_complete(self) -> bool:
        if not self.is_reserved():
            raise ReservationError("BSA buffer was not reserved.")
        return bool(epics.caget(f"{self.pv_prefix}:HST_READY"))

    @property
    def num_acquired(self) -> int:
        return epics.caget(f"{self.pv_prefix}:CNT")

    # --- Destination masks ---

    def _set_destination_masks(self, masks: list) -> None:
        self._clear_masks()
        cache = self._get_mask_cache()
        bit_mask = 0
        for mask in masks:
            bit_num = cache[mask]
            epics.caput(f"{self.pv_prefix}:DST{bit_num}", 1)
            bit_mask = bit_mask | (1 << bit_num)
        epics.caput(f"{self.pv_prefix}:DESTMASK", bit_mask)

    def _clear_masks(self) -> None:
        epics.caput(f"{self.pv_prefix}:DESTMASK", 0)
        for i in range(0, _NUM_MASK_BITS + 1):
            epics.caput(f"{self.pv_prefix}:DST{i}", 0)

    def _get_mask_cache(self) -> dict:
        bit_nums = list(range(0, _NUM_MASK_BITS + 1))
        bit_name_pvs = [
            f"{self.pv_prefix}:DST{n}.DESC" for n in bit_nums
        ]
        names = epics.caget_many(bit_name_pvs)
        return dict(zip(names, bit_nums))

    # --- Timeslots ---

    def _set_timeslots(self, ts_list: list) -> None:
        if isinstance(ts_list, int):
            ts_list = [ts_list]
        for ts in range(1, 7):
            active = 1 if ts in ts_list else 0
            epics.caput(f"{self.pv_prefix}:TS{ts}", active)
