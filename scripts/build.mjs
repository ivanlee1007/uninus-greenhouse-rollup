import { build } from 'esbuild';
import { readFile, writeFile } from 'node:fs/promises';

const pkg=JSON.parse(await readFile(new URL('../package.json',import.meta.url),'utf8'));
const outfile=new URL(`../${pkg.main}`,import.meta.url).pathname.replace(/^\/(.:)/,'$1');
await build({
  entryPoints:[new URL('../src/index.js',import.meta.url).pathname.replace(/^\/(.:)/,'$1')],
  bundle:true,
  minify:true,
  sourcemap:false,
  format:'esm',
  target:['es2022'],
  outfile,
  banner:{js:`/* UNiNUS Greenhouse Rollup Card v${pkg.version} | MIT */`},
  legalComments:'none',
});
const built=await readFile(outfile,'utf8');
await writeFile(outfile,`${built.split(/\r?\n/).map(line=>line.trimEnd()).join('\n').trimEnd()}\n`);
console.log(`Built ${pkg.main} v${pkg.version}`);
