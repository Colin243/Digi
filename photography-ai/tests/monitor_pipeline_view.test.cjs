const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../src/photo_ai/training/monitor/dashboard.html'),'utf8');
const block=html.match(/\/\/ BEGIN PIPELINE GRAPH([\s\S]*?)\/\/ END PIPELINE GRAPH/);
assert.ok(block,'dashboard must expose its pure pipeline graph block for regression tests');
const ctx={};vm.createContext(ctx);vm.runInContext(block[1]+';globalThis.api={buildPipeline,pipeSecs,joinModel,pipeFit};',ctx);
const {buildPipeline,pipeSecs,joinModel,pipeFit}=ctx.api;
const same=(a,b)=>assert.equal(JSON.stringify(a),JSON.stringify(b)); // arrays made inside vm are another realm
const stage=(name,wall,extra={})=>({name,phase:/notes|aesthetic/.test(name)?'prepare':'plan',cases:14,wall_s:wall,prompt_tokens:700,generation_tokens:70,prefill_s:1.2,decode_s:.9,...extra});
const data={model:'fused q5',stages:[1,2,3,4].map(i=>stage('notes_inspiration'+i,2.1)).concat([stage('aesthetic_from_notes',4.8),stage('target_scene',3.4),stage('compositions',14.8)])};
test('every stage in the data becomes one node and nothing is invented',()=>{
 const g=buildPipeline(data),keys=g.nodes.map(n=>n.key),stages=g.nodes.filter(n=>n.kind==='stage');
 assert.equal(new Set(keys).size,keys.length);
 same(stages.map(n=>n.key).sort(),data.stages.map(s=>s.name).sort().map(n=>n==='aesthetic_from_notes'?'aesthetic':n).sort());
 assert.equal(g.nodes.filter(n=>n.kind==='photo'&&n.phase==='prepare').length,4);
 assert.equal(g.nodes.filter(n=>n.kind==='output').length,3);
});
test('prepare-ahead stages never depend on the target photo, and the plan stages sit after the references gate',()=>{
 const g=buildPipeline(data),by=Object.fromEntries(g.nodes.map(n=>[n.key,n]));
 const into=k=>g.edges.filter(e=>e[1].key===k).map(e=>e[0].key);
 for(const n of g.nodes.filter(x=>x.phase==='prepare'))for(const src of into(n.key))assert.notEqual(src,'targetphoto'),assert.notEqual(by[src].phase,'plan');
 same(into('refs'),['aesthetic']);
 assert.ok(into('compositions').includes('refs')&&into('compositions').includes('target_scene'));
});
test('joining the real model wires photo stages to the vision tower and text stages to the token embedding',()=>{
 const mk=k=>({key:k,x:0,y:-100,z:0,kind:'frozen'});
 const model={nodes:[mk('vision_tower.patch_embed.proj'),mk('block:language_model:language_model.model.embed_tokens'),mk('other')],edges:[]};
 const pipe=buildPipeline(data),g=joinModel(pipe,model,'Qwen3.5'),links=g.edges.filter(e=>model.nodes.includes(e[0]));
 const stages=pipe.nodes.filter(n=>n.kind==='stage');
 assert.equal(g.joined,stages.length);assert.equal(links.length,stages.length);
 for(const [src,dst] of links)assert.equal(src.key,dst.needsImage?'vision_tower.patch_embed.proj':'block:language_model:language_model.model.embed_tokens');
 assert.equal(links.find(e=>e[1].key==='aesthetic')[0].key,'block:language_model:language_model.model.embed_tokens');
 assert.equal(g.nodes.length,model.nodes.length+pipe.nodes.length+1);
 assert.equal(joinModel(pipe,null,'x').joined,0);
});
test('node size follows the measured time; missing data still draws a labelled map',()=>{
 const g=buildPipeline(data),r=k=>g.nodes.find(n=>n.key===k).r;
 assert.ok(r('compositions')>r('aesthetic')&&r('aesthetic')>r('target_scene')&&r('target_scene')>r('notes_inspiration1'));
 const empty=buildPipeline({stages:[]});
 assert.ok(empty.nodes.length>10);assert.ok(empty.nodes.find(n=>n.key==='compositions').tip.includes('compositions'));
 assert.equal(pipeSecs(null),'not measured');assert.equal(pipeSecs(31.52),'31.5 s');
});
test('fitting frames every node inside the canvas and centres the group, whatever the window size or shape',()=>{
 const project=(p,c,w,h)=>({x:w/2+c.panX+p.x*c.zoom*.4,y:(h-90)/2+30+c.panY+p.y*c.zoom*.4});
 const nodes=[];for(let i=0;i<40;i++)nodes.push({x:-1000+i*52,y:(i%7)*60-180,z:0});nodes.push({kind:'caption',x:9e4,y:9e4,z:0});
 for(const [W,H] of [[800,560],[1440,900],[500,700],[1920,1080]]){
  const cam=pipeFit({zoom:1,panX:7,panY:9},nodes,W,H,project);
  let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
  for(const n of nodes.filter(n=>n.kind!=='caption')){const p=project(n,cam,W,H);x0=Math.min(x0,p.x);x1=Math.max(x1,p.x);y0=Math.min(y0,p.y);y1=Math.max(y1,p.y);}
  assert.ok(x0>=W*.04&&x1<=W*.96,`${W}x${H} x ${x0}..${x1}`);assert.ok(y0>=0&&y1<=H-90+30,`${W}x${H} y ${y0}..${y1}`);
  assert.ok(Math.abs((x0+x1)/2-W/2)<8,`${W}x${H} not centred horizontally`);assert.ok(Math.abs((y0+y1)/2-((H-90)/2+30))<8,`${W}x${H} not centred vertically`);
  assert.ok(cam.zoom>=.4&&cam.zoom<=3.5);
 }
 const same=pipeFit({zoom:3,panX:1,panY:2},[],800,560,project);assert.equal(same.zoom,3);
});
