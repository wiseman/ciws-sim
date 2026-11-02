// Development-only oracle: executes functions extracted unchanged from index.html.
// No JavaScript is linked into the native application.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import * as THREE from './vendor/three.module.js';
const source=fs.readFileSync(new URL('../../../index.html',import.meta.url),'utf8');
const slice=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
function fn(name) {
 const start=source.indexOf(`function ${name}(`);if(start<0)throw Error(name);
 let p=source.indexOf('{',start),depth=1,i=p+1;
 for(;depth;i++){if(source[i]==='{')depth++;else if(source[i]==='}')depth--;}
 return source.slice(start,i);
}
let seed=17;const rng=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
const math=Object.create(Math);math.random=rng;
const ctx=vm.createContext({THREE,Math:math,console,performance:{now:()=>1000},Date, safeStorageSet:()=>true,controllerMode:'classic'});
vm.runInContext(`const BULLET_SPEED=8,GRAVITY=.02;\n${slice('const SIM_STEPS_PER_SECOND','// --- STATE ---')}`,ctx);
const names=['solveInterceptSteps','computeSightAngles','computeAimSolution','randomRadarTrackVector','updateRadarTrack','stepTraverseAxis','randomSigned','wrapAngle','sigmoid','ema','pushBounded','makeControllerInputs','makeControllerTargets','aimAngleBetween','isInReach','flyMortar','flyDrone','steerDrone','turnToward','orientDrone','segmentSphereEntry','steerSeaSkimmer'];
vm.runInContext(names.map(fn).join('\n')+`
const _mortarLook=new THREE.Vector3(),_tmpDir=new THREE.Vector3(),_ascmLook=new THREE.Vector3();
const _droneFrom=new THREE.Vector3(),_droneStep=new THREE.Vector3(),_droneTo=new THREE.Vector3(),_droneDir=new THREE.Vector3(),_droneAxis=new THREE.Vector3(),_droneUp=new THREE.Vector3(),_droneBasis=new THREE.Matrix4(),_yAxis=new THREE.Vector3(0,1,0),_segDir=new THREE.Vector3(),_segOff=new THREE.Vector3();
const pick=items=>items[Math.floor(Math.random()*items.length)],LOSS_HISTORY_LENGTH=120;
${slice('const NeuralController = {','NeuralController.reset();')}
`,ctx);
const v=a=>new THREE.Vector3(...a);
const aims=[];for(let i=0;i<160;i++){
 const target=[(rng()-.5)*2500,rng()*650,(rng()-.5)*2500],velocity=[(rng()-.5)*20,(rng()-.5)*12,(rng()-.5)*20],muzzle=[0,9,5.5],mortar=i%2===0;
 const result=ctx.computeAimSolution(v(target),v(velocity),mortar,v(muzzle)),sight=ctx.computeSightAngles(v(target),v(muzzle));
 aims.push({target,velocity,muzzle,mortar,result,inputs:ctx.makeControllerInputs(v(target).sub(v(muzzle)),v(velocity),mortar),labels:ctx.makeControllerTargets(result,sight)});
}
const traverse=[];for(let i=0;i<150;i++){
 const args=[(rng()-.5)*6.28,(rng()-.5)*6.28,(rng()-.5)*.16,rng()*6+.1,i%2===0];
 traverse.push({args,result:ctx.stepTraverseAxis(...args)});
}
const flights=[];
for(const kind of ['drone','mortar','ascm'])for(const steps of [0.4,1,2.7]){
 const m={mesh:new THREE.Object3D(),velocity:v(kind==='mortar'?[-2.5,2.8,.2]:[-1,0,0]),targetInfo:{position:v([0,6,0])},speed:2.81,exhaustPos:v([0,0,0])};
 m.mesh.position.set(kind==='drone'?600:kind==='ascm'?1150:900,kind==='mortar'?4:60,0);
 const cruise=1,gamma=.6,drop=54,radius=cruise/(Math.PI/240);
 if(kind==='drone')m.dive={phase:'cruise',cruise,gamma,pushoverRange:drop/Math.tan(gamma)+radius*Math.tan(gamma/2),fullLoad:cruise*.6*Math.sin(gamma),bank:0,right:v([0,0,0])};
 if(kind==='drone')ctx.orientDrone(m,m.velocity,0);
 if(kind==='ascm')ctx.steerSeaSkimmer(m);
 const initial={position:m.mesh.position.toArray(),velocity:m.velocity.toArray()};
 let frames=[];for(let i=0;i<1800;i++){
   let arrived=false;
   if(kind==='drone')arrived=ctx.flyDrone(m,steps);
   if(kind==='mortar')arrived=ctx.flyMortar(m,steps);
   if(kind==='ascm'){m.mesh.position.addScaledVector(m.velocity,steps);ctx.steerSeaSkimmer(m);}
   arrived ||= m.mesh.position.distanceTo(m.targetInfo.position)<5;
   if(i%37===0||arrived)frames.push({frame:i+1,position:m.mesh.position.toArray(),velocity:m.velocity.toArray(),arrived,phase:m.dive?.phase,bank:m.dive?.bank,engineLoad:m.engineLoad});
   if(arrived)break;
 }
 flights.push({kind,steps,initial,frames});
}
const tape=Array.from({length:500},rng);let ti=0;math.random=()=>tape[ti++];
const m={mesh:new THREE.Object3D(),velocity:v([-1.3,.4,.8]),radarTrack:{posError:v([0,0,0]),posTarget:v([0,0,0]),velError:v([0,0,0]),velTarget:v([0,0,0]),retuneIn:0}};m.mesh.position.set(400,50,-200);
const radar=[];for(let i=0;i<80;i++){ctx.updateRadarTrack(m,1.3);radar.push({position:m.trackedPosition.toArray(),velocity:m.trackedVelocity.toArray(),retune:m.radarTrack.retuneIn});}
math.random=rng;
const net=vm.runInContext('NeuralController',ctx);net.reset();
let k=0;for(const l of net.layers())for(const row of l)for(let i=0;i<row.length;i++)row[i]=Math.sin(++k*.71)*.17;
net.resetOptimizer();
const initialWeights=net.layers().map(l=>l.map(row=>[...row]));
const batch=aims.slice(0,8).map(a=>({inputs:a.inputs,targets:a.labels}));
const predictions=batch.map(s=>Array.from(net.predict(s.inputs))),losses=[];
for(let i=0;i<10;i++)losses.push(net.trainBatch(batch));
const neural={initialWeights,batch,predictions,losses,finalWeights:net.layers()};
const data={sourceSHA256:crypto.createHash('sha256').update(source).digest('hex'),aims,traverse,flights,tape,radar,neural};
const dest=new URL('../CIWSSimulationTests/Fixtures/reference.json',import.meta.url);fs.mkdirSync(new URL('.',dest),{recursive:true});
const output=JSON.stringify(data)+'\n';
if(process.argv.includes('--check')){if(fs.readFileSync(dest,'utf8')!==output)throw Error('Reference fixtures are stale');}
else fs.writeFileSync(dest,output);
console.log(`Reference: ${aims.length} aims, ${traverse.length} traverses, ${flights.length} flights, ${radar.length} radar frames, 10 Adam batches`);
// Voice scheduling oracle: original methods with only Web Audio's output mocked.
const voiceTape=Array.from({length:10000},rng);let vi=0;math.random=()=>voiceTape[vi++];
vm.runInContext(slice('const DC_CALLS =','// When the triggers ask')+`
const RADIO={level:1,duck:.5,gap:.6};
const VOICE={net:{...RADIO,line:'net',stale:3},'1mc':{...RADIO,line:'pa',stale:8},crew:{line:'crew',level:1,duck:.75,gap:.3,stale:3}};
const VOICE_REPEAT_WINDOW=300;
const rand=(a,b)=>a+Math.random()*(b-a);
`,ctx);
function method(name){const start=source.indexOf(`${name}: function (`);if(start<0)throw Error(name);let p=source.indexOf(') {',start)+2,depth=1,i=p+1;for(;depth;i++){if(source[i]==='{')depth++;else if(source[i]==='}')depth--;};return source.slice(start,i);}
const duration=JSON.parse(fs.readFileSync(new URL('../../Sources/CIWSSimulation/Resources/voice-durations.json',import.meta.url)));
ctx.durations=duration;
vm.runInContext(`var voiceOutput=[]; var A={${['ready','reserve','release','fresh','play','say','queuePA','pumpPA','clearFrom'].map(method).join(',')},
 isInit:true,isMuted:false,ctx:{currentTime:0},busy:{net:0,pa:0,crew:0},hushUntil:{net:-Infinity,'1mc':-Infinity,crew:-Infinity},launchUntil:0,paQueue:[],spokenAt:{},
 debugState:{cic:{skipped:0,dropped:0,queued:0}},
 bucketState:Object.fromEntries(Object.entries(BUCKETS).map(([name,b])=>[name,{last:-Infinity,cursor:Math.floor(Math.random()*b.clips.length),voice:[-Infinity,-Infinity]}])),
 callouts:Object.fromEntries(Object.entries(durations).map(([name,duration])=>[name,{duration}])),
 cachedCallout(name){return this.callouts[name]??null},getCallout(name){return Promise.resolve(this.cachedCallout(name))},
 speak(name,buffer,when,channel){const end=when+buffer.duration;this.spokenAt[name]=when;this.busy[VOICE[channel].line]=Math.max(this.busy[VOICE[channel].line],end);voiceOutput.push({clip:name,start:when,end,channel});return end;}
};`,ctx);
const actions=[
 [1,'weapons-free',{}],[1.1,'kill',{}],[1.2,'raid-size',{}],[5,'vampire',{bearing:'090'}],[5.2,'reaction',{ship:'halvorsen',named:true}],
 [5.3,'rescue',{ship:'halvorsen'}],[5.4,'rescue',{ship:'whitcomb'}],[10,'we-hit',{side:-1,frame:240,missile:false}],
 [25,'kill',{}],[30,'kill',{}],[50,'kill',{}],[80,'vampire',{bearing:'000'}],[100,'dc',{side:1,frame:80,missile:true}],
 [120,'missile-launch',{}],[124,'birds-away',{}],[180,'pa-watch',{}],[180,'pa-chow',{}],[240,'chatter',{}],
 [300,'reaction',{ship:'cordell',named:false}],[300.3,'rescue-followup',{side:'port'}],[360,'weapons-free',{}],
 [400,'kill',{}],[420,'kill',{}],[450,'kill',{}],[720,'vampire',{bearing:'270'}]
];
for(const [at,name,params] of actions){ctx.A.ctx.currentTime=at;await ctx.A.play(name,params);for(let i=0;i<5;i++)await Promise.resolve();}
const voiceData={tape:voiceTape,actions:actions.map(([at,bucket,params])=>({at,bucket,params})),output:ctx.voiceOutput};
const voiceDest=new URL('../CIWSSimulationTests/Fixtures/voice-reference.json',import.meta.url),voiceText=JSON.stringify(voiceData)+'\n';
if(process.argv.includes('--check')){if(fs.readFileSync(voiceDest,'utf8')!==voiceText)throw Error('Voice reference fixtures stale');}else fs.writeFileSync(voiceDest,voiceText);
console.log(`Voice reference: ${actions.length} requests, ${ctx.voiceOutput.length} scheduled lines`);
const lotteryTape=Array.from({length:10000},rng);let li=0;math.random=()=>lotteryTape[li++];
const lotteries=[];for(let n=1;n<=6;n++)for(let k=0;k<30;k++)lotteries.push(Array.from({length:n},(_,i)=>i).sort(()=>math.random()-.5));
const lotteryDest=new URL('../CIWSSimulationTests/Fixtures/lottery-reference.json',import.meta.url),lotteryText=JSON.stringify({tape:lotteryTape,lotteries})+'\n';
if(process.argv.includes('--check')){if(fs.readFileSync(lotteryDest,'utf8')!==lotteryText)throw Error('Lottery reference fixtures stale');}else fs.writeFileSync(lotteryDest,lotteryText);
