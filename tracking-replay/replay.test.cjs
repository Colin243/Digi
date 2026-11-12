const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
// Minimal DOM/canvas boundary: replay/session/tracker execute unchanged.
function page(){
 const timers=[];
 function element(id){
  const e={id,width:320,height:180,value:0,dataset:{},style:{},readyState:0,currentTime:0,
   pause(){},async play(){},click(){return this.onclick?.();},setPointerCapture(){},
   getBoundingClientRect(){return {left:0,top:0,width:this.width,height:this.height};}};
  let data;
  const context={
   fillStyle:'#000000',
   fillRect(x,y,w,h){
    if(!data||data.length!==e.width*e.height*4)data=new Uint8ClampedArray(e.width*e.height*4);
    const hex=this.fillStyle.slice(1),rgb=[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16));
    for(let j=Math.ceil(y);j<Math.min(e.height,y+h);j++)for(let i=Math.ceil(x);i<Math.min(e.width,x+w);i++)data.set([...rgb,255],(j*e.width+i)*4);
   },
   getImageData(){return {width:e.width,height:e.height,data:new Uint8ClampedArray(data)};},
   drawImage(source){if(source.getContext)data=new Uint8ClampedArray(source.getContext().getImageData().data);},
   beginPath(){},arc(){},fill(){},fillText(){},strokeRect(){}
  };
  e.getContext=()=>context;return e;
 }
 const ids=['screen','video','status','play','timeline','source','reset','fixture','file','download'];
 const elements=Object.fromEntries(ids.map(id=>[id,element(id)]));
 const document={querySelector:s=>elements[s.slice(1)],createElement:tag=>element(tag)};
 const sandbox={document,window:{},Uint8ClampedArray,Blob,URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){}},
  setTimeout:cb=>{timers.push(cb);return cb;},clearTimeout:cb=>{const i=timers.indexOf(cb);if(i>=0)timers.splice(i,1);}};
 vm.createContext(sandbox);
 for(const file of ['tracker.cjs','session.cjs','replay.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,file),'utf8'),sandbox,{filename:file});
 return {elements,timers,read:expression=>vm.runInContext(expression,sandbox)};
}
test('one-click synthetic crossing shows sticky LOST and exports an auditable timeline',async()=>{
 const p=page();await p.elements.fixture.click();
 assert.match(p.elements.status.textContent,/TRACKING/);
 for(let n=0;n<100&&p.timers.length;n++)p.timers.shift()();
 assert.match(p.elements.status.textContent,/LOST/);assert.equal(p.elements.play.textContent,'Play');
 const report=p.read('session.report()');
 assert.equal(report.source.kind,'synthetic');assert.equal(report.events[0].event,'selection');
 const lost=report.frames.findIndex(frame=>frame.state==='lost');assert.ok(lost>0);
 assert.ok(report.frames.slice(lost).every(frame=>frame.state==='lost'&&frame.box===null));
 assert.ok(report.frames.at(-1).seconds>=7);
});
test('loading a portrait clip preserves aspect ratio and clears previous selection',()=>{
 const p=page();p.elements.file.onchange({target:{files:[{name:'portrait.mp4'}]}});
 const video=p.elements.video;video.videoWidth=1080;video.videoHeight=1920;video.duration=5;video.readyState=2;video.onloadeddata();
 assert.equal(p.elements.screen.width,180);assert.equal(p.elements.screen.height,320);
 assert.equal(p.read('session.result().state'),'unselected');assert.match(p.elements.source.textContent,/portrait.mp4/);
});
test('timeline seeking clears a selected subject with a visible reason',async()=>{
 const p=page();await p.elements.fixture.click();p.elements.timeline.value=3;p.elements.timeline.oninput();
 assert.match(p.elements.status.textContent,/LOST.*discontinuity/);assert.equal(p.elements.play.textContent,'Play');
 assert.equal(p.read('session.result().box'),null);
});
