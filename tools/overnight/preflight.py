"""Local probes. T3 capabilities are attested separately by the coordinator."""
from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys

import psutil

START_MIN_FREE_BYTES = 8 * 1024 ** 3
STOP_MIN_FREE_BYTES = 6 * 1024 ** 3
RSS_STOP_BYTES = 4 * 1024 ** 3
ATTEMPT_DIR_MAX_BYTES = 100 * 1024 ** 2
GLOBAL_ALLOWANCE_BYTES = 2 * 1024 ** 3
REQUIRED_MODULES = ("numpy", "scipy", "pyzx", "z3-solver", "qiskit",
                    "stim", "ldpc", "bposd", "pulp", "psutil")


class BlockedError(RuntimeError):
    pass


class HostProbes:
    def power_source(self):
        result = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                text=True, timeout=2, check=True)
        return "ac" if "AC Power" in result.stdout else "battery"

    def disk_free_bytes(self, path):
        return shutil.disk_usage(path).free

    def mem_available_bytes(self):
        return psutil.virtual_memory().available

    def module_versions(self):
        return {name: importlib.metadata.version(name) for name in REQUIRED_MODULES}

    def tool_present(self, name):
        return shutil.which(name) is not None

    def python_version(self):
        return tuple(sys.version_info[:3])


def check_power(probes):
    if probes.power_source() != "ac":
        raise BlockedError("AC power required")
    return "ac"


def check_disk(path, probes, minimum=START_MIN_FREE_BYTES):
    free = probes.disk_free_bytes(path)
    if free < minimum:
        raise BlockedError("disk free below %d bytes" % minimum)
    return free


def check_memory(probes):
    available = probes.mem_available_bytes()
    if available < RSS_STOP_BYTES:
        raise BlockedError("available memory below 4 GiB")
    return available


def check_toolchain(probes):
    missing = [name for name in ("cc", "make", "caffeinate")
               if not probes.tool_present(name)]
    if missing:
        raise BlockedError("missing tools: " + ", ".join(missing))
    if probes.python_version() < (3, 12):
        raise BlockedError("Python 3.12 or newer required")
    return probes.module_versions()


def preflight(root, probes=None):
    probes = probes or HostProbes()
    return {"power": check_power(probes), "disk_free": check_disk(root, probes),
            "mem_available": check_memory(probes), "modules": check_toolchain(probes)}
