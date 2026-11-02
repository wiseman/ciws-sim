// Development-only export of the web game's synthesized sounds. Runs AudioController's own
// buffer builders (buildBuffers, buildVLSRoar, makeChirp and playPassBy's) with a fixed seed and
// writes the sounds' mid channels as 16-bit PCM. The alarms go out as WAVs for the voice path.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import * as THREE from '../Tests/Oracle/vendor/three.module.js';
import { mergeGeometries, mergeVertices } from '../Tests/Oracle/vendor/BufferGeometryUtils.js';
const html = fs.readFileSync(new URL('../../index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf("        // --- CONFIGURATION ---"), html.lastIndexOf('</script>')).replace(/\n        init\(\);/, '');
const noop = () => {};
const canvas = () => ({ width: 1, height: 1, getContext: () => new Proxy({}, { get: () => noop }) });
const element = () => ({style:{},classList:{add:noop,remove:noop,toggle:noop},addEventListener:noop,querySelector:()=>element(),getContext:()=>canvas().getContext()});
let seed = 41; const math = Object.create(Math); math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
const context = vm.createContext({THREE,mergeGeometries,mergeVertices,URLSearchParams,location:{search:""},Math:math,console,Date,performance:{now:()=>0},setTimeout:noop,clearTimeout:noop,requestAnimationFrame:noop,window:{addEventListener:noop},document:{getElementById:element,createElement:tag=>tag==='canvas'?canvas():element(),addEventListener:noop},localStorage:{getItem:()=>null,setItem:noop},navigator:{},fetch:()=>Promise.resolve({json:async()=>({})})});
vm.runInContext(source, context, { filename: 'index.html' });

const SAMPLE_RATE = 48000;
vm.runInContext(`
const sampleRate = ${SAMPLE_RATE};
const ctx = { sampleRate, createBuffer(channels, length, rate) {
  const data = Array.from({ length: channels }, () => new Float32Array(length));
  return { numberOfChannels: channels, length, sampleRate: rate, duration: length / rate, getChannelData: c => data[c] };
} };
const A = Object.create(AudioController);
Object.assign(A, { ctx, buffers: {}, isInit: true, isMuted: false, activeOneShots: 0, playAt() {} });
A.buildBuffers();
A.buildVLSRoar();
A.buffers.chirps = Array.from({ length: 6 }, () => A.makeChirp());
A.playPassBy('rotor');
A.playPassBy('bells');
const B = A.buffers;
globalThis.exportSounds = {
  shot: B.shot, big: B.big, thump: B.thump, hit: B.hit, pop: B.pop, splash: B.splash,
  slap: B.slap, vlsRoar: B.vlsRoar, chirp: B.chirps, rotor: [B.rotor], bells: [B.bells]
};
globalThis.exportAlarms = { 'general-alarm': B.alarm, 'launch-alarm': B.launchAlarm };
`, context);

const check = process.argv.includes('--check');
const write = (url, bytes) => {
  if (check) {
    if (!fs.existsSync(url) || !fs.readFileSync(url).equals(Buffer.from(bytes))) throw new Error(`Stale audio asset: ${url.pathname}`);
  } else fs.writeFileSync(url, bytes);
};
const pcm = samples => {
  const out = Buffer.alloc(samples.length * 2);
  samples.forEach((x, i) => out.writeInt16LE(Math.round(Math.max(-1, Math.min(1, x)) * 32767), i * 2));
  return out;
};
const wav = samples => {
  const data = pcm(samples), header = Buffer.alloc(44);
  header.write('RIFF', 0); header.writeUInt32LE(36 + data.length, 4); header.write('WAVE', 8);
  header.write('fmt ', 12); header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22);
  header.writeUInt32LE(SAMPLE_RATE, 24); header.writeUInt32LE(SAMPLE_RATE * 2, 28); header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34); header.write('data', 36); header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
};

// Mid channel only: RealityKit places each sound as a mono point source.
const output = new URL('../Resources/Sounds/', import.meta.url);
fs.mkdirSync(output, { recursive: true });
const chunks = [], sounds = {};
let frames = 0;
for (const [name, variants] of Object.entries(context.exportSounds)) {
  sounds[name] = variants.map(buffer => {
    const mid = buffer.getChannelData(0), range = [frames, mid.length];
    chunks.push(pcm(mid));
    frames += mid.length;
    return range;
  });
}
const index = { format: 1, sourceSHA256: crypto.createHash('sha256').update(html).digest('hex'), sampleRate: SAMPLE_RATE, sounds };
write(new URL('web-sounds.json', output), JSON.stringify(index, null, 1) + '\n');
write(new URL('web-sounds.bin', output), Buffer.concat(chunks));
for (const [name, buffer] of Object.entries(context.exportAlarms)) {
  write(new URL(`${name}.wav`, output), wav(buffer.getChannelData(0)));
}
console.log(`${Object.keys(sounds).length} sounds, ${(frames / SAMPLE_RATE).toFixed(1)} s, ${(frames * 2 / 1e6).toFixed(1)} MB`);
