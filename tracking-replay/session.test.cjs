const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ReplaySession}=require('./session.cjs');
const image=()=>({width:60,height:40,data:new Uint8ClampedArray(60*40*4).fill(90)});
const box={x:10,y:5,w:12,h:24};
test('a replay gap loses explicitly and exports no current box',()=>{
 const s=new ReplaySession({kind:'synthetic',name:'test'});s.select(image(),box,1);
 const r=s.advance(image(),1.5);assert.equal(r.state,'lost');assert.equal(r.box,null);
 assert.match(r.reason,/discontinuity/i);assert.equal(s.report().events.at(-1).state,'lost');
});
test('a backwards seek invalidates selection and requires explicit reselection',()=>{
 const s=new ReplaySession({kind:'recorded',name:'local.mp4'});s.select(image(),box,2);
 assert.equal(s.advance(image(),1).state,'lost');assert.equal(s.advance(image(),1.1).state,'lost');
 s.select(image(),box,1.1);assert.equal(s.result().state,'tracking');
 assert.equal(s.report().events.filter(e=>e.event==='selection').length,2);
});
test('reset discards prior identity and reports source and synthetic status',()=>{
 const s=new ReplaySession({kind:'synthetic',name:'crossing'});s.select(image(),box,0);s.reset();
 assert.equal(s.result().state,'unselected');assert.deepEqual(s.report().source,{kind:'synthetic',name:'crossing'});
 assert.equal(s.report().events.length,0);
});
test('seek before selection remains unselected',()=>{
 const s=new ReplaySession({kind:'recorded',name:'clip'});s.discontinuity(4);
 assert.equal(s.result().state,'unselected');
});
test('export is detached from live session state',()=>{
 const s=new ReplaySession({kind:'synthetic',name:'crossing'});s.select(image(),box,0);
 const out=s.report();out.events[0].box.x=100;out.source.kind='changed';
 assert.equal(s.report().events[0].box.x,10);assert.equal(s.report().source.kind,'synthetic');
});
