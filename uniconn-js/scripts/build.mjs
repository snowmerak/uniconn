import { execFileSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const requested = process.argv.slice(2);
const packages = requested.length ? requested : ['core', 'node', 'web'];
if (packages.some(name => !['core', 'node', 'web'].includes(name))) throw new Error('unknown workspace');
const selected = new Set(packages);
if (selected.has('node') || selected.has('web')) selected.add('core');
const compiler = path.join(root, 'node_modules/typescript/bin/tsc');
for (const name of ['core', 'node', 'web']) {
  if (!selected.has(name)) continue;
  const workspace = path.join(root, name);
  const output = path.resolve(workspace, 'dist');
  if (path.dirname(output) !== workspace || path.basename(output) !== 'dist') {
    throw new Error('unexpected build output path');
  }
  // A failed build must never leave removed tests executable from an older build.
  rmSync(output, { recursive: true, force: true });
  execFileSync(process.execPath, [compiler, '-p', workspace], { cwd: root, stdio: 'inherit' });
}
