// Development-only export. The app bundles geometry/PNG data, never this JavaScript.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import * as THREE from '../Tests/Oracle/vendor/three.module.js';
import { mergeGeometries, mergeVertices } from '../Tests/Oracle/vendor/BufferGeometryUtils.js';
const require = createRequire(import.meta.url);
const { createCanvas } = require(process.env.CIWS_CANVAS_MODULE || '@napi-rs/canvas');
const html = fs.readFileSync(new URL('../../index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf("        // --- CONFIGURATION ---"), html.lastIndexOf('</script>')).replace(/\n        init\(\);/, '');
const noop = () => {};
const element = () => ({style:{},classList:{add:noop,remove:noop,toggle:noop},addEventListener:noop,querySelector:()=>element(),getContext:()=>createCanvas(512,512).getContext('2d')});
let seed=29; const math=Object.create(Math); math.random=()=>{ seed=(Math.imul(seed,1664525)+1013904223)>>>0; return seed/4294967296; };
const context = vm.createContext({THREE,mergeGeometries,mergeVertices,URLSearchParams,location:{search:""},Math:math,console,Date,performance:{now:()=>0},setTimeout:noop,clearTimeout:noop,requestAnimationFrame:noop,window:{addEventListener:noop},document:{getElementById:element,createElement:tag=>tag==='canvas'?createCanvas(1,1):element(),addEventListener:noop},localStorage:{getItem:()=>null,setItem:noop},navigator:{},fetch:()=>Promise.resolve({json:async()=>({})})});
vm.runInContext(source, context, {filename:'index.html'});
vm.runInContext(`
scene=new THREE.Scene(); renderer={capabilities:{getMaxAnisotropy:()=>1}};
createShip(); createPhalanxCIWS();
shipRadar.name='ship-radar'; killMarks.radome.name='radome'; turretYaw.name='mount-yaw'; turretPitch.name='mount-pitch';
shipVLS.cells.forEach((c,i)=>c.lid.name='hatch-'+i);
const assets={ship:scene.getObjectByName('ship'), mount:ciwsGroup,
 drone:addOutlines(buildDeltaWingDrone()), mortar:createMortarShell(), ascm:createAntiShipMissile(), vlsMissile:createVLSMissile(),
 witch:addOutlines(buildWitch()), pumpkin:createJackOLantern(),
 killMark:new THREE.Mesh(killMarks.marks.geometry,killMarks.marks.material), killStar:new THREE.Mesh(killMarks.stars.geometry,killMarks.stars.material),
 puff:new THREE.Mesh(PUFF_GEO_HI,toonMat(0xffffff)), debris:makeDebris().mesh, pumpkinDebris:makePumpkinDebris().mesh,
 wake:new THREE.Mesh(WAKE_GEO,TRACER_MAT), tracer:new THREE.Mesh(TRACER_GEO,TRACER_MAT), spark:new THREE.Mesh(SPARK_GEO,TRACER_MAT), billboard:new THREE.Mesh(BILLBOARD_GEO,TRACER_MAT)};
for (const [name,build] of Object.entries({flyby:buildHelicopter,dolphins:buildDolphin,whale:buildWhale,sailboat:buildSailboat,bird:buildGull,duck:buildDuck,sleigh:buildSleigh})) {
 const o=build(); if(o.userData.wings)o.userData.wings.forEach((w,i)=>w.name='wing-'+i); if(o.userData.tail)o.userData.tail.name='tail'; assets[name]=addOutlines(o);
}
for (const key of Object.keys(FRIENDLY_NAMES)) {
 const f=buildFriendly(0,key,{x:0,z:0,heading:0}); f.mesh.position.set(0,0,0);
 f.vlsCells.forEach((c,i)=>c.lid.name='hatch-'+i); assets['friendly-'+key]=f.mesh;
 const w=FRIENDLY_FITS[f.fit].wreck(); w.traverse(o=>{if(o.name==='markings')o.material=f.markings;}); assets['wreck-'+key]=w;
}
scene=new THREE.Scene(); createClouds();createMountains();assets.environment=scene;
globalThis.exportAssets=assets;
`,context);

const output = new URL('../Resources/Visuals/', import.meta.url);
fs.mkdirSync(output,{recursive:true});
const write = (url, bytes) => {
 if (process.argv.includes('--check')) {
  if (!fs.existsSync(url) || !fs.readFileSync(url).equals(Buffer.from(bytes))) throw new Error(`Stale visual asset: ${url.pathname}`);
 } else fs.writeFileSync(url, bytes);
};
const geometries=[], materials=[], textures=[], geoIDs=new Map(),matIDs=new Map(),texIDs=new Map(),chunks=[];let byteLength=0;
const buffer = (array, integer=false) => { const a=integer?Uint32Array.from(array):Float32Array.from(array); const b=Buffer.from(a.buffer);const range=[byteLength,a.length];chunks.push(b);byteLength+=b.length;return range; };
function texture(t) {
 if(texIDs.has(t))return texIDs.get(t);
 const id=textures.length, name=`web-texture-${id}.png`;texIDs.set(t,id);
 write(new URL(name,output),t.image.toBuffer('image/png'));textures.push(name);return id;
}
function material(m, vertexColor) {
 const key=m.uuid+(vertexColor?vertexColor.join(','):'');if(matIDs.has(key))return matIDs.get(key);
 const id=materials.length;matIDs.set(key,id);
 const base=m.color?.clone()??new THREE.Color(0xffffff);if(vertexColor)base.multiply(new THREE.Color(...vertexColor));
 materials.push({color:base.toArray(),emissive:m.emissive?.toArray()??[0,0,0],toon:!!m.isMeshToonMaterial,outline:m===context.outlineMaterial,side:m.side,opacity:m.opacity,alphaTest:m.alphaTest,texture:m.map?.image?.toBuffer?texture(m.map):null,repeat:m.map?.repeat.toArray()??[1,1],offset:m.map?.offset.toArray()??[0,0],depthWrite:m.depthWrite});return id;
}
function geometry(g) {
 if(geoIDs.has(g))return geoIDs.get(g);const id=geometries.length;geoIDs.set(g,id);
 const a=g.attributes;geometries.push({positions:buffer(a.position.array),normals:a.normal?buffer(a.normal.array):null,uv:a.uv?buffer(a.uv.array):null,indices:buffer(g.index?.array??Array.from({length:a.position.count},(_,i)=>i),true)});return id;
}
function node(o) {
 const result={name:o.name,position:o.position.toArray(),rotation:o.quaternion.toArray(),scale:o.scale.toArray(),visible:o.visible,children:[]};
 if(o.isMesh && !o.material.isShaderMaterial) {
  result.geometry=geometry(o.geometry); const mats=Array.isArray(o.material)?o.material:[o.material];result.materials=mats.map(m=>material(m));
  const colors=o.geometry.attributes.color;
  if(colors && mats[0].vertexColors) {const idx=o.geometry.index?.array??Array.from({length:colors.count},(_,i)=>i); const ids=[];const local=new Map();for(let i=0;i<idx.length;i+=3){const k=idx[i];const mid=material(mats[0],[colors.getX(k),colors.getY(k),colors.getZ(k)]);if(!local.has(mid))local.set(mid,local.size);ids.push(local.get(mid));}result.materials=[...local.keys()];result.faceMaterials=buffer(ids,true);}
  else if(o.geometry.groups.length && mats.length>1){const ids=[];for(const group of o.geometry.groups)for(let i=0;i<group.count;i+=3)ids.push(group.materialIndex);result.faceMaterials=buffer(ids,true);}
 }
 if(o.userData.isOutline) {result.geometry=geometry(o.geometry);result.outline=true;}
 for(const child of o.children) { if(child.isLight || child.isInstancedMesh)continue;result.children.push(node(child)); }
 return result;
}
// Export a quiet initial pose; Swift animates the same named pivots.
const assets={};for(const [name,o] of Object.entries(context.exportAssets)){assets[name]=node(o);}
const data={format:1,sourceSHA256:crypto.createHash('sha256').update(html).digest('hex'),assets,geometries,materials,textures};
write(new URL('web-models.json',output),JSON.stringify(data));write(new URL('web-meshes.bin',output),Buffer.concat(chunks));
console.log(`${geometries.length} geometries, ${materials.length} materials, ${textures.length} textures, ${(byteLength/1e6).toFixed(1)} MB`);

write(new URL('web-white.png',output), (()=>{const c=createCanvas(1,1); const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,1,1);return c.toBuffer('image/png')})());
