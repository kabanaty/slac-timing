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
        inclusion_masks=["YY"],
    )
