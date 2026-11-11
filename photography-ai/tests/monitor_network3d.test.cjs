const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../src/photo_ai/training/monitor/dashboard.html'),'utf8');
const block=html.match(/\/\/ BEGIN NETWORK3D MATH([\s\S]*?)\/\/ END NETWORK3D MATH/);
assert.ok(block,'dashboard must expose its pure 3D math block for regression tests');
const context={};vm.createContext(context);vm.runInContext(block[1]+';globalThis.math=Network3D;',context);
const m=context.math;
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} ≠ ${b}`);
test('orbit rotates actual depth into the horizontal plane without changing radius',()=>{
 const c=m.camera();c.yaw=Math.PI/2;c.pitch=0;
 const p=m.rotate({x:0,y:0,z:100},c);close(p.x,100);close(p.z,0);close(Math.hypot(p.x,p.y,p.z),100);
});
test('perspective makes nearer points larger and yaw reveals different sides',()=>{
 const c=m.camera();c.yaw=0;c.pitch=0;
 const near=m.project({x:80,y:0,z:-200},c,1000,700),far=m.project({x:80,y:0,z:200},c,1000,700);
 assert.ok(near.scale>far.scale);assert.ok(near.x>far.x);
 c.yaw=Math.PI;const back=m.project({x:80,y:0,z:-200},c,1000,700);assert.ok(back.x<500);
});
test('zoom and panning remain bounded, with a recoverable reset',()=>{
 const c=m.camera();m.zoom(c,100);assert.equal(c.zoom,3.5);m.zoom(c,0.0001);assert.equal(c.zoom,0.4);
 m.orbit(c,10000,10000);assert.ok(c.pitch<=Math.PI*.49);assert.ok(Number.isFinite(c.yaw));
 m.pan(c,1e8,-1e8,1000,700);assert.equal(c.panX,1000);assert.equal(c.panY,-700);
 assert.equal(m.camera().zoom,1);assert.equal(m.camera().panX,0);
});
test('picking chooses the front visible node at overlapping projected positions',()=>{
 const nodes=[{key:'back',px:100,py:100,depth:200,screenR:5},{key:'front',px:100,py:100,depth:-200,screenR:5}];
 assert.equal(m.pick(nodes,100,100).key,'front');assert.equal(m.pick(nodes,400,400),null);
});
test('projection stays finite at narrow viewports and zoom extremes',()=>{
 const c=m.camera();m.zoom(c,100);
 for(const yaw of [0,Math.PI/2,Math.PI,Math.PI*2]){c.yaw=yaw;const p=m.project({x:500,y:300,z:-250},c,280,360);assert.ok([p.x,p.y,p.scale,p.depth].every(Number.isFinite));}
});
test('idle orbit waits 20 seconds and only runs in a visible display view',()=>{
 const state={enabled:true,display:true,visible:true,hidden:false,reducedMotion:false,motionOverride:false,lastInteraction:1000};
 assert.equal(m.shouldOrbit(state,20999),false);assert.equal(m.shouldOrbit(state,21000),true);
 for(const key of ['enabled','display','visible'])assert.equal(m.shouldOrbit({...state,[key]:false},22000),false);
 assert.equal(m.shouldOrbit({...state,hidden:true},22000),false);
 assert.equal(m.shouldOrbit({...state,reducedMotion:true},22000),false);
 assert.equal(m.shouldOrbit({...state,reducedMotion:true,motionOverride:true},22000),true);
 assert.equal(m.shouldOrbit({...state,lastInteraction:21999},22000),false);
});
const cols=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'];
const units=[...Array.from({length:24},(_,block)=>({group:'vision_encoder',block})),...Array.from({length:28},(_,block)=>cols.map(c=>({group:'language_model',block,name:`language_model.model.layers.${block}.${['gate_proj','up_proj','down_proj'].includes(c)?'mlp':'self_attn'}.${c}`,lora:{rank:8}}))).flat()];
const topologyContext={S:{run:{architecture:{units,dataflow:{deepstack_visual_indexes:[5,11,17]}}}},LORA_COLS:cols,lmColor:()=> '#fff'};
vm.createContext(topologyContext);
const buildSource=html.match(/function buildNet\(W, H\) \{[\s\S]*?\n}\n(?=function drawNet)/);
assert.ok(buildSource,'world geometry must be testable independently of rendering');
vm.runInContext(buildSource[0]+';globalThis.graph=buildNet(1000,600);',topologyContext);
const graph=topologyContext.graph;
test('the sculptural layout contains exactly the real units and unique finite XYZ positions',()=>{
 assert.equal(graph.nodes.length,254);assert.equal(new Set(graph.nodes.map(n=>n.key)).size,254);
 for(const u of units.filter(u=>u.lora))assert.ok(graph.nodes.some(n=>n.key===u.name));
 assert.ok(graph.nodes.every(n=>[n.x,n.y,n.z].every(Number.isFinite)));
 assert.ok(graph.edges.every(([a,b])=>graph.nodes.includes(a)&&graph.nodes.includes(b)));
});
test('DeepStack connections retain their configured source blocks and destination layers',()=>{
 for(const [i,source] of [5,11,17].entries()){
  const key=`block:connector:vision_tower.deepstack_merger_list.${i}`;
  assert.ok(graph.edges.some(([a,b])=>a.key===`block:vision_encoder:${source}`&&b.key===key));
  assert.ok(graph.edges.some(([a,b])=>a.key===key&&b.key===`block:language_model:${i}`));
 }
});
test('decoder clusters occupy a three-dimensional volume instead of a flat spiral',()=>{
 const hubs=graph.nodes.filter(n=>n.kind==='hub');
 for(const [axis,min] of [['x',250],['y',200],['z',230]]){
  const values=hubs.map(n=>n[axis]);assert.ok(Math.max(...values)-Math.min(...values)>min,`${axis} must have substantial depth/spread`);
 }
 const [a,b,c,d]=hubs.slice(0,4),u=[b.x-a.x,b.y-a.y,b.z-a.z],v=[c.x-a.x,c.y-a.y,c.z-a.z],w=[d.x-a.x,d.y-a.y,d.z-a.z];
 const volume=Math.abs(u[0]*(v[1]*w[2]-v[2]*w[1])-u[1]*(v[0]*w[2]-v[2]*w[0])+u[2]*(v[0]*w[1]-v[1]*w[0]));
 assert.ok(volume>1000,'clusters must not be coplanar');
});
const pollSource=html.match(/async function poll\(\) \{[\s\S]*?\n}\n(?=function ingest)/);
assert.ok(pollSource,'data refresh must remain testable without a page reload');
function pollingHarness(){
 const timers=[],requests=[],ingested=[],renders=[];
 const state={path:'run-a',runGeneration:1,readyGeneration:1,offset:0,malformed:0,status:{}};
 const c={S:state,Date,clearTimeout:()=>{},setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length;},api:(path,q)=>new Promise(resolve=>requests.push({q,resolve})),ingest:events=>ingested.push(...events),render:()=>renders.push(true)};
 vm.createContext(c);vm.runInContext(pollSource[0]+';globalThis.refresh=poll;',c);
 return {c,state,timers,requests,ingested,renders};
}
const eventResponse=events=>({events,next_offset:40,malformed:0,state:'running',status:{},eof:true});
test('overlapping data refreshes serialize without replacing the page',{timeout:1000},async()=>{
 const h=pollingHarness(),first=h.c.refresh();await h.c.refresh();assert.equal(h.requests.length,1);
 h.requests[0].resolve(eventResponse([{kind:'step',step:1}]));await first;
 assert.equal(h.ingested.length,1);assert.equal(h.renders.length,1);
 const queued=h.timers.find(t=>t.ms===0);assert.ok(queued,'one refresh must be queued after the active request');
 const second=queued.fn();assert.equal(h.requests.length,2);h.requests[1].resolve(eventResponse([]));await second;
 assert.equal(h.state.offset,40);assert.equal(h.state.polling,false);
});
test('responses from an old run cannot enter a newly selected run',{timeout:1000},async()=>{
 const h=pollingHarness(),first=h.c.refresh();h.state.path='run-b';h.state.runGeneration=2;h.state.readyGeneration=2;await h.c.refresh();
 h.requests[0].resolve(eventResponse([{kind:'step',step:999}]));await first;
 assert.equal(h.ingested.length,0);assert.equal(h.renders.length,0);
 const second=h.timers.find(t=>t.ms===0).fn();assert.equal(h.requests[1].q.path,'run-b');h.requests[1].resolve(eventResponse([{kind:'step',step:1}]));await second;
 assert.equal(h.ingested[0].step,1);
});

test('data refresh waits for the selected run metadata to be ready',{timeout:1000},async()=>{
 const h=pollingHarness();h.state.path='run-b';h.state.runGeneration=2;h.state.readyGeneration=null;
 const loading=h.c.refresh();assert.equal(h.requests.length,0,'no events may be polled against old metadata');await loading;
 h.state.readyGeneration=2;const ready=h.c.refresh();assert.equal(h.requests.length,1);h.requests[0].resolve(eventResponse([]));await ready;
});
