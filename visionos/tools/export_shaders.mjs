// Native MaterialX graphs translating the web renderer's cel ramp, fog, sky and ocean.
import fs from 'node:fs';
import * as THREE from '../Tests/Oracle/vendor/three.module.js';
const linear=hex=>new THREE.Color(hex).toArray();
class Graph {
 constructor(name){this.name=name;this.nodes=[];this.params=[];this.paramNames=new Set();this.i=0;}
 val(type,value){return {type,value};}
 param(name,type,value){if(!this.paramNames.has(name)){this.params.push(`${type} inputs:${name} = ${this.literal(type,value)}`);this.paramNames.add(name);}return {type,path:`/Shaders/${this.name}.inputs:${name}`};}
 literal(type,v){return typeof v==='string'?(type==='asset'?`@${v}@`:JSON.stringify(v)):Array.isArray(v)?`(${v.join(',')})`:String(v);}
 node(id,type,inputs={}){const name=`n${this.i++}`;this.nodes.push(`def Shader "${name}" {\n uniform token info:id = "${id}"\n${Object.entries(inputs).map(([key,v])=>v.path?` ${v.type} inputs:${key}.connect = <${v.path}>`:` ${v.type} inputs:${key} = ${this.literal(v.type,v.value)}`).join('\n')}\n ${type} outputs:out\n}`);return {type,path:`/Shaders/${this.name}/${name}.outputs:out`};}
 op(op,a,b){return this.node(`ND_${op}_${a.type==='float'?'float':a.type==='float2'?'vector2':a.type==='float3'?'vector3':a.type}${b&&b.type!==a.type?'FA':''}`,a.type,{in1:a,...(b?{in2:b}:{})});}
 mul(a,b){return this.op('multiply',a,b)} add(a,b){return this.op('add',a,b)} sub(a,b){return this.op('subtract',a,b)}
 unary(op,a){if(op==='fract')return this.sub(a,this.unary('floor',a));return this.node(`ND_${op}_${a.type==='float2'?'vector2':a.type==='float3'?'vector3':a.type}`,op==='magnitude'?'float':a.type,{in:a});}
 extract(a,index){return this.node(`ND_extract_${a.type==='float2'?'vector2':a.type==='float3'?'vector3':a.type}`, 'float',{in:a,index:this.val('int',index)});}
 mix(a,b,k){return this.node(`ND_mix_${a.type==='float2'?'vector2':a.type==='float3'?'vector3':a.type}`,a.type,{bg:a,fg:b,mix:k});}
 smooth(x,a,b){return this.node('ND_smoothstep_float','float',{in:x,low:this.val('float',a),high:this.val('float',b)});}
 step(edge,x){return this.node('ND_ifgreatereq_float','float',{value1:x,value2:edge,in1:this.val('float',1),in2:this.val('float',0)});}
 position(){return this.node('ND_position_vector3','float3',{space:this.val('string','world')});}
 distance(){if(this.cachedDistance)return this.cachedDistance;const camera=this.node('ND_realitykit_cameraposition_vector3','float3');return this.cachedDistance=this.mul(this.unary('magnitude',this.sub(this.position(),camera)),this.param('distanceScale','float',1));}
 fog(color){return this.mix(color,this.val('color3f',linear(0xdcebf2)),this.smooth(this.distance(),150,1600));}
 surface(color,opacity=this.val('float',1),geometry=null){const s=this.node('ND_realitykit_unlit_surfaceshader','token',{color,opacity,opacityThreshold:this.val('float',0.01),applyPostProcessToneMap:this.val('bool',false)});return `def Material "${this.name}" {\n${this.params.join('\n')}\n token outputs:mtlx:surface.connect = <${s.path}>\n${geometry?`token outputs:realitykit:vertex.connect = <${geometry.path}>`:''}\n${this.nodes.join('\n')}\n}`;}
}
// Map USD types to MaterialX nodedef suffixes.
const oldNode=Graph.prototype.node;Graph.prototype.node=function(id,...args){return oldNode.call(this,id.replaceAll('color3f','color3').replaceAll('color4f','color4'),...args)};
const all=[];
for(const toon of [true,false]) {
 const g=new Graph(toon?'Toon':'Basic'),f=x=>g.val('float',x);
 const base=g.param('baseColor','color3f',[1,1,1]);
 const uv=g.node('ND_texcoord_vector2','float2',{index:g.val('int',0)});
 const mapped=g.add(g.mul(uv,g.param('uvRepeat','float2',[1,1])),g.param('uvOffset','float2',[0,0]));
 const tex=g.node('ND_image_color4','color4f',{file:g.param('image','asset','web-white.png'),texcoord:mapped});
 const rgb=g.node('ND_convert_color4_color3','color3f',{in:tex});
 let color=g.mul(base,rgb);
 if(toon){
  const normal=g.node('ND_normal_vector3','float3',{space:g.val('string','world')});
  const dot=g.node('ND_dotproduct_vector3','float',{in1:normal,in2:g.param('sunDirection','float3',[-.354, .798, .488])});
  const x=g.add(g.mul(dot,f(.5)),f(.5));
  const ramp=g.add(f(105/255),g.add(g.mul(g.step(f(1/3),x),f(80/255)),g.mul(g.step(f(2/3),x),f(70/255))));
  const hemi=g.mix(g.val('color3f',linear(0x6f8c99)),g.val('color3f',linear(0xe4f1fa)),g.add(g.mul(g.extract(normal,1),f(.5)),f(.5)));
  const irradiance=g.add(g.mul(g.val('color3f',linear(0xfff8ec).map(x=>x*2.6)),ramp),g.mul(hemi,f(1.5)));
  color=g.add(g.mul(color,g.mul(irradiance,f(1/Math.PI))),g.param('emissive','color3f',[0,0,0]));
 }
 all.push(g.surface(g.fog(color),g.mul(g.extract(tex,3),g.param('opacity','float',1))));
}
{
 const g=new Graph('Sky'),f=x=>g.val('float',x);
 const normal=g.unary('normalize',g.node('ND_position_vector3','float3',{space:g.val('string','object')}));
 const h=g.op('power',g.smooth(g.extract(normal,1),0,.5),f(.8));
 all.push(g.surface(g.mix(g.val('color3f',linear(0xdcebf2)),g.val('color3f',linear(0x9fcbe6)),h)));
}
{
 const g=new Graph('Ocean'),f=x=>g.val('float',x),v=(x,y)=>g.val('float2',[x,y]);
 const pos=g.node('ND_position_vector3','float3',{space:g.val('string','object')});
 const p=g.node('ND_combine2_vector2','float2',{in1:g.extract(pos,0),in2:g.extract(pos,2)});
 const t=g.param('time','float',0);
 function hash(a){let h=a;h=g.unary('fract',g.mul(h,v(123.34,456.21)));const dot=g.node('ND_dotproduct_vector2','float',{in1:h,in2:g.add(h,v(45.32,45.32))});h=g.add(h,g.node('ND_combine2_vector2','float2',{in1:dot,in2:dot}));return g.unary('fract',g.mul(g.extract(h,0),g.extract(h,1)));}
 function noise(a){const i=g.unary('floor',a),r=g.unary('fract',a),u=g.mul(g.mul(r,r),g.sub(v(3,3),g.mul(r,f(2))));return g.mix(g.mix(hash(i),hash(g.add(i,v(1,0))),g.extract(u,0)),g.mix(hash(g.add(i,v(0,1))),hash(g.add(i,v(1,1))),g.extract(u,0)),g.extract(u,1));}
 const swell=g.add(g.mul(noise(g.add(g.mul(p,f(.045)),g.mul(v(.05,.015),t))),f(.6)),g.mul(noise(g.sub(g.mul(p,f(.11)),g.mul(v(.03,.06),t))),f(.4)));
 let color=g.mix(g.val('color3f',linear(0x4f8ea6)),g.val('color3f',linear(0x76abbf)),g.step(f(.72),swell));
 const q=g.mul(p,v(.42,1.1));
 const caps=g.add(g.mul(noise(g.add(q,g.mul(v(.6,.2),t))),f(.55)),g.mul(noise(g.sub(g.mul(q,f(1.9)),g.mul(v(.3,.7),t))),f(.45)));
 const threshold=g.mix(f(.8),f(.97),g.smooth(g.distance(),60,600));
 color=g.mix(color,g.val('color3f',linear(0xd5e9f0)),g.step(threshold,caps));all.push(g.surface(g.fog(color)));
}
{
 const g=new Graph('Ink');
 const normal=g.node('ND_normal_vector3','float3',{space:g.val('string','object')});
 const offset=g.mul(normal,g.mul(g.distance(),g.param('thickness','float',.003)));
 const geometry=g.node('ND_realitykit_geometrymodifier_2_0_vertexshader','token',{modelPositionOffset:offset});
 all.push(g.surface(g.fog(g.val('color3f',linear(0x161b20))),g.val('float',1),geometry));
}
// Fireball heat bands and crisp smoke breakup, using the same palette and thresholds.
for(const outlined of [false,true]) {
 const g=new Graph(outlined?'PuffInk':'Puff'), f=x=>g.val('float',x), v=(...x)=>g.val('float3',x);
 const seed=g.param('seed','float',0), boil=g.param('boil','float',0), heat=g.param('heat','float',1), dissolve=g.param('dissolve','float',0);
 const position=g.node('ND_position_vector3','float3',{space:g.val('string','object')});
 const dir=g.unary('normalize',position);
 const noise=p=>g.node('ND_noise3d_float','float',{position:p});
 const seed3=g.node('ND_combine3_vector3','float3',{in1:seed,in2:seed,in3:seed});
 const drift=g.node('ND_combine3_vector3','float3',{in1:f(0),in2:boil,in3:f(0)});
 const n=noise(g.add(g.mul(dir,f(1.7)),g.add(g.mul(seed3,v(7.13,3.71,5.29)),drift)));
 const n2=noise(g.add(g.mul(dir,f(3.9)),g.add(g.mul(seed3,v(1.9,8.3,0)),g.mul(g.node('ND_combine3_vector3','float3',{in1:boil,in2:boil,in3:boil}),v(-.6,0,.4)))));
 let offset=g.sub(g.mul(dir,g.add(f(1),g.mul(g.add(g.mul(n,f(.7)),g.mul(n2,f(.3))),f(.32)))),position);
 const normal=g.node('ND_normal_vector3','float3',{space:g.val('string','world')});
 const sun=g.param('sunDirection','float3',[-.354,.798,.488]);
 const light=g.node('ND_dotproduct_vector3','float',{in1:normal,in2:sun});
 const grain=noise(g.add(g.mul(dir,f(2.6)),g.mul(seed3,f(13.7))));
 const opacity=g.step(dissolve,g.add(g.mul(grain,f(.5)),f(.5)));
 let color;
 if(outlined){
  color=g.mix(g.val('color3f',linear(0x1a1817)),g.val('color3f',linear(0x6e1a0b)),g.step(f(.45),heat));
  offset=g.add(offset,g.mul(dir,g.mul(g.distance(),g.param('thickness','float',.003))));
 }else{
  const view=g.unary('normalize',g.sub(g.node('ND_realitykit_cameraposition_vector3','float3'),g.position()));
  const facing=g.node('ND_clamp_float','float',{in:g.node('ND_dotproduct_vector3','float',{in1:normal,in2:view}),low:f(0),high:f(1)});
  const temp=g.add(heat,g.add(g.mul(g.sub(facing,f(.6)),f(.6)),g.add(g.mul(grain,f(.12)),g.mul(light,f(.06)))));
  const brightness=g.add(f(.55),g.add(g.mul(g.step(f(-.35),light),f(.19)),g.add(g.mul(g.step(f(.1),light),f(.26)),g.mul(g.step(f(.55),light),f(.22)))));
  color=g.mul(g.param('smoke','color3f',linear(0x67615b)),brightness);
  for(const [threshold,hex] of [[.29,0x4a2618],[.38,0xc22a17],[.56,0xff7417],[.78,0xffd23f],[1,0xfffbe6]]) color=g.mix(color,g.val('color3f',linear(hex)),g.step(f(threshold),temp));
  color=g.mul(color,g.sub(f(1),g.mul(g.mul(g.step(f(.29),temp),g.step(light,f(-.4))),f(.18))));
 }
 const geom=g.node('ND_realitykit_geometrymodifier_2_0_vertexshader','token',{modelPositionOffset:offset});
 all.push(g.surface(g.fog(color),opacity,geom));
}
for(const kind of ['Ring','MuzzleJet','Flash']){
 const g=new Graph(kind),f=x=>g.val('float',x),v=(x,y)=>g.val('float2',[x,y]);
 const uv=g.node('ND_texcoord_vector2','float2',{index:g.val('int',0)}), p=g.sub(g.mul(uv,f(2)),v(1,1));
 const seed=g.param('seed','float',0), age=g.param('age','float',0);
 const x=g.extract(p,0),y=g.extract(p,1),r=g.unary('magnitude',p);
 const a=g.node('ND_atan2_float','float',{iny:y,inx:x});
 const hash=n=>g.unary('fract',g.mul(g.unary('sin',n),f(43758.5453)));
 let color,opacity;
 if(kind==='Ring'){
  const radius=g.sub(f(1),g.op('power',g.sub(f(1),age),f(3))),width=g.mix(f(.045),f(.008),age);
  const breakup=g.add(g.add(g.mul(g.unary('sin',g.add(g.mul(a,f(7)),seed)),f(.3)),g.mul(g.unary('sin',g.sub(g.mul(a,f(13)),g.mul(seed,f(2)))),f(.2))),f(.5));
  opacity=g.mul(g.step(g.unary('absval',g.sub(r,radius)),g.mul(width,f(.5))),g.mul(g.step(g.sub(g.mul(age,f(1.1)),f(.25)),breakup),g.sub(f(1),g.mul(age,f(.5)))));
  color=g.param('color','color3f',linear(0xffe7ba));
 }else if(kind==='MuzzleJet'){
  const t=g.extract(uv,1),across=g.unary('absval',x),notch=hash(g.add(g.unary('floor',g.mul(t,f(7))),g.mul(seed,f(13.7))));
  const width=g.mul(g.unary('sin',g.mul(g.op('power',t,f(.55)),f(Math.PI))),g.add(f(.6),g.mul(notch,f(.4))));
  const k=g.op('divide',across,g.op('max',width,f(.0001)));
  color=g.mix(g.val('color3f',linear(0xff7417)),g.val('color3f',linear(0xffd23f)),g.step(k,f(.7)));
  color=g.mix(color,g.val('color3f',linear(0xfffbe6)),g.mul(g.step(k,f(.35)),g.step(t,f(.75))));
  opacity=g.step(across,width);
 }else{
  const sector=g.mul(g.op('divide',g.add(a,seed),f(2*Math.PI)),g.param('spikes','float',7));
  const across=g.mul(g.unary('absval',g.sub(g.unary('fract',sector),f(.5))),f(2));
  const ray=g.add(f(.35),g.mul(hash(g.add(g.mul(g.unary('floor',sector),f(17.31)),g.mul(seed,f(3.1)))),f(.65)));
  const radius=g.mix(ray,f(.3),g.op('power',across,f(.3)));
  opacity=g.step(r,radius);
  color=g.mix(g.val('color3f',linear(0xff7417)),g.val('color3f',linear(0xffd23f)),g.step(r,g.mul(radius,f(.7))));
  color=g.mix(color,g.val('color3f',linear(0xfffbe6)),g.step(r,f(.2)));
 }
 all.push(g.surface(color,opacity));
}

{
 const g=new Graph('Trail'),f=x=>g.val('float',x);
 const uv=g.node('ND_texcoord_vector2','float2',{index:g.val('int',0)});
 const across=g.extract(uv,0), age=g.extract(uv,1);
 const world=g.position(), eye=g.node('ND_realitykit_cameraposition_vector3','float3');
 const view=g.unary('normalize',g.sub(eye,world));
 const tangent=g.node('ND_tangent_vector3','float3',{space:g.val('string','world'),index:g.val('int',0)});
 const side=g.unary('normalize',g.node('ND_crossproduct_vector3','float3',{in1:tangent,in2:view}));
 const width=g.mul(g.param('width','float',1),g.add(f(.3),g.mul(f(1.2),g.unary('sqrt',age))));
 const offsetWorld=g.mul(side,g.mul(across,width));
 const offset=g.node('ND_transformvector_vector3','float3',{in:offsetWorld,fromspace:g.val('string','world'),tospace:g.val('string','object')});
 const seed=g.param('seed','float',0),seed3=g.node('ND_combine3_vector3','float3',{in1:seed,in2:seed,in3:seed});
 const noise=p=>g.node('ND_noise3d_float','float',{position:p});
 const n=noise(g.add(g.mul(world,f(.7)),seed3)),n2=noise(g.sub(g.mul(world,f(1.6)),g.mul(seed3,f(1.3))));
 const edge=g.sub(f(1),g.mul(g.add(g.mul(n2,f(.5)),f(.5)),f(.3)));
 const abs=g.unary('absval',across);
 const opacity=g.mul(g.step(abs,edge),g.step(g.mul(g.sub(age,f(.35)),f(1.5)),g.add(g.mul(n,f(.5)),f(.5))));
 const sv=g.node('ND_clamp_float','float',{in:g.op('divide',across,edge),low:f(-1),high:f(1)});
 const normal=g.unary('normalize',g.add(g.mul(side,sv),g.mul(view,g.unary('sqrt',g.op('max',f(0),g.sub(f(1),g.mul(sv,sv)))))));
 const light=g.node('ND_dotproduct_vector3','float',{in1:normal,in2:g.param('sunDirection','float3',[-.354,.798,.488])});
 const brightness=g.add(f(.6),g.add(g.mul(g.step(f(-.35),light),f(.18)),g.mul(g.step(f(.15),light),f(.22))));
 const hot=g.param('hot','float',1),isHot=g.step(age,g.mul(f(.1),hot));
 let color=g.mul(g.param('smoke','color3f',linear(0xc9c5bd)),brightness);
 color=g.mix(color,g.val('color3f',linear(0xff7417)),isHot);
 color=g.mix(color,g.val('color3f',linear(0xffd23f)),g.step(age,g.mul(f(.045),hot)));
 color=g.mix(color,g.mix(g.val('color3f',linear(0x1a1817)),g.val('color3f',linear(0x6e1a0b)),isHot),g.step(g.sub(edge,f(.17)),abs));
 const geom=g.node('ND_realitykit_geometrymodifier_2_0_vertexshader','token',{modelPositionOffset:offset});
 all.push(g.surface(g.fog(color),opacity,geom));
}

{
 const g=new Graph('Plume'),f=x=>g.val('float',x);
 const uv=g.node('ND_texcoord_vector2','float2',{index:g.val('int',0)}),y=g.extract(uv,1),x=g.sub(g.mul(g.extract(uv,0),f(2)),f(1)),abs=g.unary('absval',x);
 const seed=g.param('seed','float',0),age=g.param('age','float',0);
 let hw=g.add(g.mul(g.sub(f(1),g.op('power',y,f(2.4))),f(.85)),g.mul(g.sub(f(1),y),f(.15)));
 hw=g.mul(hw,g.add(f(.8),g.add(g.mul(g.unary('sin',g.add(g.mul(y,f(13)),g.mul(seed,f(6)))),f(.12)),g.mul(g.unary('sin',g.sub(g.mul(y,f(31)),g.mul(seed,f(9)))),f(.08)))));
 const cx=g.unary('floor',g.add(g.mul(x,f(5)),g.mul(seed,f(13)))),cy=g.unary('floor',g.add(g.mul(y,f(9)),g.mul(seed,f(13))));
 const hash=g.unary('fract',g.mul(g.unary('sin',g.add(g.mul(cx,f(127.1)),g.mul(cy,f(311.7)))),f(43758.5453)));
 const opacity=g.mul(g.step(abs,hw),g.step(g.mul(g.sub(age,f(.55)),f(2.4)),hash));
 const white=g.mul(g.step(abs,g.mul(hw,f(.55))),g.step(y,f(.85)));
 all.push(g.surface(g.mix(g.val('color3f',[.82,.89,.93]),g.val('color3f',[1,1,1]),white),opacity));
}

{
 const g=new Graph('Wake'),f=x=>g.val('float',x),v=(x,y)=>g.val('float2',[x,y]);
 const pos=g.node('ND_position_vector3','float3',{space:g.val('string','object')}),localX=g.extract(pos,0),d=g.extract(pos,2),x=g.unary('absval',localX);
 const scroll=g.param('scroll','float',0), strength=g.param('strength','float',1),w=g.sub(d,scroll);
 const pair=(a,b)=>g.node('ND_combine2_vector2','float2',{in1:a,in2:b});
 const hash=a=>g.unary('fract',g.mul(g.unary('sin',g.node('ND_dotproduct_vector2','float',{in1:a,in2:v(127.1,311.7)})),f(43758.5453)));
 function noise(a){const i=g.unary('floor',a),r=g.unary('fract',a),u=g.mul(g.mul(r,r),g.sub(v(3,3),g.mul(r,f(2))));return g.mix(g.mix(hash(i),hash(g.add(i,v(1,0))),g.extract(u,0)),g.mix(hash(g.add(i,v(0,1))),hash(g.add(i,v(1,1))),g.extract(u,0)),g.extract(u,1));}
 const side=g.add(f(4.052),g.mul(d,f(.06)));
 let foam=g.mul(g.sub(f(1),g.smooth(g.unary('absval',g.sub(x,side)),0,1.3)),g.mul(g.mix(f(.75),f(1),g.step(d,f(3))),g.step(d,f(45.92))));
 const arm=g.mul(d,f(.354)), armWidth=g.add(f(.35),g.mul(d,f(.008)));
 const arms=g.mul(g.step(g.unary('absval',g.sub(x,arm)),armWidth),g.step(f(.42),noise(pair(g.mul(w,f(.35)),g.mul(x,f(.1))))));
 foam=g.op('max',foam,g.mul(arms,f(.8)));
 const aft=g.sub(d,f(45.92)),ahead=g.op('max',aft,f(0));
 const band=g.add(f(3.652*.6),g.mul(ahead,f(.05)));
 const churn=g.mul(g.step(f(-2),aft),g.mul(g.step(x,band),g.step(g.add(f(.38),g.mul(ahead,f(.004))),noise(pair(g.mul(localX,f(.45)),g.mul(w,f(.18)))))));
 foam=g.op('max',foam,churn);
 const fade=g.mul(g.sub(f(1),g.op('divide',d,f(220))),strength);
 const opacity=g.mul(g.step(d,g.op('min',f(220),scroll)),g.mul(g.step(f(.0001),foam),g.step(g.add(f(.2),g.mul(noise(pair(g.mul(localX,f(.7)),g.mul(w,f(.7)))),f(.6))),g.mul(foam,fade))));
 all.push(g.surface(g.mix(g.val('color3f',[.84,.92,.95]),g.val('color3f',[1,1,1]),g.step(f(.9),foam)),opacity));
}

const write = (url, text) => { if(process.argv.includes('--check')) {if(fs.readFileSync(url,'utf8') !== text) throw Error('Stale native shader graphs');} else fs.writeFileSync(url,text); };
write(new URL('../Resources/Visuals/WebShaders.usda',import.meta.url),`#usda 1.0\n(defaultPrim = "Shaders")\ndef Xform "Shaders" {\n${all.join('\n')}\n}\n`);
