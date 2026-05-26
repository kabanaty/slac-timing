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
            epics.ca.finalize_libca()

    else:
        epics.ca.initialize_libca()
        yield
        epics.ca.finalize_libca()
    sys.modules.pop("slac_timing.event_definition", None)


def test_edef_name_timeout():
    import pytest
    import slac_timing.event_definition
    import slac_timing.buffer

    with pytest.raises(slac_timing.buffer.ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert str(e.value) == "Could not reach edef system pv=IOC:IN20:EV01:EDEFNAME"


@pytest.mark.ioc_yaml("fail_pvnames_ioc.yaml")
def test_slot_name_timeout():
    import slac_timing.event_definition
    import slac_timing.buffer

    with pytest.raises(slac_timing.buffer.ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert str(e.value) == "Could not reach edef system pv=EDEF:SYS0:1:NAME"


@pytest.mark.ioc_yaml("fail_usernames_ioc.yaml")
def test_slot_username_timeout():
    import slac_timing.event_definition
    import slac_timing.buffer

    with pytest.raises(slac_timing.buffer.ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert str(e.value) == "Could not reach edef system pv=EDEF:SYS0:1:USERNAME"


@pytest.mark.ioc_yaml("fail_available_ioc.yaml")
def test_fail_available_timeout():
    import slac_timing.event_definition
    import slac_timing.buffer

    with pytest.raises(slac_timing.buffer.ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert str(e.value) == "Could not reach edef system pv=IOC:IN20:EV01:EDEFAVAIL"


@pytest.mark.ioc_yaml("no_reservations_ioc.yaml")
def test_no_reservations():
    import slac_timing.event_definition
    import slac_timing.buffer

    with pytest.raises(slac_timing.buffer.ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert (
        str(e.value)
        == "No event definitions available. pv=IOC:IN20:EV01:EDEFAVAIL, value=0"
    )


@pytest.mark.ioc_yaml("could_not_reserve_edef_ioc.yaml")
def test_yes_reservations_but_error():
    import slac_timing.event_definition
    import slac_timing.buffer

    with pytest.raises(slac_timing.buffer.ReservationError) as e:
        slac_timing.event_definition.EventDefinition(
            name="name", user="user", n_measurements=1, n_avg=1, beamcode=0
        )
    assert str(e.value) == (
        "Could not reserve an EDEF."
        + "\npv=EDEF:SYS0:1:NAME, value=nothing"
        + "\npv=EDEF:SYS0:2:NAME, value=nothing"
        + "\npv=EDEF:SYS0:3:NAME, value=nothing"
        + "\npv=EDEF:SYS0:4:NAME, value=nothing"
        + "\npv=EDEF:SYS0:5:NAME, value=nothing"
        + "\npv=EDEF:SYS0:6:NAME, value=nothing"
        + "\npv=EDEF:SYS0:7:NAME, value=nothing"
        + "\npv=EDEF:SYS0:8:NAME, value=nothing"
        + "\npv=EDEF:SYS0:9:NAME, value=nothing"
        + "\npv=EDEF:SYS0:10:NAME, value=nothing"
        + "\npv=EDEF:SYS0:11:NAME, value=nothing"
        + "\npv=IOC:IN20:EV01:EDEFAVAIL, value=1"
    )
