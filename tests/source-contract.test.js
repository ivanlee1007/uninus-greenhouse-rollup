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

test('card uses inline containment so responsive rows keep intrinsic height', async () => {
  const text = await source('src/card.js');
  assert.match(text, /container-type:inline-size/);
  assert.doesNotMatch(text, /container-type:size/);
  assert.doesNotMatch(text, /cqh/);
});

test('editor exposes adaptive items-per-row, subtitle, per-face entity and color controls', async () => {
  const text = await source('src/editor.js');
  for (const marker of ['subtitle_attribute', 'items_per_row', '每列捲揚數量', 'status_moving_color', 'background_color', 'cover_entity', '標準 Cover Entity', 'motion_entity', 'max_entity', 'accent_color', 'ha-entity-picker', 'config-changed']) {
    assert.match(text, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(text, /force_1x4/);
});

test('integration faces expose explicit open stop close controls through cover services', async () => {
  const text = await source('src/card.js');
  for (const marker of ['data-action="open"', 'data-action="stop"', 'data-action="close"', "callService('cover'", 'coverServiceForAction', 'commandLabel', 'confidenceLabel']) {
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
  assert.match(text, /customElements\.define/);
  assert.match(text, /uninus-greenhouse-rollup-card-editor/);
  assert.match(text, /window\.customCards/);
  assert.match(text, /UNiNUS Greenhouse Rollup Card/);
  assert.match(text, /preview:\s*true/);
});

test('card and editor use native Web Components to avoid HA Lit patch corruption', async () => {
  const card = await source('src/card.js');
  const editor = await source('src/editor.js');
  assert.doesNotMatch(card, /from ['"]lit['"]/);
  assert.doesNotMatch(editor, /from ['"]lit['"]/);
  assert.match(card, /extends HTMLElement/);
  assert.match(editor, /extends HTMLElement/);
  assert.match(card, /rollup-card/);
});
