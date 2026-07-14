import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), 'utf8');
}

test('card exposes Home Assistant custom-card lifecycle and responsive observer', async () => {
  const text = await source('src/card.js');
  for (const marker of ['getConfigElement', 'getStubConfig', 'getGridOptions', 'ResizeObserver', 'connectedCallback', 'disconnectedCallback']) {
    assert.match(text, new RegExp(marker));
  }
});

test('editor exposes global, subtitle, per-face entity and color controls', async () => {
  const text = await source('src/editor.js');
  for (const marker of ['subtitle_attribute', 'force_1x4', 'status_moving_color', 'background_color', 'motion_entity', 'max_entity', 'accent_color', 'ha-entity-picker', 'config-changed']) {
    assert.match(text, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('card respects reduced motion and uses namespaced effect classes', async () => {
  const text = await source('src/card.js');
  assert.match(text, /prefers-reduced-motion/);
  assert.match(text, /rollup-air/);
  assert.doesNotMatch(text, /class="air"/);
});

test('index registers card, editor and visual picker metadata', async () => {
  const text = await source('src/index.js');
  assert.match(text, /uninus-greenhouse-rollup-card-editor/);
  assert.match(text, /window\.customCards/);
  assert.match(text, /UNiNUS Greenhouse Rollup Card/);
});
