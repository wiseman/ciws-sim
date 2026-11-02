// Development-only extraction of declarative tuning; the app contains no JavaScript runtime.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const source = readFileSync(resolve(root, 'index.html'), 'utf8');
const section = source.slice(source.indexOf('        const DC_CALLS ='), source.indexOf('        // When the triggers ask'));
const { BUCKETS, DC_CALLS } = Function(`${section}\nreturn {BUCKETS, DC_CALLS};`)();
const buckets = Object.entries(BUCKETS).map(([name, bucket]) => ({
    name, ...bucket, rank: bucket.rank ? name : undefined,
    cooldown: bucket.cooldown === Infinity ? undefined : bucket.cooldown,
    once: bucket.cooldown === Infinity
}));
const output = { sourceSHA256: createHash('sha256').update(source).digest('hex'), buckets, damageCalls: DC_CALLS };
const destination = resolve(root, 'visionos/Sources/CIWSSimulation/Resources/voice-buckets.json');
const serialized = JSON.stringify(output, null, 2) + '\n';
if (process.argv.includes('--check')) {
    if (readFileSync(destination, 'utf8') !== serialized) throw Error('Web reference changed; regenerate and check the Swift port.');
} else writeFileSync(destination, serialized);
