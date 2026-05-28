import epics
from slac_tools import LazyPV


class IndexedPVGroup:
    """Indexed access for parametric PVs like DST{0-9} or TS{1-6}."""

    def __init__(self, prefix: str, suffix_template: str, indices: range):
        self._prefix = prefix
        self._suffix_template = suffix_template
        self._indices = indices
        self._pvs: dict[int, LazyPV] = {}

    def __getitem__(self, index: int) -> LazyPV:
        if index not in self._indices:
            raise IndexError(
                f"Index {index} out of range "
                f"{self._indices.start}-{self._indices.stop - 1}"
            )
        if index not in self._pvs:
            suffix = self._suffix_template.format(index)
            self._pvs[index] = LazyPV(f"{self._prefix}:{suffix}")
        return self._pvs[index]

    def __iter__(self):
        for i in self._indices:
            yield self[i]

    def __len__(self) -> int:
        return len(self._indices)

    @property
    def pvnames(self) -> list[str]:
        return [
            f"{self._prefix}:{self._suffix_template.format(i)}" for i in self._indices
        ]

    def get_many(self, **kwargs) -> list:
        """Batch-read all PVs in this group via epics.caget_many."""
        return epics.caget_many(self.pvnames, **kwargs)


# --- System PV Containers (reservation protocol) ---


class BSASystemPVs:
    """System-level PVs for BSA buffer reservation."""

    def __init__(self, prefix: str = "BSA:SYS0:1"):
        self.nfree = LazyPV(f"{prefix}:NFREEBSA")
        self.reserve_name = LazyPV(f"{prefix}:BSANAME")
        self.slot_names = IndexedPVGroup(prefix, "{}:NAME", range(21, 50))
        self.slot_usernames = IndexedPVGroup(prefix, "{}:USERNAME", range(21, 50))


class EventDefinitionSystemPVs:
    """System-level PVs for EDEF reservation."""

    def __init__(self):
        self.reserve_name = LazyPV("IOC:IN20:EV01:EDEFNAME")
        self.available = LazyPV("IOC:IN20:EV01:EDEFAVAIL")
        self.slot_names = IndexedPVGroup("EDEF:SYS0", "{}:NAME", range(1, 12))
        self.slot_usernames = IndexedPVGroup("EDEF:SYS0", "{}:USERNAME", range(1, 12))


# --- Buffer PV Containers ---


class BufferPVs:
    """Base PV container with shared buffer suffixes."""

    def __init__(self, prefix: str):
        self._prefix = prefix
        self.avgcnt = LazyPV(f"{prefix}:AVGCNT")
        self.meascnt = LazyPV(f"{prefix}:MEASCNT")
        self.ctrl = LazyPV(f"{prefix}:CTRL")
        self.free = LazyPV(f"{prefix}:FREE")
        self.cnt = LazyPV(f"{prefix}:CNT")


class BSABufferPVs(BufferPVs):
    """PVs specific to SC linac BSA buffers."""

    def __init__(self, prefix: str):
        super().__init__(prefix)
        self.destmode = LazyPV(f"{prefix}:DESTMODE")
        self.destmask = LazyPV(f"{prefix}:DESTMASK")
        self.ratemode = LazyPV(f"{prefix}:RATEMODE")
        self.fixedrate = LazyPV(f"{prefix}:FIXEDRATE")
        self.acrate = LazyPV(f"{prefix}:ACRATE")
        self.hst_ready = LazyPV(f"{prefix}:HST_READY")
        self.dst = IndexedPVGroup(prefix, "DST{}", range(0, 10))
        self.dst_desc = IndexedPVGroup(prefix, "DST{}.DESC", range(0, 10))
        self.ts = IndexedPVGroup(prefix, "TS{}", range(1, 7))


class EventDefinitionPVs(BufferPVs):
    """PVs specific to CU linac event definitions."""

    def __init__(self, prefix: str):
        super().__init__(prefix)
        self.beamcode = LazyPV(f"{prefix}:BEAMCODE")
        self.cntmax = LazyPV(f"{prefix}:CNTMAX")
        self.inclusion = IndexedPVGroup(prefix, "INCLUSION{}", range(1, 6))
        self.exclusion = IndexedPVGroup(prefix, "EXCLUSION{}", range(1, 6))
        self.pnbn_names = IndexedPVGroup("PNBN:SYS0", "{}:NAME", range(1, 141))
        self.pnbn_positions = IndexedPVGroup("PNBN:SYS0", "{}:BITP", range(1, 141))
