import time
from typing import ClassVar, Optional

from pydantic import model_validator

from slac_timing.buffer import Buffer, ReservationError
import slac_timing.pvs


_PREFIX = "EDEF:SYS0"
_NUM_EDEF_SLOTS = 11
_RESERVE_TIMEOUT_S = 5.0
_SYSTEM = slac_timing.pvs.EventDefinitionSystemPVs()


class EventDefinition(Buffer):
    """CU linac eDef buffer."""

    BEAMCODE_MAP: ClassVar[dict[str, int]] = {
        "CU_HXR": 1,
        "CU_SXR": 2,
    }

    beamcode: int
    inclusion_masks: Optional[list] = None
    exclusion_masks: Optional[list] = None

    @property
    def pv_prefix(self) -> str:
        return f"{_PREFIX}:{self.number}"

    def _create_pvs(self) -> slac_timing.pvs.EventDefinitionPVs:
        return slac_timing.pvs.EventDefinitionPVs(self.pv_prefix)

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
        if _SYSTEM.reserve_name.put(self.name, wait=True) is None:
            raise ReservationError(
                f"Could not reach edef system pv={_SYSTEM.reserve_name.pvname}"
            )
        elapsed = 0.0
        current_name_list = [None] * 11
        while elapsed < _RESERVE_TIMEOUT_S:
            for num in range(1, _NUM_EDEF_SLOTS + 1):
                edef_name = _SYSTEM.slot_names[num].get(as_string=True)
                if edef_name is None:
                    raise ReservationError(
                        f"Could not reach edef system pv={_SYSTEM.slot_names[num].pvname}"
                    )
                if edef_name == self.name:
                    if _SYSTEM.slot_usernames[num].put(str(self.user), wait=True) is None:
                        raise ReservationError(
                            f"Could not reach edef system pv={_SYSTEM.slot_usernames[num].pvname}"
                        )
                    return num
                current_name_list[num - 1] = edef_name
            time.sleep(0.05)
            elapsed += 0.05

        available = _SYSTEM.available.get()
        if available is None:
            raise ReservationError(
                f"Could not reach edef system pv={_SYSTEM.available.pvname}"
            )
        elif available is not None and available < 1:
            raise ReservationError(
                f"No event definitions available. pv={_SYSTEM.available.pvname}, value={available}"
            )
        msg = "Could not reserve an EDEF."
        for num in range(1, _NUM_EDEF_SLOTS + 1):
            msg += f"\npv={_SYSTEM.slot_names[num].pvname}, value={current_name_list[num - 1]}"
        msg += f"\npv={_SYSTEM.available.pvname}, value={available}"
        raise ReservationError(msg)

    def _configure(self) -> None:
        pv_values = {
            "avgcnt": self.n_avg,
            "meascnt": self.n_measurements,
            "beamcode": self.beamcode,
        }
        for name, value in pv_values.items():
            pv = getattr(self.pvs, name)
            res = pv.put(value, wait=True)
            if res is None:
                raise ReservationError(f"PV Timed Out. pv={pv.pvname}")
        if self.inclusion_masks is not None:
            self._set_masks("inclusion", self.inclusion_masks)
        if self.exclusion_masks is not None:
            self._set_masks("exclusion", self.exclusion_masks)

    # --- Lifecycle ---

    def release(self) -> None:
        self._require_reserved("release")
        self.pvs.free.put(1)
        self._clear_ca_cache()

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
            bit_num = cache[mask]
            bit_mask = bit_mask | (1 << (bit_num + 32))
        for modifier_num in (5, 4, 3, 2, 1):
            mod_mask = (bit_mask >> 32 * (modifier_num + 1)) & 0xFFFFFFFF
            if not (res := group[modifier_num].put(mod_mask, wait=True)):
                raise ReservationError(
                    f"PV timed out. pv={group[modifier_num].pvname} value={res}"
                )
            time.sleep(0.05)

    def _clear_masks(self, group) -> None:
        res = [group[n].put(0, wait=True) for n in range(1, 6)]
        if not all(r is not None for r in res):
            msg = "PV timed out."
            for i in range(0, len(res)):
                msg += f"\npv={group[i + 1].pvname}, value={res[i]}"
            raise ReservationError(msg)

    def _get_mask_cache(self) -> dict:
        names = self.pvs.pnbn_names.get_many(as_string=True)
        if not all(n is not None for n in names):
            msg = "PV timed out."
            for i in range(0, len(names)):
                msg += f"\npv={self.pvs.pnbn_names[i + 1].pvname}, value={names[i]}"
            raise ReservationError(msg)
        positions = self.pvs.pnbn_positions.get_many()
        if not all(n is not None for n in positions):
            msg = "PV timed out."
            for i in range(0, len(names)):
                msg += f"\npv={self.pvs.pnbn_positions[i + 1].pvname}, value={positions[i]}"
            raise ReservationError(msg)
        return dict(zip(names, positions))
