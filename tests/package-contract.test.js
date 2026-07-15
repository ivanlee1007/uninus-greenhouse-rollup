import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);

test('integration manifest, package and bundled card versions agree', async () => {
  const [pkg, manifest, rootBundle, integrationBundle] = await Promise.all([
    readFile(new URL('package.json', root), 'utf8').then(JSON.parse),
    readFile(new URL('custom_components/uninus_greenhouse_rollup/manifest.json', root), 'utf8').then(JSON.parse),
    readFile(new URL('uninus-greenhouse-rollup-card.js', root)),
    readFile(new URL('custom_components/uninus_greenhouse_rollup/www/uninus-greenhouse-rollup-card.js', root)),
  ]);
  assert.equal(manifest.version, pkg.version);
  assert.equal(pkg.main, 'uninus-greenhouse-rollup-card.js');
  assert.deepEqual(integrationBundle, rootBundle);
  assert.match(rootBundle.toString('utf8').split('\n')[0], new RegExp(`v${pkg.version.replaceAll('.', '\\.')}`));
});

test('README documents the visual editor and exact items per row', async () => {
  const readme = await readFile(new URL('README.md', root), 'utf8');
  assert.match(readme, /視覺化設定/);
  assert.match(readme, /每列捲揚數量/);
  assert.match(readme, /最多 4/);
  assert.match(readme, /items_per_row/);
  assert.match(readme, /固定產生 1～4 欄/);
  assert.doesNotMatch(readme, /force_1x4/);
});
