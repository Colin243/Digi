const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Tracker}=require('./tracker.cjs');
function frame(people=[]) {
  const data=new Uint8ClampedArray(100*60*4);
  for(const [x,y,w,h,r,g,b] of people) for(let j=y;j<y+h;j++) for(let i=x;i<x+w;i++) data.set([r,g,b,255],(j*100+i)*4);
  return {width:100,height:60,data};
}
const red=x=>[x,15,12,24,220,30,30];
const blue=x=>[x,15,12,24,20,50,230];
const setup=()=>{const t=new Tracker();t.select(frame([red(10)]),{x:10,y:15,w:12,h:24});return t;};
test('follows selected appearance rather than other person',()=>{
 const t=setup(); const r=t.update(frame([red(16),blue(60)])); assert.equal(r.state,'tracking');assert.ok(Math.abs(r.box.x-16)<=2);
});
test('disappearance is lost with no current subject box',()=>{const r=setup().update(frame());assert.equal(r.state,'lost');assert.equal(r.box,null);});
test('never reacquires after loss without selection',()=>{const t=setup();t.update(frame());assert.equal(t.update(frame([red(10)])).state,'lost');});
test('equally plausible separated subjects are ambiguous',()=>{const r=setup().update(frame([red(3),red(22)]));assert.equal(r.state,'lost');});
test('occluder at crossing cannot replace selected person',()=>{const t=setup();const r=t.update(frame([blue(10)]));assert.equal(r.state,'lost');});
test('crossing sequence follows red or loses, never follows blue',()=>{const t=setup();for(let i=1;i<=8;i++){const x=10+i*5;const r=t.update(frame([red(x),blue(70-i*5)]));if(r.state==='tracking')assert.ok(Math.abs(r.box.x-x)<=2);else assert.equal(r.box,null);}});
test('selection required after reset',()=>{const t=setup();t.reset();assert.equal(t.update(frame()).state,'unselected');});
test('invalid selection rejected',()=>{assert.throws(()=>new Tracker().select(frame(),{x:-2,y:0,w:12,h:24}));});

test('changed frame dimensions lose rather than sampling stale coordinates',()=>{
 const t=setup();const r=t.update({width:20,height:20,data:new Uint8ClampedArray(1600)});
 assert.equal(r.state,'lost');assert.equal(r.box,null);assert.match(r.reason,/dimensions/i);
});
test('malformed image buffers are rejected before selection',()=>{
 const t=new Tracker();assert.throws(()=>t.select({width:100,height:60,data:new Uint8ClampedArray(4)},{x:10,y:15,w:12,h:24}),/frame/i);
 assert.equal(t.state,'unselected');
});
test('malformed update loses visibly and cannot reacquire',()=>{
 const t=setup();assert.equal(t.update({width:100,height:60,data:[]}).state,'lost');
 assert.equal(t.update(frame([red(10)])).state,'lost');
});
test('explicit reselection permits tracking after loss',()=>{
 const t=setup();t.update(frame());t.select(frame([blue(60)]),{x:60,y:15,w:12,h:24});
 const r=t.update(frame([blue(55)]));assert.equal(r.state,'tracking');assert.ok(Math.abs(r.box.x-55)<=2);
});
test('returned boxes cannot modify tracker state',()=>{
 const t=setup();t.result().box.x=90;assert.equal(t.result().box.x,10);
});
test('similar-looking crossing stops before identities become ambiguous',()=>{
 const t=setup();let lost=false;
 for(let i=1;i<=8;i++){
  const x=10+i*5,other=70-i*5,r=t.update(frame([red(x),red(other)]));
  if(r.state==='lost')lost=true;
  if(!lost)assert.ok(Math.abs(r.box.x-x)<=2);
  else assert.equal(r.box,null);
 }
 assert.equal(lost,true);
});
