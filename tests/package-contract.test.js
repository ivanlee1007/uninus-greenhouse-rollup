import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);

test('HACS filename, package entry and runtime artifact agree', async () => {
  const [pkg, hacs] = await Promise.all([
    readFile(new URL('package.json', root), 'utf8').then(JSON.parse),
    readFile(new URL('hacs.json', root), 'utf8').then(JSON.parse),
  ]);
  assert.equal(hacs.filename, pkg.main);
  assert.equal(pkg.main, 'uninus-greenhouse-rollup-card.js');
});

test('README documents the visual editor and forced 1x4 mode', async () => {
  const readme = await readFile(new URL('README.md', root), 'utf8');
  assert.match(readme, /視覺化設定/);
  assert.match(readme, /1 × 4/);
  assert.match(readme, /ResizeObserver/);
});
