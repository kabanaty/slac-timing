from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from slac_timing.buffer import Buffer, BufferSizeError


class ConcreteBuffer(Buffer):
    """Minimal concrete subclass for testing."""

    @property
    def pv_prefix(self) -> str:
        return "TEST:SYS0:1"

    def _create_pvs(self):
        return None

    def _reserve(self) -> int:
        return 1

    def release(self) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_complete(self) -> bool:
        return True

    @property
    def num_acquired(self) -> int:
        return self.n_measurements


@pytest.fixture
def buffer():
    with patch("pydantic.BaseModel.model_post_init"):
        buf = ConcreteBuffer.__new__(ConcreteBuffer)
        buf.__dict__.update(
            name="test", user="tester", number=1, n_measurements=5, n_avg=1, _pvs=None
        )
    return buf


class TestGetBackwardCompat:
    def test_returns_truncated_data(self, buffer):
        raw = np.arange(10, dtype=float)
        with patch("epics.caget", return_value=raw):
            result = buffer.get("SOME:PV")
        np.testing.assert_array_equal(result, np.arange(5, dtype=float))

    def test_returns_none_for_unreachable(self, buffer):
        with patch("epics.caget", return_value=None):
            assert buffer.get("SOME:PV") is None

    def test_short_data_returned_as_is_without_pad(self, buffer):
        raw = np.array([1.0, 2.0])
        with patch("epics.caget", return_value=raw):
            result = buffer.get("SOME:PV")
        np.testing.assert_array_equal(result, np.array([1.0, 2.0]))


class TestGetPad:
    def test_pads_short_data(self, buffer):
        raw = np.array([1.0, 2.0, 3.0])
        with patch("epics.caget", return_value=raw):
            result = buffer.get("SOME:PV", pad=True)
        assert len(result) == 5
        np.testing.assert_array_equal(result[:3], [1.0, 2.0, 3.0])
        assert np.isnan(result[3]) and np.isnan(result[4])

    def test_pads_none_to_full_array(self, buffer):
        with patch("epics.caget", return_value=None):
            result = buffer.get("SOME:PV", pad=True)
        assert len(result) == 5
        assert all(np.isnan(result))

    def test_custom_fill_value(self, buffer):
        with patch("epics.caget", return_value=None):
            result = buffer.get("SOME:PV", pad=True, fill_value=-1.0)
        np.testing.assert_array_equal(result, np.full(5, -1.0))

    def test_exact_size_data_unchanged(self, buffer):
        raw = np.arange(5, dtype=float)
        with patch("epics.caget", return_value=raw):
            result = buffer.get("SOME:PV", pad=True)
        np.testing.assert_array_equal(result, raw)

    def test_no_pad_when_n_measurements_zero(self, buffer):
        buffer.__dict__["n_measurements"] = 0
        raw = np.array([1.0, 2.0])
        with patch("epics.caget", return_value=raw):
            result = buffer.get("SOME:PV", pad=True)
        np.testing.assert_array_equal(result, raw)


class TestGetRetries:
    def test_retries_on_short_data_then_succeeds(self, buffer):
        short = np.array([1.0, 2.0])
        correct = np.arange(5, dtype=float)
        with patch("epics.caget", side_effect=[short, short, correct]):
            result = buffer.get("SOME:PV", retries=3, retry_delay=0)
        np.testing.assert_array_equal(result, correct)

    def test_raises_after_retries_exhausted(self, buffer):
        short = np.array([1.0, 2.0])
        with patch("epics.caget", return_value=short):
            with pytest.raises(BufferSizeError):
                buffer.get("SOME:PV", retries=2, retry_delay=0)

    def test_raises_when_none_persists(self, buffer):
        with patch("epics.caget", return_value=None):
            with pytest.raises(BufferSizeError):
                buffer.get("SOME:PV", retries=2, retry_delay=0)

    def test_no_retry_when_n_measurements_zero(self, buffer):
        buffer.__dict__["n_measurements"] = 0
        with patch("epics.caget", return_value=np.array([1.0])) as mock:
            buffer.get("SOME:PV", retries=3, retry_delay=0)
        assert mock.call_count == 1


class TestGetPadWithRetries:
    def test_pad_applied_when_no_retries(self, buffer):
        short = np.array([1.0, 2.0])
        with patch("epics.caget", return_value=short):
            result = buffer.get("SOME:PV", pad=True)
        assert len(result) == 5
        np.testing.assert_array_equal(result[:2], [1.0, 2.0])
        assert np.isnan(result[2])


class TestGetMany:
    def test_returns_dict(self, buffer):
        raw = [np.arange(5, dtype=float), None]
        with patch("epics.caget_many", return_value=raw):
            result = buffer.get_many(["PV:A", "PV:B"])
        np.testing.assert_array_equal(result["PV:A"], np.arange(5, dtype=float))
        assert result["PV:B"] is None

    def test_pads_all(self, buffer):
        raw = [np.array([1.0, 2.0]), None]
        with patch("epics.caget_many", return_value=raw):
            result = buffer.get_many(["PV:A", "PV:B"], pad=True)
        assert len(result["PV:A"]) == 5
        assert len(result["PV:B"]) == 5
        assert all(np.isnan(result["PV:B"]))

    def test_retries_batch(self, buffer):
        short_batch = [np.array([1.0]), np.arange(5, dtype=float)]
        ok_batch = [np.arange(5, dtype=float), np.arange(5, dtype=float)]
        with patch("epics.caget_many", side_effect=[short_batch, ok_batch]):
            result = buffer.get_many(["PV:A", "PV:B"], retries=2, retry_delay=0)
        np.testing.assert_array_equal(result["PV:A"], np.arange(5, dtype=float))


class TestClearCaCache:
    """Tests for _clear_ca_cache and its nested helpers."""

    def test_noop_when_no_context(self, buffer):
        with patch("slac_timing.buffer.epics.ca") as mock_ca, \
             patch("slac_timing.buffer._PVcache_", {}):
            mock_ca.current_context.return_value = None
            buffer._clear_ca_cache()
            mock_ca._cache.get.assert_not_called()

    def test_clears_matching_pv_objects(self, buffer):
        pv_obj = MagicMock()
        pv_obj._monref = ("cb", "mask", "evid")
        pv_cache = {
            ("SOME:PV:HST1", "native", "ctx"): pv_obj,
            ("OTHER:PV:HST2", "native", "ctx"): MagicMock(),
        }
        with patch("slac_timing.buffer.epics.ca") as mock_ca, \
             patch("slac_timing.buffer._PVcache_", pv_cache):
            mock_ca.current_context.return_value = "ctx"
            mock_ca._cache.get.return_value = None
            buffer._clear_ca_cache()

        assert ("SOME:PV:HST1", "native", "ctx") not in pv_cache
        assert ("OTHER:PV:HST2", "native", "ctx") in pv_cache
        pv_obj._clear_auto_monitor_subscription.assert_called_once()

    def test_clear_subscription_exception_propagates(self, buffer):
        pv_obj = MagicMock()
        pv_obj._monref = ("cb", "mask", "evid")
        pv_obj._clear_auto_monitor_subscription.side_effect = RuntimeError("dead channel")
        pv_cache = {("SOME:PV:HST1", "native", "ctx"): pv_obj}
        with patch("slac_timing.buffer.epics.ca") as mock_ca, \
             patch("slac_timing.buffer._PVcache_", pv_cache):
            mock_ca.current_context.return_value = "ctx"
            mock_ca._cache.get.return_value = None
            with pytest.raises(RuntimeError, match="dead channel"):
                buffer._clear_ca_cache()

    def test_clears_matching_context_cache_entries(self, buffer):
        entry = SimpleNamespace(chid=42)
        context_cache = {"SOME:PV:HST1": entry, "OTHER:PV:HST2": SimpleNamespace(chid=99)}
        with patch("slac_timing.buffer.epics.ca") as mock_ca, \
             patch("slac_timing.buffer._PVcache_", {}):
            mock_ca.current_context.return_value = "ctx"
            mock_ca._cache.get.return_value = context_cache
            buffer._clear_ca_cache()

        mock_ca.clear_channel.assert_called_once_with(42)
        assert "OTHER:PV:HST2" in context_cache

    def test_clear_channel_failure_propagates(self, buffer):
        entry = SimpleNamespace(chid=42)
        context_cache = {"SOME:PV:HST1": entry}
        with patch("slac_timing.buffer.epics.ca") as mock_ca, \
             patch("slac_timing.buffer._PVcache_", {}):
            mock_ca.current_context.return_value = "ctx"
            mock_ca._cache.get.return_value = context_cache
            mock_ca.clear_channel.side_effect = RuntimeError("stale chid")
            with pytest.raises(RuntimeError, match="stale chid"):
                buffer._clear_ca_cache()

    def test_skips_entry_without_chid(self, buffer):
        entry = SimpleNamespace(chid=None)
        context_cache = {"SOME:PV:HST1": entry}
        with patch("slac_timing.buffer.epics.ca") as mock_ca, \
             patch("slac_timing.buffer._PVcache_", {}):
            mock_ca.current_context.return_value = "ctx"
            mock_ca._cache.get.return_value = context_cache
            buffer._clear_ca_cache()

        mock_ca.clear_channel.assert_not_called()
        assert "SOME:PV:HST1" in context_cache
