import time
from typing import ClassVar, Optional

from pydantic import model_validator

from slac_timing.buffer import Buffer, ReservationError
import slac_timing.pvs


_PREFIX = "EDEF:SYS0"
_NUM_EDEF_SLOTS = 11
_RESERVE_TIMEOUT_S = 5.0
_MASK_SETTLE_S = 0.1
_SYSTEM = slac_timing.pvs.EventDefinitionSystemPVs()


class EventDefinition(Buffer):
    """CU linac eDef buffer.

    At reservation all inclusion/exclusion mask words are cleared, including
    the defaults the IOC gives a new EDEF (e.g. pockcel_perm, TS2/3/5/6
    exclusions) and any bits left by a previous user, then exactly the
    requested masks are set. Masks are applied once, at reservation.

    rate_limit_hz is the rate of shots the masks let through (e.g. the BYKIK
    rate), or None if the buffer sees the full beam rate.
    """

    BEAMCODE_MAP: ClassVar[dict[str, int]] = {
        "CU_HXR": 1,
        "CU_SXR": 2,
    }

    beamcode: int
    inclusion_masks: Optional[list] = None
    exclusion_masks: Optional[list] = None
    rate_limit_hz: Optional[float] = None

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
                    if (
                        _SYSTEM.slot_usernames[num].put(str(self.user), wait=True)
                        is None
                    ):
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
        self._set_masks("inclusion", self.inclusion_masks or [])
        self._set_masks("exclusion", self.exclusion_masks or [])

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

    def _set_masks(self, mask_type: str, mask_names: list) -> None:
        """Clear the EDEF's mask words, then set exactly the named mask bits.

        Word n (n = 1..5) holds PNBN BITP 32n..32n+31. All names are checked
        before any word is written.
        """

        def _apply_mask(pvs, bits):
            for n, b in bits.items():
                if pvs[n].put(_to_int32(b), wait=True) is None:
                    raise ReservationError(
                        f"PV timed out. pv={pvs[n].pvname} value={b:#010x}"
                    )
            time.sleep(_MASK_SETTLE_S)

        def _assert_valid_names(names, name_map):
            invalid_names = [n for n in names if n not in name_map]
            if invalid_names:
                pv_names = self.pvs.pnbn_names.pvnames
                raise ReservationError(
                    f"Unknown {mask_type} mask(s) {invalid_names}; not found in "
                    f"{pv_names[0]}..{pv_names[-1]}"
                )

        def _assert_valid_pv_index(i, indicies):
            if i not in indicies:
                raise ReservationError(
                    f"{mask_type} mask {name!r} has pv index={i}, outside "
                    f"{pvs.pvnames[0]}..{pvs.pvnames[-1]}"
                )

        def _solve_index_and_bit(n):
            """Number n is defined as: pv_index * 32 + bit_num
            Where bit_num is the nth bit to flip.
            e.g.
                n = 34
                pv_index = 1
                bit_num = 2
                bit = 2 ** 2 = 100 in binary.

                n = 32
                pv_index = 1
                bit_num = 0
                bit = 2 ** 0 = 1 in binary.
            """
            pv_index, bit_num = divmod(int(n), 32)
            bit = 1 << bit_num
            return pv_index, bit

        pvs = getattr(self.pvs, mask_type)
        bits = dict.fromkeys(range(1, len(pvs) + 1), 0)

        if not mask_names:
            _apply_mask(pvs, bits)

        name_to_bit = self._create_mask_map()
        _assert_valid_names(mask_names, name_to_bit)
        for name in mask_names:
            bit = name_to_bit.get(name)
            i, one_bit = _solve_index_and_bit(bit)
            _assert_valid_pv_index(i, bits)
            # Flips one bit in the ith mask pv.
            # 100 | 000 = 100 and 100 | 100 = 100.
            bits[i] |= one_bit
        _apply_mask(pvs, bits)

    def _create_mask_map(self) -> dict:
        """Masks are identified by a string, and have an associated int.
        There is a 1-1 relationship PNBN:SYS0:X:NAME -> PNBN:SYS0:X:BITP
                                           Mask Name -> Mask Int
        """

        def _get_many(pvs):
            out = pvs.get_many(as_string=True)
            invalid_indicies = [i for i, o in enumerate(out) if not o]
            if not invalid_indicies:
                return out
            msg = "PV timed out."
            for i in invalid_indicies:
                msg += f"\npv={pvs[i + 1].pvname}, value={out[i]}"
            raise ReservationError(msg)

        return dict(
            zip(
                _get_many(self.pvs.pnbn_names),
                map(int, _get_many(self.pvs.pnbn_positions)),
            )
        )


def _to_int32(word: int) -> int:
    """Convert an unsigned 32-bit word to the signed value a LONG PV holds.

    Raises OverflowError if ``word`` is outside 0..2**32 - 1, so an
    out-of-range value is never sent to the IOC.
    """
    return int.from_bytes(word.to_bytes(4, "big", signed=False), "big", signed=True)
