import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_CONFIG,
  FACE_KEYS,
  normalizeConfig,
  resolveFaceState,
  resolveSubtitle,
  selectLayout,
  updateFaceConfig,
  applyEditorChange,
  resolveThemeTokens,
  isValidColor,
  GRID_OPTIONS,
  coverServiceForAction,
} from '../src/model.js';

test('normalizeConfig creates four ordered faces and preserves explicit false', () => {
  const config = normalizeConfig({ animation: false, theme: 'light', items_per_row: 3, faces: [{ key: 'east', name: '東溫室' }] });
  assert.deepEqual(config.faces.map((face) => face.key), FACE_KEYS);
  assert.equal(config.faces[0].name, '東溫室');
  assert.equal(config.animation, false);
  assert.equal(config.theme, 'light');
  assert.equal(config.items_per_row, 3);
  assert.equal(config.faces[1].name, '南側');
});

test('normalizeConfig preserves legacy mode and explicitly selects integration mode', () => {
  const legacy = normalizeConfig({ faces: [{ key: 'east', entity: 'sensor.east' }] });
  assert.equal(legacy.faces[0].entity_mode, 'position_entity');

  const inferred = normalizeConfig({ faces: [{ key: 'east', cover_entity: 'cover.east' }] });
  assert.equal(inferred.faces[0].entity_mode, 'cover_entity');

  const explicitLegacy = normalizeConfig({ faces: [{ key: 'east', entity_mode: 'position_entity', cover_entity: 'cover.east', entity: 'sensor.east' }] });
  assert.equal(explicitLegacy.faces[0].entity_mode, 'position_entity');
  assert.equal(resolveFaceState(explicitLegacy.faces[0], {
    'cover.east': { state: 'opening', attributes: { current_position: 80 } },
    'sensor.east': { state: '10', attributes: {} },
  }).integration, false);
});

test('normalizeConfig clamps items per row and removes the legacy force flag', () => {
  assert.equal(normalizeConfig({ items_per_row: 0 }).items_per_row, 1);
  assert.equal(normalizeConfig({ items_per_row: 9 }).items_per_row, 4);
  assert.equal(normalizeConfig({ items_per_row: 2.8 }).items_per_row, 2);
  const migrated = normalizeConfig({ force_1x4: true });
  assert.equal(migrated.items_per_row, 4);
  assert.equal('force_1x4' in migrated, false);
});

test('normalizeConfig rejects invalid theme and colors', () => {
  const config = normalizeConfig({ theme: 'neon', status_moving_color: 'javascript:bad' });
  assert.equal(config.theme, DEFAULT_CONFIG.theme);
  assert.equal(config.status_moving_color, DEFAULT_CONFIG.status_moving_color);
});

test('resolveFaceState clamps position and resolves opening motion', () => {
  const states = {
    'sensor.east_position': { state: '150', attributes: {} },
    'binary_sensor.east_moving': { state: 'on', attributes: { direction: 'opening' } },
  };
  const result = resolveFaceState({ entity: 'sensor.east_position', motion_entity: 'binary_sensor.east_moving', max_value: 120 }, states);
  assert.equal(result.available, true);
  assert.equal(result.percent, 100);
  assert.equal(result.motion, 'opening');
  assert.equal(result.motionLabel, '開啟中');
  assert.equal(result.positionLabel, '全開');
});

test('resolveFaceState handles unavailable and idle states safely', () => {
  const result = resolveFaceState({ entity: 'sensor.missing', motion_entity: 'binary_sensor.missing', max_value: 120 }, {});
  assert.equal(result.available, false);
  assert.equal(result.percent, 0);
  assert.equal(result.motion, 'idle');
  assert.equal(result.positionLabel, '位置資料不可用');
});

test('resolveFaceState uses max entity when available and preserves zero', () => {
  const states = {
    'sensor.position': { state: '0', attributes: {} },
    'input_number.maximum': { state: '200', attributes: {} },
  };
  const result = resolveFaceState({ entity: 'sensor.position', max_entity: 'input_number.maximum', max_value: 120 }, states);
  assert.equal(result.value, 0);
  assert.equal(result.maximum, 200);
  assert.equal(result.positionLabel, '全閉');
});

test('resolveFaceState prefers integration cover position and command metadata', () => {
  const states = {
    'cover.east_rollup': {
      state: 'opening',
      attributes: {
        current_position: 42,
        position_confidence: 'estimated',
        command_state: 'opening',
        position_is_estimated: true,
      },
    },
    'sensor.legacy': { state: '99', attributes: {} },
  };
  const result = resolveFaceState({ cover_entity: 'cover.east_rollup', entity: 'sensor.legacy' }, states);
  assert.equal(result.integration, true);
  assert.equal(result.controlEntity, 'cover.east_rollup');
  assert.equal(result.percent, 42);
  assert.equal(result.motion, 'opening');
  assert.equal(result.confidence, 'estimated');
  assert.equal(result.confidenceLabel, '估算位置');
  assert.equal(result.commandLabel, '開啟命令中');
});

test('integration cover stops motion animation at endpoint while relay timer remains on', () => {
  const states = {
    'cover.east_rollup': {
      state: 'open',
      attributes: { current_position: 100, position_confidence: 'calibrated', command_state: 'opening_timer', position_is_estimated: true },
    },
  };
  const result = resolveFaceState({ cover_entity: 'cover.east_rollup' }, states);
  assert.equal(result.percent, 100);
  assert.equal(result.moving, false);
  assert.equal(result.motionLabel, '已全開');
  assert.equal(result.commandLabel, '開啟計時中');
  assert.equal(result.confidenceLabel, '端點已校正');
});

test('integration cover safely reports unknown and unavailable positions', () => {
  const unknown = resolveFaceState(
    { cover_entity: 'cover.unknown' },
    { 'cover.unknown': { state: 'opening', attributes: { command_state: 'opening', position_confidence: 'unknown', position_is_estimated: true } } },
  );
  assert.equal(unknown.available, true);
  assert.equal(unknown.positionKnown, false);
  assert.equal(unknown.positionLabel, '位置尚未校正');

  const unavailable = resolveFaceState(
    { cover_entity: 'cover.offline' },
    { 'cover.offline': { state: 'unavailable', attributes: {} } },
  );
  assert.equal(unavailable.available, false);
});

test('managed Cover with unknown position does not claim a closing endpoint', () => {
  const state = resolveFaceState({ cover_entity: 'cover.unknown' }, {
    'cover.unknown': {
      state: 'closing',
      attributes: {
        command_state: 'closing_timer',
        position_confidence: 'unknown',
        position_is_estimated: true,
      },
    },
  });

  assert.equal(state.positionKnown, false);
  assert.equal(state.motionLabel, '關閉中');
  assert.equal(state.positionLabel, '位置尚未校正');
});

test('managed Cover with unknown position does not claim an opening endpoint', () => {
  const state = resolveFaceState({ cover_entity: 'cover.unknown' }, {
    'cover.unknown': {
      state: 'opening',
      attributes: {
        command_state: 'opening_timer',
        position_confidence: 'unknown',
        position_is_estimated: true,
      },
    },
  });

  assert.equal(state.positionKnown, false);
  assert.equal(state.motionLabel, '開啟中');
  assert.equal(state.positionLabel, '位置尚未校正');
});

test('native MQTT cover uses reported position without estimator-specific metadata', () => {
  const state = resolveFaceState({ cover_entity: 'cover.native' }, {
    'cover.native': {
      state: 'opening',
      attributes: { current_position: 37, supported_features: 11 },
    },
  });

  assert.equal(state.integration, true);
  assert.equal(state.managedCover, false);
  assert.equal(state.positionLabel, '開啟 37%');
  assert.equal(state.confidenceLabel, '');
  assert.equal(state.commandLabel, '裝置回報');
  assert.deepEqual(state.supports, { open: true, close: true, stop: true });
});

test('native MQTT cover without position does not pretend open means 100 percent', () => {
  const state = resolveFaceState({ cover_entity: 'cover.native' }, {
    'cover.native': {
      state: 'open',
      attributes: { supported_features: 3 },
    },
  });

  assert.equal(state.positionKnown, false);
  assert.equal(state.percent, null);
  assert.equal(state.positionLabel, '已開啟・位置未提供');
  assert.deepEqual(state.supports, { open: true, close: true, stop: false });
});

test('native Cover custom attributes do not opt into the Integration estimator UI', () => {
  const state = resolveFaceState({ cover_entity: 'cover.native' }, {
    'cover.native': {
      state: 'open',
      attributes: {
        current_position: 42,
        command_state: 'opening',
        position_confidence: 'estimated',
        supported_features: 3,
      },
    },
  });

  assert.equal(state.managedCover, false);
  assert.equal(state.positionLabel, '開啟 42%');
  assert.equal(state.commandLabel, '裝置回報');
  assert.equal(state.confidenceLabel, '');
});

test('native Cover movement state remains authoritative at stale position endpoints', () => {
  const opening = resolveFaceState({ cover_entity: 'cover.native' }, {
    'cover.native': { state: 'opening', attributes: { current_position: 100, supported_features: 11 } },
  });
  const closing = resolveFaceState({ cover_entity: 'cover.native' }, {
    'cover.native': { state: 'closing', attributes: { current_position: 0, supported_features: 11 } },
  });

  assert.equal(opening.motion, 'opening');
  assert.equal(opening.moving, true);
  assert.equal(closing.motion, 'closing');
  assert.equal(closing.moving, true);
});

test('managed timed Cover suppresses endpoint motion but still respects supported features', () => {
  const opening = resolveFaceState({ cover_entity: 'cover.managed' }, {
    'cover.managed': {
      state: 'opening',
      attributes: {
        current_position: 100,
        command_state: 'opening_timer',
        position_confidence: 'calibrated',
        position_is_estimated: true,
        supported_features: 3,
      },
    },
  });
  const closing = resolveFaceState({ cover_entity: 'cover.managed' }, {
    'cover.managed': {
      state: 'closing',
      attributes: {
        current_position: 0,
        command_state: 'closing_timer',
        position_confidence: 'calibrated',
        position_is_estimated: true,
        supported_features: 3,
      },
    },
  });

  assert.equal(opening.motion, 'idle');
  assert.equal(closing.motion, 'idle');
  assert.deepEqual(opening.supports, { open: true, close: true, stop: false });
});

test('Cover capability bits are interpreted consistently', () => {
  const expected = new Map([
    [0, { open: false, close: false, stop: false }],
    [1, { open: true, close: false, stop: false }],
    [2, { open: false, close: true, stop: false }],
    [3, { open: true, close: true, stop: false }],
    [4, { open: false, close: false, stop: false }],
    [8, { open: false, close: false, stop: true }],
    [11, { open: true, close: true, stop: true }],
  ]);

  for (const [supported_features, supports] of expected) {
    const state = resolveFaceState({ cover_entity: 'cover.capability' }, {
      'cover.capability': { state: 'open', attributes: { supported_features } },
    });
    assert.deepEqual(state.supports, supports, `supported_features=${supported_features}`);
  }
});

test('explicit cover mode never falls back to legacy when the cover entity is missing', () => {
  const state = resolveFaceState({
    key: 'east',
    entity_mode: 'cover_entity',
    cover_entity: 'cover.missing',
    entity: 'sensor.legacy',
    max_value: 100,
  }, {
    'sensor.legacy': { state: '64', attributes: {} },
  });

  assert.equal(state.integration, true);
  assert.equal(state.available, false);
  assert.equal(state.positionKnown, false);
  assert.equal(state.controlEntity, 'cover.missing');
});

test('null integration position remains unknown instead of becoming closed', () => {
  const state = resolveFaceState({ cover_entity: 'cover.east' }, {
    'cover.east': {
      state: 'open',
      attributes: { current_position: null, position_confidence: 'unknown' },
    },
  });

  assert.equal(state.positionKnown, false);
  assert.equal(state.percent, null);
  assert.notEqual(state.positionLabel, '全閉');
});

test('coverServiceForAction maps only supported safe controls', () => {
  assert.equal(coverServiceForAction('open'), 'open_cover');
  assert.equal(coverServiceForAction('stop'), 'stop_cover');
  assert.equal(coverServiceForAction('close'), 'close_cover');
  assert.equal(coverServiceForAction('delete'), '');
});

test('resolveSubtitle prefers configured attribute and preserves numeric zero', () => {
  const states = { 'sensor.greenhouse': { state: 'ok', attributes: { note: 0 } } };
  assert.equal(resolveSubtitle({ subtitle: 'fallback', subtitle_entity: 'sensor.greenhouse', subtitle_attribute: 'note' }, states), '0');
  assert.equal(resolveSubtitle({ subtitle: 'fallback' }, states), 'fallback');
});

test('selectLayout uses the configured items per row at every card width', () => {
  for (const width of [0, 320, 520, 700, 920]) {
    assert.equal(selectLayout({ width, itemsPerRow: 4 }), 'columns-4');
    assert.equal(selectLayout({ width, itemsPerRow: 3 }), 'columns-3');
    assert.equal(selectLayout({ width, itemsPerRow: 2 }), 'columns-2');
    assert.equal(selectLayout({ width, itemsPerRow: 1 }), 'columns-1');
  }
});

test('selectLayout clamps invalid configured column counts', () => {
  assert.equal(selectLayout({ width: 320, itemsPerRow: 9 }), 'columns-4');
  assert.equal(selectLayout({ width: 920, itemsPerRow: -2 }), 'columns-1');
  assert.equal(selectLayout({ width: 520, itemsPerRow: 'invalid' }), 'columns-2');
});

test('grid options use intrinsic height so responsive rows are never clipped', () => {
  assert.equal(GRID_OPTIONS.columns, 'full');
  assert.equal(GRID_OPTIONS.min_columns, 6);
  assert.equal('rows' in GRID_OPTIONS, false);
  assert.equal('min_rows' in GRID_OPTIONS, false);
  assert.equal('max_rows' in GRID_OPTIONS, false);
});

test('updateFaceConfig only changes the requested face', () => {
  const config = normalizeConfig({});
  const next = updateFaceConfig(config, 'west', 'entity', 'sensor.west');
  assert.equal(next.faces.find((face) => face.key === 'west').entity, 'sensor.west');
  assert.equal(next.faces.find((face) => face.key === 'east').entity, '');
  assert.notEqual(next.faces, config.faces);
});

test('isValidColor accepts CSS color formats used by the editor', () => {
  assert.equal(isValidColor('#ffd54a'), true);
  assert.equal(isValidColor('rgb(10, 20, 30)'), true);
  assert.equal(isValidColor('hsl(43 96% 50%)'), true);
  assert.equal(isValidColor('red'), true);
  assert.equal(isValidColor('url(javascript:bad)'), false);
});

test('applyEditorChange preserves boolean false and color strings', () => {
  const config = normalizeConfig({ animation: true });
  const noAnimation = applyEditorChange(config, { property: 'animation', value: false, valueType: 'boolean' });
  const colored = applyEditorChange(noAnimation, { property: 'status_moving_color', value: '#12abef' });
  assert.equal(noAnimation.animation, false);
  assert.equal(colored.status_moving_color, '#12abef');
});

test('applyEditorChange updates a nested face without mutating siblings', () => {
  const config = normalizeConfig({});
  const next = applyEditorChange(config, { faceKey: 'north', property: 'name', value: '北側上層' });
  assert.equal(next.faces[3].name, '北側上層');
  assert.equal(next.faces[0].name, '東側');
});

test('resolveThemeTokens exposes distinct light and dark surfaces with custom background override', () => {
  const dark = resolveThemeTokens(normalizeConfig({ theme: 'dark' }));
  const light = resolveThemeTokens(normalizeConfig({ theme: 'light' }));
  const custom = resolveThemeTokens(normalizeConfig({ theme: 'light', background_color: '#abcdef' }));
  assert.notEqual(dark.background, light.background);
  assert.equal(custom.background, '#abcdef');
});
