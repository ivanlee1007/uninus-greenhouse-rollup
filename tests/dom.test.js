import test from 'node:test';
import assert from 'node:assert/strict';
import { parseHTML } from 'linkedom';

const { window } = parseHTML('<html><body></body></html>');
Object.assign(globalThis, {
  window,
  document: window.document,
  HTMLElement: window.HTMLElement,
  CustomEvent: window.CustomEvent,
  customElements: window.customElements,
  ResizeObserver: class {
    observe() {}
    disconnect() {}
  },
});

const { UninusGreenhouseRollupCard } = await import('../src/card.js');
customElements.define('uninus-greenhouse-rollup-test-card', UninusGreenhouseRollupCard);

function createCard(coverState, callService) {
  const calls = [];
  const card = window.document.createElement('uninus-greenhouse-rollup-test-card');
  window.document.body.append(card);
  card.setConfig({
    title: 'Runtime test',
    items_per_row: 2,
    faces: [{
      key: 'east',
      name: 'East',
      entity_mode: 'cover_entity',
      cover_entity: 'cover.east',
    }],
  });
  card.hass = {
    states: { 'cover.east': coverState },
    callService: callService ?? (async (...args) => calls.push(args)),
  };
  return { card, calls };
}

test('integration control click calls the exact cover service without opening More Info', async () => {
  const { card, calls } = createCard({
    state: 'opening',
    attributes: {
      current_position: 42,
      command_state: 'opening',
      position_confidence: 'estimated',
    },
  });
  let moreInfoCount = 0;
  card.addEventListener('hass-more-info', () => { moreInfoCount += 1; });

  const stop = card.shadowRoot.querySelector('.controls button[data-action="stop"]');
  assert.ok(stop);
  assert.equal(stop.disabled, false);
  stop.click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(calls, [['cover', 'stop_cover', { entity_id: 'cover.east' }]]);
  assert.equal(moreInfoCount, 0);
  assert.match(card.shadowRoot.innerHTML, /42%/);
  assert.match(card.shadowRoot.innerHTML, /開啟命令中/);
  card.remove();
});

test('integration controls are disabled when the cover is unavailable', () => {
  const { card } = createCard({ state: 'unavailable', attributes: {} });
  const controls = [...card.shadowRoot.querySelectorAll('.controls button')];

  assert.equal(controls.length, 3);
  assert.ok(controls.every((button) => button.disabled));
  assert.match(card.shadowRoot.innerHTML, /N\/A/);
  assert.match(card.shadowRoot.innerHTML, /不可用/);
  card.remove();
});

test('unknown position uses neutral geometry instead of looking fully closed', () => {
  const { card } = createCard({
    state: 'opening',
    attributes: { current_position: null, command_state: 'opening', position_confidence: 'unknown' },
  });
  const face = card.shadowRoot.querySelector('.face');

  assert.ok(face.classList.contains('unknown'));
  assert.match(face.getAttribute('style'), /--open:50%/);
  assert.match(card.shadowRoot.innerHTML, />—</);
  card.remove();
});

test('pending direction command survives a hass rerender and blocks duplicate directions', async () => {
  let finish;
  let callCount = 0;
  const pending = new Promise((resolve) => { finish = resolve; });
  const state = { state: 'open', attributes: { current_position: 50, command_state: 'idle' } };
  const { card } = createCard(state, async () => { callCount += 1; await pending; });

  card.shadowRoot.querySelector('[data-action="open"]').click();
  await Promise.resolve();
  card.hass = card.hass;
  const rerenderedOpen = card.shadowRoot.querySelector('[data-action="open"]');
  const rerenderedClose = card.shadowRoot.querySelector('[data-action="close"]');
  assert.equal(rerenderedOpen.disabled, true);
  assert.equal(rerenderedClose.disabled, true);
  rerenderedClose.click();
  assert.equal(callCount, 1);

  finish();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(card.shadowRoot.querySelector('[data-action="open"]').disabled, false);
  card.remove();
});

test('conflict disables directions but leaves stop available', () => {
  const { card } = createCard({
    state: 'open',
    attributes: { current_position: 50, command_state: 'conflict' },
  });

  assert.equal(card.shadowRoot.querySelector('[data-action="open"]').disabled, true);
  assert.equal(card.shadowRoot.querySelector('[data-action="close"]').disabled, true);
  assert.equal(card.shadowRoot.querySelector('[data-action="stop"]').disabled, false);
  card.remove();
});

test('service rejection is handled and emits a Home Assistant notification', async () => {
  const { card } = createCard(
    { state: 'open', attributes: { current_position: 50, command_state: 'idle' } },
    async () => { throw new Error('service failed'); },
  );
  let message = '';
  card.addEventListener('hass-notification', (event) => { message = event.detail.message; });

  card.shadowRoot.querySelector('[data-action="open"]').click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.match(message, /控制失敗/);
  assert.equal(card.shadowRoot.querySelector('[data-action="open"]').disabled, false);
  card.remove();
});
