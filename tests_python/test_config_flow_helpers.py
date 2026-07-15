from types import SimpleNamespace
from unittest import TestCase, skipIf

try:
    from custom_components.uninus_greenhouse_rollup.config_flow import (
        _pair_unique_id,
        _switches_in_use,
    )
except (ModuleNotFoundError, ImportError) as error:
    if (
        isinstance(error, ModuleNotFoundError)
        and error.name
        and (error.name.startswith("homeassistant") or error.name == "voluptuous")
    ):
        _pair_unique_id = None
        _switches_in_use = None
    elif isinstance(error, ImportError):
        raise
    else:
        raise


@skipIf(_pair_unique_id is None, "Home Assistant test dependency not installed")
class ConfigFlowHelperTest(TestCase):
    def test_pair_identity_is_independent_of_direction_order(self):
        self.assertEqual(
            _pair_unique_id("switch.a", "switch.b"),
            _pair_unique_id("switch.b", "switch.a"),
        )

    def test_any_reused_source_switch_is_rejected(self):
        entries = [
            SimpleNamespace(
                entry_id="existing",
                data={"open_entity": "switch.a", "close_entity": "switch.b"},
                options={},
            )
        ]
        self.assertTrue(_switches_in_use(entries, "switch.c", "switch.a"))
        self.assertTrue(_switches_in_use(entries, "switch.b", "switch.a"))
        self.assertFalse(_switches_in_use(entries, "switch.c", "switch.d"))


if __name__ == "__main__":
    import unittest

    unittest.main()
