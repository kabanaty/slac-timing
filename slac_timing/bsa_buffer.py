import time
from typing import Optional

from pydantic import model_validator

from slac_timing.buffer import Buffer, ReservationError
from slac_timing.pvs import BSABufferPVs, BSASystemPVs


_PREFIX = "BSA:SYS0:1"
_NUM_MASK_BITS = 9
_RESERVE_TIMEOUT_S = 5.0
_SYSTEM = BSASystemPVs(_PREFIX)


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

    def _create_pvs(self) -> BSABufferPVs:
        return BSABufferPVs(self.pv_prefix)

    @model_validator(mode="after")
    def _init_reserve(self) -> "BSABuffer":
        if self.number is None:
            self.number = self._reserve()
            self._init_pvs()
            self._configure()
        else:
            self._init_pvs()
        return self

    def _reserve(self) -> int:
        available = _SYSTEM.nfree.get()
        if available is not None and available < 1:
            raise ReservationError("No BSA buffers available.")

        _SYSTEM.reserve_name.put(self.name, wait=True)
        elapsed = 0.0
        while elapsed < _RESERVE_TIMEOUT_S:
            for num in range(21, 50):
                buffer_name = _SYSTEM.slot_names[num].get()
                if buffer_name == self.name:
                    _SYSTEM.slot_usernames[num].put(str(self.user))
                    return num
            time.sleep(0.05)
            elapsed += 0.05

        if not _SYSTEM.nfree.get():
            raise ReservationError("No BSA buffers available.")
        raise ReservationError("Could not reserve a BSA buffer.")

    def _configure(self) -> None:
        self.pvs.avgcnt.put(self.n_avg)
        self.pvs.meascnt.put(self.n_measurements)
        if self.destination_mode is not None:
            self.pvs.destmode.put(self.destination_mode)
        if self.destination_masks is not None:
            self._set_destination_masks(self.destination_masks)
        if self.rate_mode is not None:
            self.pvs.ratemode.put(self.rate_mode)
        if self.fixed_rate is not None:
            self.pvs.fixedrate.put(self.fixed_rate)
        if self.ac_rate is not None:
            self.pvs.acrate.put(self.ac_rate)
        if self.timeslots is not None:
            self._set_timeslots(self.timeslots)

    # --- Lifecycle ---

    def release(self) -> None:
        self._require_reserved("release")
        self.pvs.free.put(1)

    # --- Acquisition ---

    def start(self) -> None:
        self._require_reserved("start")
        self.pvs.ctrl.put(1)
        deadline = time.time() + 1.0
        while self.is_complete():
            time.sleep(0.01)
            if time.time() > deadline:
                raise ReservationError("BSA buffer was not able to start.")

    def stop(self) -> None:
        self._require_reserved("stop")
        self.pvs.ctrl.put(0)

    def is_complete(self) -> bool:
        self._require_reserved("check completion")
        return bool(self.pvs.hst_ready.get())

    @property
    def num_acquired(self) -> int:
        return self.pvs.cnt.get()

    # --- Destination masks ---

    def _set_destination_masks(self, masks: list) -> None:
        self._clear_masks()
        cache = self._get_mask_cache()
        bit_mask = 0
        for mask in masks:
            bit_num = cache[mask]
            self.pvs.dst[bit_num].put(1)
            bit_mask = bit_mask | (1 << bit_num)
        self.pvs.destmask.put(bit_mask)

    def _clear_masks(self) -> None:
        self.pvs.destmask.put(0)
        for i in range(0, _NUM_MASK_BITS + 1):
            self.pvs.dst[i].put(0)

    def _get_mask_cache(self) -> dict:
        bit_nums = list(range(0, _NUM_MASK_BITS + 1))
        names = self.pvs.dst_desc.get_many()
        return dict(zip(names, bit_nums))

    # --- Timeslots ---

    def _set_timeslots(self, ts_list: list) -> None:
        if isinstance(ts_list, int):
            ts_list = [ts_list]
        for ts in range(1, 7):
            active = 1 if ts in ts_list else 0
            self.pvs.ts[ts].put(active)
