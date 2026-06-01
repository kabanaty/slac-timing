import epics
import gc
import pytest
from slac_timing.buffer import ReservationError
from slicops import unit_util
import sys


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


@pytest.mark.ioc_yaml("fail_config_pvs.yaml")
def test_fail_config_pvs():
    import slac_timing.event_definition

    with pytest.raises(ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert str(e.value) == "PV Timed Out. pv=EDEF:SYS0:1:AVGCNT"


@pytest.mark.ioc_yaml("fail_clear_mask_pvs.yaml")
def test_fail_clear_masks_pvs():
    import slac_timing.event_definition

    with pytest.raises(ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name",
            user="user",
            n_measurements=1,
            n_avg=1,
            beamcode=0,
            inclusion_masks=["foo", "bar"],
        )
    error_msg = "PV timed out."
    for i in range(1, 6):
        error_msg += f"\npv=EDEF:SYS0:1:INCLUSION{i}, value=None"
    assert str(e.value) == error_msg


@pytest.mark.ioc_yaml("fail_mask_name_pvs.yaml")
def test_fail_mask_name_pvs():
    import slac_timing.event_definition

    with pytest.raises(ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name",
            user="user",
            n_measurements=1,
            n_avg=1,
            beamcode=0,
            inclusion_masks=["foo", "bar"],
        )
    error_msg = "PV timed out."
    for i in range(1, 141):
        error_msg += f"\npv=PNBN:SYS0:{i}:NAME, value=None"
    assert str(e.value) == error_msg


@pytest.mark.ioc_yaml("fail_mask_pos_pvs.yaml")
def test_fail_mask_pos_pvs():
    import slac_timing.event_definition

    with pytest.raises(ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name",
            user="user",
            n_measurements=1,
            n_avg=1,
            beamcode=0,
            inclusion_masks=["foo", "bar"],
        )
    error_msg = "PV timed out."
    for i in range(1, 141):
        error_msg += f"\npv=PNBN:SYS0:{i}:BITP, value=None"
    assert str(e.value) == error_msg
