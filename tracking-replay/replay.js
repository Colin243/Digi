'use strict';
const canvas=document.querySelector('#screen'),ctx=canvas.getContext('2d',{willReadFrequently:true});
const raw=document.createElement('canvas'),pixels=raw.getContext('2d',{willReadFrequently:true});
const video=document.querySelector('#video'),status=document.querySelector('#status'),play=document.querySelector('#play');
const timeline=document.querySelector('#timeline'),sourceLabel=document.querySelector('#source');
let session=new window.ReplaySession({kind:'synthetic',name:'two-subject-crossing'});
let playing=false,t=0,lastTime=null,drag=null,url=null,timer=null;
const synthetic=()=>session.source.kind==='synthetic';
function dimensions(width,height){canvas.width=raw.width=width;canvas.height=raw.height=height;}
function paint(){
 pixels.fillStyle='#252a30';pixels.fillRect(0,0,raw.width,raw.height);
 if(!synthetic()&&video.readyState>=2)pixels.drawImage(video,0,0,raw.width,raw.height);
 if(synthetic()){
  const x=25+Math.min(t,7)*32,other=260-Math.min(t,7)*32;
  for(const [a,color,name] of [[x,'#dc2020','Selected'],[other,'#1450e6','Other']]){
   pixels.fillStyle=color;pixels.fillRect(a,55,30,80);pixels.beginPath();pixels.arc(a+15,40,12,0,Math.PI*2);pixels.fill();
   pixels.fillStyle='#fff';pixels.font='10px system-ui';pixels.fillText(name,a-2,155);
  }
 }
 ctx.drawImage(raw,0,0);
 const r=session.result();
 status.textContent=`${r.state.toUpperCase()} · ${t.toFixed(1)}s · ${r.reason}`;
 status.dataset.state=r.state;
 if(r.box){ctx.strokeStyle='#6ee7a0';ctx.lineWidth=2;ctx.strokeRect(r.box.x,r.box.y,r.box.w,r.box.h);}
 timeline.value=t;
}
const image=()=>pixels.getImageData(0,0,raw.width,raw.height);
function pause(){playing=false;video.pause();play.textContent='Play';clearTimeout(timer);}
function restart(){pause();t=0;lastTime=null;if(!synthetic())video.currentTime=0;session.reset();paint();}
function tick(){
 if(!playing)return;
 if(synthetic())t=Math.min(7,t+.1);else t=video.currentTime;
 paint();
 if(lastTime!==t){session.advance(image(),t);lastTime=t;paint();}
 if((synthetic()&&t>=7)||(!synthetic()&&video.ended))pause();
 else timer=setTimeout(tick,100);
}
play.onclick=async()=>{
 if(playing){pause();return;}
 playing=true;play.textContent='Pause';
 try{
  if(!synthetic())await video.play();
  if(!playing)return;
  lastTime=t;tick();
 }catch(error){pause();status.textContent=`Cannot play: ${error.message}`;}
};
document.querySelector('#reset').onclick=restart;
document.querySelector('#fixture').onclick=()=>{
 pause();video.onloadeddata=null;video.onerror=null;session=new window.ReplaySession({kind:'synthetic',name:'two-subject-crossing'});
 dimensions(320,180);timeline.max=7;sourceLabel.textContent='Synthetic crossing · red subject selected';restart();
 session.select(image(),{x:25,y:55,w:30,h:80},0);paint();play.click();
};
document.querySelector('#file').onchange=e=>{
 const file=e.target.files[0];if(!file)return;
 pause();if(url)URL.revokeObjectURL(url);
 session=new window.ReplaySession({kind:'recorded',name:file.name});t=0;lastTime=null;
 sourceLabel.textContent=`Local clip · ${file.name}`;
 url=URL.createObjectURL(file);video.src=url;
 video.onloadeddata=()=>{
  // Keep the source aspect ratio; selection and exported boxes use this space.
  const scale=320/Math.max(video.videoWidth,video.videoHeight);
  dimensions(Math.max(6,Math.round(video.videoWidth*scale)),Math.max(6,Math.round(video.videoHeight*scale)));
  timeline.max=Number.isFinite(video.duration)?video.duration:0;paint();
 };
 video.onerror=()=>{pause();status.textContent='Unsupported clip — try H.264 MP4';};
};
timeline.oninput=()=>{
 pause();t=Number(timeline.value);lastTime=null;session.discontinuity(t);
 if(!synthetic())video.currentTime=t;
 paint();
};
video.onseeked=()=>{if(!synthetic()){t=video.currentTime;paint();}};
function point(e){
 const b=canvas.getBoundingClientRect();
 return {x:Math.max(0,Math.min(raw.width,(e.clientX-b.left)*raw.width/b.width)),y:Math.max(0,Math.min(raw.height,(e.clientY-b.top)*raw.height/b.height))};
}
canvas.onpointerdown=e=>{
 if(!synthetic()&&(video.readyState<2||video.seeking))return;
 pause();drag=point(e);canvas.setPointerCapture(e.pointerId);
};
canvas.onpointermove=e=>{
 if(!drag)return;paint();const p=point(e);ctx.strokeStyle='#fff';ctx.strokeRect(drag.x,drag.y,p.x-drag.x,p.y-drag.y);
};
canvas.onpointerup=e=>{
 if(!drag)return;
 const p=point(e),box={x:Math.min(p.x,drag.x),y:Math.min(p.y,drag.y),w:Math.abs(p.x-drag.x),h:Math.abs(p.y-drag.y)};drag=null;
 try{session.select(image(),box,t);lastTime=t;paint();}catch(error){status.textContent=error.message;}
};
canvas.onpointercancel=()=>{drag=null;paint();};
document.querySelector('#download').onclick=()=>{
 const report={...session.report(),coordinateSpace:{width:raw.width,height:raw.height},seconds:t};
 const href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=href;a.download='tracking-events.json';a.click();
 setTimeout(()=>URL.revokeObjectURL(href),1000);
};
dimensions(320,180);paint();
