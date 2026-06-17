import time as _time
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

    def _disconnect_pvs(self) -> None:
        """Disconnect all PV connections held by this buffer."""
        if self._pvs is not None:
            self._pvs.disconnect()
            self._pvs = None
        self._clear_ca_cache()

    def _clear_ca_cache(self) -> None:
        """Remove caget-created channels for this buffer from the CA cache."""
        import epics.ca
        from epics.pv import _PVcache_

        ctx = epics.ca.current_context()
        if ctx is None:
            return

        suffix = f"HST{self.number}"

        stale_pvids = [
            pvid for pvid in list(_PVcache_)
            if pvid[0].endswith(suffix)
        ]
        for pvid in stale_pvids:
            pv_obj = _PVcache_.pop(pvid, None)
            if pv_obj is not None:
                try:
                    pv_obj.disconnect()
                except BaseException:
                    pass

        context_cache = epics.ca._cache.get(ctx)
        if context_cache is None:
            return
        stale_names = [name for name in context_cache if name.endswith(suffix)]
        for name in stale_names:
            entry = context_cache.get(name)
            if entry is not None and getattr(entry, "chid", None) is not None:
                try:
                    epics.ca.clear_channel(entry.chid)
                except BaseException:
                    context_cache.pop(name, None)

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
    ) -> Optional[np.ndarray]:
        """Get buffer data for a single PV.

        Args:
            pv: PV name (without HST suffix or buffer number).
            pad: If True, pad short data to n_measurements with fill_value,
                and replace None with a full fill_value array.
            fill_value: Value used for padding (default NaN).
            retries: Number of re-fetch attempts on size mismatch.
            retry_delay: Seconds between retry attempts.

        Returns:
            Array of length n_measurements (when pad=True), or None/short array otherwise.

        Raises:
            BufferSizeError: If retries > 0 and data size still mismatches after all attempts.
        """
        import epics

        data = self._fetch_single(epics, pv)

        if retries > 0 and self.n_measurements > 0:
            for _ in range(retries):
                if data is not None and len(data) == self.n_measurements:
                    break
                _time.sleep(retry_delay)
                data = self._fetch_single(epics, pv)
            else:
                if data is None or len(data) != self.n_measurements:
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
                    raise BufferSizeError(
                        f"Batch size mismatch after {retries} retries."
                    )

        if pad:
            return {pv: self._apply_pad(data, pad, fill_value) for pv, data in results.items()}
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

    def _batch_sizes_ok(self, results: dict[str, Optional[np.ndarray]]) -> bool:
        for data in results.values():
            if data is None or len(data) != self.n_measurements:
                return False
        return True

    def _fetch_single(self, epics, pv: str) -> Optional[np.ndarray]:
        data = epics.caget(self.buffer_pv(pv))
        if data is None:
            return None
        if self.n_measurements > 0:
            return data[: self.n_measurements]
        return data

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


