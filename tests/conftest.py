"""Fixtures. Home Assistant tests are skipped when HA isn't installed."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "yakka"
HA_TESTS = [
    "test_automation.py",
    "test_config_flow.py",
    "test_init.py",
    "test_target_automation.py",
]

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:
    collect_ignore = HA_TESTS
else:
    pytest_plugins = ["pytest_homeassistant_custom_component"]

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Let Home Assistant load custom_components/yakka."""
        yield


def load_standalone(name: str) -> ModuleType:
    """Import one of the component's HA-free modules without its package."""
    key = f"yakka_standalone_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, COMPONENT / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module
