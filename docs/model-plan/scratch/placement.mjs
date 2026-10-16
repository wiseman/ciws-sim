// Friendly placement before vs after (the createFriendlies rules, our ship's bounds), sampled:
// distance of each friendly from the gun, nearest-neighbour spacing, bearing spread.
// Usage: node docs/model-plan/scratch/placement.mjs
const B = { halfWidth: 8.5, bow: -42, stern: 70 }, AREA = 100, HALF = 23, N = 10000;
const near = (p, m) => Math.abs(p.x) < B.halfWidth + m && p.z > B.bow - m && p.z < B.stern + m;
const rnd = () => (Math.random() * 2 - 1) * AREA;
const foot = (x, z, h) => [-1, -0.5, 0, 0.5, 1].map(k => ({ x: x - Math.sin(h) * k * HALF, z: z - Math.cos(h) * k * HALF }));
const close = (a, b) => a.some(p => b.some(q => Math.hypot(p.x - q.x, p.z - q.z) < 18));
function place(after) {
  const out = [], fps = [];
  for (let i = 0; i < 5; i++) {
    let x, z, f;
    do { x = rnd(); z = rnd(); const h = (Math.random() * 2 - 1) * 0.45; f = foot(x, z, h); }
    while (near({ x, z }, 15) || (after && (f.some(p => near(p, 8)) || fps.some(o => close(f, o)))));
    fps.push(f); out.push({ x, z });
  }
  return out;
}
for (const after of [false, true]) {
  let dist = [], nn = [], within60 = 0;
  for (let t = 0; t < N; t++) {
    const fs = place(after);
    for (const a of fs) {
      const d = Math.hypot(a.x, a.z); dist.push(d); if (d < 60) within60++;
      nn.push(Math.min(...fs.filter(b => b !== a).map(b => Math.hypot(a.x - b.x, a.z - b.z))));
    }
  }
  const med = a => a.sort((p, q) => p - q)[a.length >> 1], mean = a => a.reduce((s, v) => s + v, 0) / a.length;
  console.log(after ? 'after ' : 'before', `range from gun: mean ${mean(dist).toFixed(1)} median ${med(dist).toFixed(1)}, under 60: ${(100 * within60 / dist.length).toFixed(1)}%;`,
    `nearest other friendly: mean ${mean(nn).toFixed(1)} median ${med(nn).toFixed(1)}, under 25: ${(100 * nn.filter(v => v < 25).length / nn.length).toFixed(1)}%`);
}
