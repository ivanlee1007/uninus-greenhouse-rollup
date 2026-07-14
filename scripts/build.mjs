import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';

const pkg=JSON.parse(await readFile(new URL('../package.json',import.meta.url),'utf8'));
await build({
  entryPoints:[new URL('../src/index.js',import.meta.url).pathname.replace(/^\/(.:)/,'$1')],
  bundle:true,
  minify:true,
  sourcemap:false,
  format:'esm',
  target:['es2022'],
  outfile:new URL(`../${pkg.main}`,import.meta.url).pathname.replace(/^\/(.:)/,'$1'),
  banner:{js:`/* UNiNUS Greenhouse Rollup Card v${pkg.version} | MIT */`},
  legalComments:'none',
});
console.log(`Built ${pkg.main} v${pkg.version}`);
