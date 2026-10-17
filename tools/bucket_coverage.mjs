// Counts each voice bucket's lines for every situation it covers (each ship, side and bearing its
// clip names template), against the clips sounds/callouts.json lists, and flags any with fewer
// than three. Usage: node tools/bucket_coverage.mjs
import { readFileSync } from 'node:fs';
const root = new URL('..', import.meta.url);
const html = readFileSync(new URL('index.html', root), 'utf8');
const have = new Set(JSON.parse(readFileSync(new URL('sounds/callouts.json', root), 'utf8')));
// The voice tables, from FRIENDLY_NAMES to the bearings, evaluated on their own
const from = html.indexOf('        const FRIENDLY_NAMES = '), to = html.indexOf('        const URGENT_CALLOUTS = ');
const { BUCKETS, FRIENDLY_NAMES, CALLED_BEARINGS } = new Function(`${html.slice(from, to)}; return { BUCKETS, FRIENDLY_NAMES, CALLED_BEARINGS };`)();
const VALUES = { ship: Object.keys(FRIENDLY_NAMES), bearing: CALLED_BEARINGS, side: ['port', 'starboard', 'stbd'] };
let short = 0;
for (const [name, B] of Object.entries(BUCKETS)) {
    const fields = [...new Set(B.clips.flatMap(c => [...c.matchAll(/\{(\w+)\}/g)].map(m => m[1])))];
    // Every combination of the fields' values; a situation counts if any of its templated clips exist
    // (sides are spelt 'stbd' in some buckets and 'starboard' in others)
    const fill = (clip, c) => clip.replace(/\{(\w+)\}/g, (_, f) => c[f]);
    let combos = [{}];
    for (const f of fields) combos = combos.flatMap(c => VALUES[f].map(v => ({ ...c, [f]: v })));
    if (fields.length) combos = combos.filter(c => B.clips.some(clip => clip.includes('{') && have.has(fill(clip, c))));
    const counts = combos.map(c => B.clips.filter(clip => have.has(fill(clip, c))).length);
    const min = Math.min(...counts);
    if (min < 3) short++;
    console.log(`${min < 3 ? 'SHORT' : 'ok   '} ${name.padEnd(18)} ${min === Math.max(...counts) ? min : `${min}-${Math.max(...counts)}`} lines${fields.length ? ` per ${fields.join('+')}` : ''}`);
}
console.log(short ? `${short} buckets have fewer than three lines` : 'every bucket has at least three lines');
