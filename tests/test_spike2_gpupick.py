"""The emulator renders on the machine's fast GPU, and only chooses when there
is a choice (PAD-258).

WHAT THIS GUARDS. `gpupick.py` names the adapter watch.sh hands Mesa's d3d12 as
MESA_D3D12_DEFAULT_ADAPTER_NAME. Unset, Mesa takes DXCore's adapter 0, which on
a CPU-with-graphics + discrete-card machine was the integrated part (measured
1.096 ms/frame vs 0.026 on the RTX 5090). The rule under test is pick():
nothing with fewer than two hardware adapters, DXCore's own HighPerformance
order when it sorted, otherwise discrete before integrated then most memory.

The DXCore query itself needs a WSL2 VM and is proven on the rig; outside one,
main() must print nothing and succeed, so watch.sh leaves Mesa alone.
"""
import os
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import gpupick  # noqa: E402

GB = 1 << 30
IGPU = ("AMD Radeon(TM) Graphics", True, True, 2 * GB)
DGPU = ("NVIDIA GeForce RTX 5090", True, False, 32 * GB)
WARP = ("Microsoft Basic Render Driver", False, False, 0)


def test_one_hardware_adapter_is_not_a_choice():
    assert gpupick.pick([DGPU], sorted_=True) is None
    assert gpupick.pick([IGPU, WARP], sorted_=False) is None


def test_dxcore_order_wins_when_it_sorted():
    # Windows' HighPerformance order is trusted as given, even against the
    # heuristic, so a user's own Windows preference is what counts.
    assert gpupick.pick([IGPU, DGPU], sorted_=True) == IGPU[0]
    assert gpupick.pick([DGPU, IGPU], sorted_=True) == DGPU[0]


def test_fallback_prefers_discrete_then_memory():
    assert gpupick.pick([IGPU, DGPU], sorted_=False) == DGPU[0]
    small = ("Small dGPU", True, False, 4 * GB)
    assert gpupick.pick([IGPU, small, DGPU], sorted_=False) == DGPU[0]


def test_software_adapter_is_never_picked():
    assert gpupick.pick([WARP, IGPU, DGPU], sorted_=True) == IGPU[0]


def test_no_dxcore_prints_nothing(monkeypatch):
    if os.path.exists(gpupick.LIB):
        pytest.skip("inside WSL2: DXCore is present")
    out = subprocess.run([sys.executable, os.path.join(RIG, "gpupick.py")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout == ""
