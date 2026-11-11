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
