import time
from typing import Optional

from pydantic import model_validator

from slac_timing.buffer import Buffer, ReservationError
from slac_timing.pvs import EventDefinitionPVs, EventDefinitionSystemPVs


_PREFIX = "EDEF:SYS0"
_NUM_EDEF_SLOTS = 11
_RESERVE_TIMEOUT_S = 5.0
_SYSTEM = EventDefinitionSystemPVs()


class EventDefinition(Buffer):
    """CU linac eDef buffer."""

    BEAMCODE_MAP = {
        "CU_HXR": 1,
        "CU_SXR": 2,
    }

    beamcode: int
    inclusion_masks: Optional[list] = None
    exclusion_masks: Optional[list] = None

    @property
    def pv_prefix(self) -> str:
        return f"{_PREFIX}:{self.number}"

    def _create_pvs(self) -> EventDefinitionPVs:
        return EventDefinitionPVs(self.pv_prefix)

    @model_validator(mode="after")
    def _init_reserve(self) -> "EventDefinition":
        if self.number is None:
            self.number = self._reserve()
            self._init_pvs()
            self._configure()
        else:
            self._init_pvs()
        return self

    def _reserve(self) -> int:
        _SYSTEM.reserve_name.put(self.name, wait=True)
        elapsed = 0.0
        while elapsed < _RESERVE_TIMEOUT_S:
            for num in range(1, _NUM_EDEF_SLOTS + 1):
                edef_name = _SYSTEM.slot_names[num].get()
                if edef_name == self.name:
                    _SYSTEM.slot_usernames[num].put(str(self.user))
                    return num
            time.sleep(0.05)
            elapsed += 0.05

        available = _SYSTEM.available.get()
        if available is not None and available < 1:
            raise ReservationError(
                f"No event definitions available for {self.name!r} (user={self.user!r}) "
                f"after waiting {_RESERVE_TIMEOUT_S}s. "
                f"Check IOC:IN20:EV01:EDEFAVAIL and EDEF:SYS0:{{1-11}}:NAME to see current holders."
            )
        raise ReservationError(
            f"Could not reserve an EDEF for {self.name!r} (user={self.user!r}) "
            f"within {_RESERVE_TIMEOUT_S}s. The system reported free slots but none matched. "
            f"Try again or check EDEF:SYS0:{{1-11}}:NAME for stale reservations."
        )

    def _configure(self) -> None:
        self.pvs.avgcnt.put(self.n_avg)
        self.pvs.meascnt.put(self.n_measurements)
        self.pvs.beamcode.put(self.beamcode)
        if self.inclusion_masks is not None:
            self._set_masks("inclusion", self.inclusion_masks)
        if self.exclusion_masks is not None:
            self._set_masks("exclusion", self.exclusion_masks)

    # --- Lifecycle ---

    def release(self) -> None:
        self._require_reserved("release")
        self.pvs.free.put(1)

    # --- Acquisition ---

    def start(self) -> None:
        self._require_reserved("start")
        self.pvs.ctrl.put(1)

    def stop(self) -> None:
        self._require_reserved("stop")
        self.pvs.ctrl.put(0)

    def is_complete(self) -> bool:
        self._require_reserved("check completion")
        acquired = self.pvs.cnt.get()
        to_acquire = self.pvs.cntmax.get()
        return acquired == to_acquire

    @property
    def num_acquired(self) -> int:
        self._require_reserved("check number acquired")
        return self.pvs.cnt.get()

    # --- Masks ---

    def _set_masks(self, mask_type: str, masks: list) -> None:
        group = getattr(self.pvs, mask_type)
        self._clear_masks(group)
        cache = self._get_mask_cache()
        bit_mask = 0
        for mask in masks:
            try:
                bit_num = cache[mask]
            except KeyError:
                valid = list(cache.keys())
                raise ValueError(
                    f"Invalid {mask_type} mask {mask!r}. Valid options: {valid}"
                ) from None
            bit_mask = bit_mask | (1 << (bit_num + 32))
        for modifier_num in (5, 4, 3, 2, 1):
            mod_mask = (bit_mask >> 32 * (modifier_num + 1)) & 0xFFFFFFFF
            group[modifier_num].put(mod_mask, wait=True)
            time.sleep(0.05)

    def _clear_masks(self, group) -> None:
        for n in range(1, 6):
            group[n].put(0, wait=True)

    def _get_mask_cache(self) -> dict:
        names = self.pvs.pnbn_names.get_many()
        positions = self.pvs.pnbn_positions.get_many()
        return dict(zip(names, positions))
