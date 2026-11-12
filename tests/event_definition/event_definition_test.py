import gc
import pytest
import sys
from slicops import unit_util
import epics


@pytest.fixture(scope="function", autouse=True)
def reset_event_definition(request):
    ioc_file = request.node.get_closest_marker("ioc_yaml")
    if ioc_file is not None:
        with unit_util.start_ioc(ioc_file.args[0], db_yaml="db.yaml"):
            epics.ca.initialize_libca()
            yield
            sys.modules.pop("slac_timing.event_definition", None)
            epics.ca.finalize_libca()
            gc.collect()
    else:
        epics.ca.initialize_libca()
        yield
        sys.modules.pop("slac_timing.event_definition", None)
        epics.ca.finalize_libca()
        gc.collect()


@pytest.mark.ioc_yaml("working_ioc.yaml")
def test_slot_name_timeout():
    import slac_timing.event_definition

    slac_timing.event_definition.EventDefinition(
        name="name",
        user="user",
        n_measurements=1,
        n_avg=1,
        beamcode=0,
        inclusion_masks=["TS1"],
    )


def _words(group):
    return [int(w) & 0xFFFFFFFF for w in group.get_many()]


@pytest.mark.ioc_yaml("masks_ioc.yaml")
def test_inclusion_masks_replace_defaults():
    import slac_timing.event_definition

    e = slac_timing.event_definition.EventDefinition(
        name="name",
        user="user",
        n_measurements=1,
        beamcode=1,
        inclusion_masks=["RATE_MPS_HXR_30HZ"],
    )
    # BITP 68 (RATE_MPS_HXR_30HZ) -> word 2 bit 4; pockcel_perm default cleared.
    assert _words(e.pvs.inclusion) == [0, 0x00000010, 0, 0, 0]
    # No exclusion masks requested -> TS2/3/5/6 defaults cleared.
    assert _words(e.pvs.exclusion) == [0, 0, 0, 0, 0]


@pytest.mark.ioc_yaml("masks_ioc.yaml")
def test_exclusion_masks_replace_defaults():
    import slac_timing.event_definition

    e = slac_timing.event_definition.EventDefinition(
        name="name",
        user="user",
        n_measurements=1,
        beamcode=1,
        inclusion_masks=["pockcel_perm"],
        exclusion_masks=["TS4"],
    )
    # TS4 is BITP 35 -> word 1 bit 3; TS2/3/5/6 defaults cleared.
    assert _words(e.pvs.exclusion) == [0x08, 0, 0, 0, 0]
    # pockcel_perm is BITP 83 -> word 2 bit 19.
    assert _words(e.pvs.inclusion) == [0, 0x00080000, 0, 0, 0]


@pytest.mark.ioc_yaml("masks_ioc.yaml")
def test_no_masks_clears_all_words():
    import slac_timing.event_definition

    e = slac_timing.event_definition.EventDefinition(
        name="name",
        user="user",
        n_measurements=1,
        beamcode=1,
    )
    assert _words(e.pvs.inclusion) == [0, 0, 0, 0, 0]
    assert _words(e.pvs.exclusion) == [0, 0, 0, 0, 0]


@pytest.mark.ioc_yaml("masks_ioc.yaml")
def test_high_bit_written_as_signed_word():
    import slac_timing.event_definition

    e = slac_timing.event_definition.EventDefinition(
        name="name",
        user="user",
        n_measurements=1,
        beamcode=1,
        inclusion_masks=["PHAS_DITHR"],
    )
    # PHAS_DITHR is BITP 63 -> word 1 bit 31, stored as a negative LONG.
    assert _words(e.pvs.inclusion) == [0x80000000, 0, 0, 0, 0]


@pytest.mark.ioc_yaml("masks_ioc.yaml")
def test_unknown_mask_name():
    import slac_timing.event_definition
    from slac_timing.buffer import ReservationError

    with pytest.raises(ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name",
            user="user",
            n_measurements=1,
            beamcode=1,
            inclusion_masks=["pockcel_perm", "NOT_A_MASK"],
        )
    assert str(e.value) == (
        "Unknown inclusion mask(s) ['NOT_A_MASK']; not found in "
        "PNBN:SYS0:1:NAME..PNBN:SYS0:140:NAME"
    )
    # Names are validated before any word is cleared.
    inclusion = slac_timing.pvs.EventDefinitionPVs("EDEF:SYS0:1").inclusion
    assert _words(inclusion) == [0, 0x00080000, 0, 0, 0]


@pytest.mark.ioc_yaml("masks_ioc.yaml")
def test_mask_bit_outside_words():
    import slac_timing.event_definition
    from slac_timing.buffer import ReservationError

    # YY has BITP 0; INCLUSION1..5 only cover BITP 32..191.
    with pytest.raises(ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name",
            user="user",
            n_measurements=1,
            beamcode=1,
            inclusion_masks=["YY"],
        )
    assert str(e.value) == (
        "inclusion mask 'YY' has BITP=0, outside "
        "EDEF:SYS0:1:INCLUSION1..EDEF:SYS0:1:INCLUSION5"
    )
