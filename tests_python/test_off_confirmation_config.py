import json
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from custom_components.uninus_greenhouse_rollup.config_flow import _schema, RollupOptionsFlow
from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover
from custom_components.uninus_greenhouse_rollup import async_migrate_entry


class OffConfirmationConfigTest(IsolatedAsyncioTestCase):
    async def test_timeout_is_configurable_and_legacy_defaults_are_safe(self):
        defaults = {m.schema: m.default() for m in _schema().schema}
        self.assertEqual(defaults.get('off_confirmation_timeout'), 5)
        entry = SimpleNamespace(data={'open_travel_time': 10, 'close_travel_time': 10}, options={})
        flow = RollupOptionsFlow()
        flow.handler = 'entry'
        flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry))
        entry.entry_id = "entry"
        flow.hass.data = {"uninus_greenhouse_rollup": {"parameters": {"entry":
            SimpleNamespace(parameters={"open_travel_time": 10, "close_travel_time": 10,
                                       "reverse_dead_time": 0.2, "off_confirmation_timeout": 5})}}}
        result = await flow.async_step_init()
        fields = {m.schema: m.default() for m in result['data_schema'].schema}
        self.assertEqual(fields.get('off_confirmation_timeout'), 5)
        data = dict(open_entity='switch.o', close_entity='switch.c', open_travel_time=10,
                    close_travel_time=10, off_confirmation_timeout=1.2)
        cover = UninusGreenhouseRollupCover(SimpleNamespace(entry_id='id', title='Title'), data)
        self.assertEqual(cover._off_confirmation_timeout, 1.2)
        self.assertEqual(cover.unique_id, 'id')
        entry = SimpleNamespace(version=3, data=data, options={'off_confirmation_timeout': 2})
        update = Mock()
        self.assertTrue(await async_migrate_entry(SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update)), entry))
        self.assertEqual(entry.data['off_confirmation_timeout'], 1.2)
        self.assertEqual(entry.options['off_confirmation_timeout'], 2)
        root = Path(__file__).resolve().parents[1] / 'custom_components/uninus_greenhouse_rollup'
        for path in [root / 'strings.json', *root.glob('translations/*.json')]:
            document = json.loads(path.read_text(encoding='utf-8'))
            for step in ('legacy_switch_pair', 'reconfigure'):
                self.assertIn('off_confirmation_timeout', document['config']['step'][step]['data'])
            self.assertIn('off_confirmation_timeout', document['options']['step']['init']['data'])
