"""Host checks fail closed without environment bypasses."""
import pytest

from tools.overnight import preflight as pre
from tests.fixture_support import FixtureProbes


def test_battery_cannot_be_overridden_by_environment(monkeypatch):
    probes = FixtureProbes()
    probes.power_source = lambda: "battery"
    monkeypatch.setenv("OVERNIGHT_POWER_SOURCE", "ac")
    with pytest.raises(pre.BlockedError, match="AC"):
        pre.check_power(probes)


def test_disk_and_memory_gate():
    probes = FixtureProbes()
    probes.disk_free_bytes = lambda _: 7 * 1024 ** 3
    with pytest.raises(pre.BlockedError, match="disk"):
        pre.check_disk("/", probes)
    assert pre.check_disk("/", probes, pre.STOP_MIN_FREE_BYTES) == 7 * 1024 ** 3
    probes.mem_available_bytes = lambda: 1024
    with pytest.raises(pre.BlockedError, match="memory"):
        pre.check_memory(probes)


def test_toolchain_and_module_failure():
    probes = FixtureProbes()
    probes.tool_present = lambda _: False
    with pytest.raises(pre.BlockedError, match="missing tools"):
        pre.check_toolchain(probes)
    probes.tool_present = lambda _: True
    def missing():
        raise ImportError("missing module")
    probes.module_versions = missing
    with pytest.raises(ImportError, match="missing module"):
        pre.check_toolchain(probes)
