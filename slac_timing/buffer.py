from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict


class ReservationError(Exception):
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

    @property
    @abstractmethod
    def pv_prefix(self) -> str:
        """Full PV prefix for this buffer instance, e.g. 'EDEF:SYS0:3'."""
        ...

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

    def get(self, pv: str) -> Optional[np.ndarray]:
        """Get buffer data for a single PV. Returns None if unreachable."""
        import epics

        data = epics.caget(self.buffer_pv(pv))
        if data is None:
            return None
        if self.n_measurements > 0:
            return data[: self.n_measurements]
        return data

    def get_many(self, pvs: list[str]) -> dict[str, Optional[np.ndarray]]:
        """Batched read via caget_many. Returns None for failed PVs."""
        import epics

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
