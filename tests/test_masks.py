import logging
from unittest.mock import patch

import pytest

import slac_timing.masks
from slac_timing.buffer import ReservationError
from slac_timing.factory import create_buffer
from slac_timing.masks import NoBeamError, bykik_inclusion_masks


@pytest.fixture
def bykik_rate():
    """Patch both BYKIK rate PVs to return the given enum string."""

    def _set(value):
        for pv in slac_timing.masks._RATE_PVS.values():
            patcher = patch.object(pv, "get", return_value=value)
            patcher.start()
            patchers.append(patcher)

    patchers = []
    yield _set
    for p in patchers:
        p.stop()


@pytest.mark.parametrize(
    "beampath, area, rate, expected",
    [
        ("CU_HXR", "LTUH", "30 Hz", (["pockcel_perm", "RATE_MPS_HXR_30HZ"], 30.0)),
        ("CU_HXR", "LTUH", "10 Hz", (["pockcel_perm", "RATE_MPS_HXR_10HZ"], 10.0)),
        ("CU_HXR", "LTUH", "1 Hz", (["pockcel_perm", "RATE_MPS_HXR_01HZ"], 1.0)),
        ("CU_HXR", "LTUH", "60 Hz", (["pockcel_perm", "RATE_MPS_HXR_60HZ"], 60.0)),
        ("CU_SXR", "LTUS", "30 Hz", (["pockcel_perm", "RATE_MPS_SXR_30HZ"], 30.0)),
        ("CU_SXR", "LTUS", "1 Hz", (["pockcel_perm", "RATE_MPS_SXR_01HZ"], 1.0)),
        ("CU_HXR", "LTUH", "120 Hz", (["pockcel_perm"], None)),
    ],
)
def test_rate_masks(bykik_rate, beampath, area, rate, expected):
    bykik_rate(rate)
    assert bykik_inclusion_masks(beampath, area) == expected


@pytest.mark.parametrize(
    "beampath, area",
    [
        ("CU_HXR", "LI28"),
        ("CU_HXR", "UNDH"),
        ("CU_HXR", "LTUS"),
        ("CU_SXR", "LTUH"),
        ("CU_HXR", None),
    ],
)
def test_no_rate_bit_outside_ltu(beampath, area):
    with patch.object(slac_timing.masks.LazyPV, "get") as get:
        assert bykik_inclusion_masks(beampath, area) == (["pockcel_perm"], None)
    get.assert_not_called()


def test_zero_hz_raises(bykik_rate):
    bykik_rate("0 Hz")
    with pytest.raises(NoBeamError, match="IOC:BSY0:MP01:BYKIK_RATE"):
        bykik_inclusion_masks("CU_HXR", "LTUH")


def test_no_beam_is_reservation_error():
    assert issubclass(NoBeamError, ReservationError)


@pytest.mark.parametrize("rate", ["Invalid", "Unknown", "DEPRECATED"])
def test_unmapped_rate_warns(bykik_rate, caplog, rate):
    bykik_rate(rate)
    with caplog.at_level(logging.WARNING, logger="slac_timing.masks"):
        assert bykik_inclusion_masks("CU_SXR", "LTUS") == (["pockcel_perm"], None)
    assert "IOC:BSY0:MP01:BYKIKS_RATE" in caplog.text
    assert repr(rate) in caplog.text


def test_unreadable_rate_raises(bykik_rate):
    bykik_rate(None)
    with pytest.raises(ReservationError, match="Could not read BYKIK rate"):
        bykik_inclusion_masks("CU_HXR", "LTUH")


@patch("slac_timing.factory.EventDefinition")
def test_create_buffer_passes_masks(edef, bykik_rate):
    edef.BEAMCODE_MAP = {"CU_HXR": 1, "CU_SXR": 2}
    bykik_rate("30 Hz")
    create_buffer("CU_HXR", n_measurements=10, user="u", area="LTUH")
    kwargs = edef.call_args.kwargs
    assert kwargs["beamcode"] == 1
    assert kwargs["inclusion_masks"] == ["pockcel_perm", "RATE_MPS_HXR_30HZ"]
    assert kwargs["rate_limit_hz"] == 30.0


@patch("slac_timing.factory.EventDefinition")
def test_create_buffer_without_area(edef):
    edef.BEAMCODE_MAP = {"CU_HXR": 1, "CU_SXR": 2}
    create_buffer("CU_SXR", n_measurements=10, user="u")
    kwargs = edef.call_args.kwargs
    assert kwargs["beamcode"] == 2
    assert kwargs["inclusion_masks"] == ["pockcel_perm"]
    assert kwargs["rate_limit_hz"] is None
