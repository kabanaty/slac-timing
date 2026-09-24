import time as _time
import warnings
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, PrivateAttr

from slac_timing.pvs import BufferPVs


class ReservationError(Exception):
    pass


class BufferSizeError(Exception):
    """Raised when buffer data size does not match n_measurements after retries."""

    pass


class Buffer(BaseModel, ABC):
    """Abstract base for timing buffers.

    Reserves a buffer on construction. Use as a context manager
    or call release() explicitly when done.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    user: str
    number: Optional[int] = None
    n_measurements: int
    n_avg: int = 1

    _pvs: Optional[BufferPVs] = PrivateAttr(default=None)

    @property
    @abstractmethod
    def pv_prefix(self) -> str:
        """Full PV prefix for this buffer instance, e.g. 'EDEF:SYS0:3'."""
        ...

    @abstractmethod
    def _create_pvs(self) -> BufferPVs:
        """Create the PV container for this buffer type."""
        ...

    @property
    def pvs(self) -> BufferPVs:
        if self._pvs is None:
            raise ReservationError("PVs not available: buffer not reserved.")
        return self._pvs

    def _init_pvs(self) -> None:
        self._pvs = self._create_pvs()

    # --- Lifecycle ---

    @abstractmethod
    def _reserve(self) -> int:
        """Reserve a buffer and return its number."""
        ...

    @abstractmethod
    def release(self) -> None:
        """Release the buffer back to the system."""
        ...

    def is_reserved(self) -> bool:
        return self.number is not None and self.number != 0

    def _require_reserved(self, action: str) -> None:
        if not self.is_reserved():
            raise ReservationError(f"Buffer not reserved, cannot {action}.")

    def __enter__(self) -> "Buffer":
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    # --- Acquisition ---

    @abstractmethod
    def start(self) -> None:
        """Begin data acquisition."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop data acquisition."""
        ...

    @abstractmethod
    def is_complete(self) -> bool:
        """Check if acquisition has finished."""
        ...

    def wait(self, timeout: float = 60.0) -> None:
        """Block until acquisition completes or timeout."""
        import time

        start = time.time()
        while not self.is_complete():
            if time.time() - start > timeout:
                raise TimeoutError("Buffer acquisition timed out.")
            time.sleep(0.05)

    @property
    @abstractmethod
    def num_acquired(self) -> int:
        """Number of measurements collected so far."""
        ...

    # --- Data retrieval ---

    def buffer_pv(self, pv: str, suffix: str = "HST") -> str:
        """Construct full buffered PV name: {pv}{suffix}{number}"""
        return f"{pv}{suffix}{self.number}"

    def get(
        self,
        pv: str,
        *,
        pad: bool = False,
        fill_value: float = np.nan,
        retries: int = 0,
        retry_delay: float = 1.0,
        trim_stale: bool = False,
        trim_offset: int | None = None,
    ) -> Optional[np.ndarray]:
        """Get buffer data for a single PV.

        Args:
            pv: PV name (without HST suffix or buffer number).
            pad: If True, pad short data to n_measurements with fill_value,
                and replace None with a full fill_value array.
            fill_value: Value used for padding (default NaN).
            retries: Number of re-fetch attempts on size mismatch.
            retry_delay: Seconds between retry attempts.
            trim_stale: If True and raw data exceeds n_measurements, detect
                which end contains stale (flat) data and trim it instead of
                blindly taking from the front.
            trim_offset: If set, skip this many samples from the front of
                oversized raw data. Used to align multiple PVs to the same
                buffer window. Mutually exclusive with trim_stale.

        Returns:
            Array of length n_measurements (when pad=True), or None/short array otherwise.

        Raises:
            BufferSizeError: If retries > 0 and data size still mismatches after all attempts.
            ValueError: If both trim_stale and trim_offset are provided.
        """
        if trim_stale:
            warnings.warn(
                "trim_stale is a temporary workaround for firmware that "
                "over-reports buffer length and will be removed once the "
                "firmware is fixed.",
                FutureWarning,
                stacklevel=2,
            )
        if trim_offset is not None:
            warnings.warn(
                "trim_offset is a temporary workaround for firmware that "
                "over-reports buffer length and will be removed once the "
                "firmware is fixed.",
                FutureWarning,
                stacklevel=2,
            )
        if trim_stale and trim_offset is not None:
            raise ValueError(
                "trim_stale and trim_offset are mutually exclusive."
            )

        import epics

        data = self._fetch_single(
            epics, pv, trim_stale=trim_stale, trim_offset=trim_offset
        )

        if retries > 0 and self.n_measurements > 0:
            for _ in range(retries):
                if data is not None and len(data) == self.n_measurements:
                    break
                _time.sleep(retry_delay)
                data = self._fetch_single(
                    epics, pv, trim_stale=trim_stale, trim_offset=trim_offset
                )
            else:
                if data is None or len(data) != self.n_measurements:
                    if not pad:
                        raise BufferSizeError(
                            f"Expected {self.n_measurements} points for {pv}, "
                            f"got {len(data) if data is not None else 'None'} "
                            f"after {retries} retries."
                        )

        return self._apply_pad(data, pad, fill_value)

    def get_many(
        self,
        pvs: list[str],
        *,
        pad: bool = False,
        fill_value: float = np.nan,
        retries: int = 0,
        retry_delay: float = 1.0,
    ) -> dict[str, Optional[np.ndarray]]:
        """Batched read via caget_many.

        Args:
            pvs: List of PV names.
            pad: If True, pad short data and replace None with fill_value arrays.
            fill_value: Value used for padding (default NaN).
            retries: Number of re-fetch attempts on any size mismatch in the batch.
            retry_delay: Seconds between retry attempts.

        Raises:
            BufferSizeError: If retries > 0 and any PV still mismatches after all attempts.
        """
        import epics

        results = self._fetch_many(epics, pvs)

        if retries > 0 and self.n_measurements > 0:
            for _ in range(retries):
                if self._batch_sizes_ok(results):
                    break
                _time.sleep(retry_delay)
                results = self._fetch_many(epics, pvs)
            else:
                if not self._batch_sizes_ok(results):
                    if not pad:
                        raise BufferSizeError(
                            f"Batch size mismatch after {retries} retries."
                        )

        if pad:
            return {
                pv: self._apply_pad(data, pad, fill_value)
                for pv, data in results.items()
            }
        return results

    def get_data_buffer(self, pv: str, **kwargs) -> Optional[np.ndarray]:
        """Compatibility alias for get()."""
        return self.get(pv, **kwargs)

    # --- Internal helpers ---

    def _apply_pad(
        self, data: Optional[np.ndarray], pad: bool, fill_value: float
    ) -> Optional[np.ndarray]:
        if not pad or self.n_measurements <= 0:
            return data
        if data is None:
            return np.full(self.n_measurements, fill_value)
        if len(data) < self.n_measurements:
            padded = np.full(self.n_measurements, fill_value)
            padded[: len(data)] = data
            return padded
        return data

    def _compute_trim_offset(self, data: np.ndarray) -> int:
        """Return the number of stale front samples to skip.

        Uses variance of the excess region at each end to decide whether
        the front or back of the buffer contains stale (flat) data.

        Returns 0 when no front-trimming is needed.
        """
        n = self.n_measurements
        if len(data) <= n:
            return 0

        excess = len(data) - n
        if excess < 10:
            return 0

        front_var = float(np.var(data[:excess]))
        back_var = float(np.var(data[-excess:]))

        if front_var == 0.0 and back_var == 0.0:
            return 0

        if front_var < back_var:
            warnings.warn(
                f"Trimmed {excess} stale samples from front of buffer "
                f"(front_var={front_var:.4g}, back_var={back_var:.4g}). "
                f"Returning last {n} of {len(data)} samples.",
                stacklevel=4,
            )
            return excess

        if back_var < front_var:
            warnings.warn(
                f"Trimmed {excess} stale samples from back of buffer "
                f"(front_var={front_var:.4g}, back_var={back_var:.4g}). "
                f"Returning first {n} of {len(data)} samples.",
                stacklevel=4,
            )
            return 0

        return 0

    def _find_active_window(self, data: np.ndarray) -> np.ndarray:
        offset = self._compute_trim_offset(data)
        n = self.n_measurements
        return data[offset : offset + n]

    def compute_trim_offset(self, pv: str) -> int:
        """Fetch raw data for *pv* and return the stale-data trim offset.

        .. deprecated::
            Temporary workaround for firmware that over-reports buffer
            length. Will be removed once the firmware is fixed.

        The offset is the number of samples to skip from the front so that
        ``data[offset : offset + n_measurements]`` contains the active window.
        Returns 0 when no trimming is needed.

        This is intended to be called once for a reference PV (e.g. motor
        position), and the resulting offset passed to subsequent
        :meth:`get` calls via ``trim_offset`` so all PVs use the same window.
        """
        warnings.warn(
            "compute_trim_offset is a temporary workaround for firmware "
            "that over-reports buffer length and will be removed once the "
            "firmware is fixed.",
            DeprecationWarning,
            stacklevel=2,
        )
        import epics

        p = epics.PV(self.buffer_pv(pv), auto_monitor=False)
        data = p.get(use_monitor=False, timeout=5.0)
        self._clear_pv_state(epics, p)
        if data is None:
            return 0
        return self._compute_trim_offset(data)

    def _batch_sizes_ok(self, results: dict[str, Optional[np.ndarray]]) -> bool:
        for data in results.values():
            if data is None or len(data) != self.n_measurements:
                return False
        return True

    def _fetch_single(
        self,
        epics,
        pv: str,
        trim_stale: bool = False,
        trim_offset: int | None = None,
    ) -> Optional[np.ndarray]:
        p = epics.PV(self.buffer_pv(pv), auto_monitor=False)
        data = p.get(use_monitor=False, timeout=5.0)
        self._clear_pv_state(epics, p)
        if data is None:
            return None
        if self.n_measurements > 0:
            if trim_offset is not None and len(data) > self.n_measurements:
                return data[trim_offset : trim_offset + self.n_measurements]
            if trim_stale and len(data) > self.n_measurements:
                return self._find_active_window(data)
            return data[: self.n_measurements]
        return data

    def _clear_pv_state(self, epics, pv) -> None:
        """Disconnect pv and discard pyepics' cached last-read value for it."""
        pv.disconnect()
        ctx = epics.ca.current_context()
        if ctx is None:
            return
        # No public pyepics API for this -- reaches into epics.ca's internals.
        context_cache = epics.ca._cache.get(ctx)
        if context_cache is None:
            return
        entry = context_cache.get(pv.pvname)
        if entry is not None:
            entry.get_results.clear()

    def _fetch_many(self, epics, pvs: list[str]) -> dict[str, Optional[np.ndarray]]:
        hst_pvs = [self.buffer_pv(pv) for pv in pvs]
        raw = epics.caget_many(hst_pvs)
        results = {}
        for pv, data in zip(pvs, raw):
            if data is None:
                results[pv] = None
            elif self.n_measurements > 0:
                results[pv] = data[: self.n_measurements]
            else:
                results[pv] = data
        return results
