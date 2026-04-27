import importlib

import pytest


from ras_commander import RasComputeState


def test_ras_compute_state_is_public_export():
    assert RasComputeState.__name__ == "RasComputeState"


def test_ras_currency_module_not_retained_as_compatibility_alias():
    import ras_commander

    assert not hasattr(ras_commander, "RasCurrency")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ras_commander.RasCurrency")
