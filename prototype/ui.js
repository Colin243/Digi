(function () {
  const root=document.getElementById('digit-lab'); const $=s=>root.querySelector(s);
  const {CameraSimulation,renderPixels}=globalThis.DigitSimulation;
  const camera=new CameraSimulation(); const width=960,height=540;
  const source=$('.source'),processed=$('.processed'); const src=source.getContext('2d',{willReadFrequently:true}); const dst=processed.getContext('2d');
  let pixels, originalPixels, comparison=false, imageGeneration=0;
  const status=text=>{$('.save-status').textContent=text;};
  function render() {
    const s=camera.settings;
    if(pixels) dst.putImageData(new ImageData(renderPixels(pixels,s,width,height),width,height),0,0);
    const manual=s.mode==='Manual'; $('.iso').disabled=!manual; $('.speed').disabled=!manual; $('.ev').disabled=manual;
    $('.iso').value=manual?s.iso:100;$('.speed').value=manual?s.shutter:125;
    $('.mode-indicator').textContent=manual?'M':'AUTO'; $('.exposure-readout').textContent=manual?`1/${s.shutter}  ISO ${s.iso}`:'1/125  ISO 100';
    $('.wb-readout').textContent=s.wb.toUpperCase(); $('.ev-label').textContent=manual?'EV off':`EV ${s.ev>=0?'+':''}${s.ev.toFixed(1)}`;
    $('.exposure-help').textContent=manual?'ISO and shutter control exposure. EV is off.':'Switch to M to adjust ISO and shutter speed.';
    $('.recipe').value=s.recipe; root.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===s.mode)));
  }
  function load(image,label) {
    src.fillStyle='#333';src.fillRect(0,0,width,height);
    const scale=Math.max(width/image.naturalWidth,height/image.naturalHeight);
    src.drawImage(image,(width-image.naturalWidth*scale)/2,(height-image.naturalHeight*scale)/2,image.naturalWidth*scale,image.naturalHeight*scale);
    originalPixels=src.getImageData(0,0,width,height).data; $('.image-credit').textContent=label; applySampleLighting();
  }
  function fallback() {
    const gradient=src.createLinearGradient(0,0,width,height);gradient.addColorStop(0,'#9bb4bf');gradient.addColorStop(1,'#d6be9d');src.fillStyle=gradient;src.fillRect(0,0,width,height);
    ['#bd826b','#815b4c','#ecc3a4','#536b4b','#8d353b','#41647d'].forEach((color,i)=>{src.fillStyle=color;src.fillRect(30+(i%3)*110,210+Math.floor(i/3)*130,100,110);});
    for(let i=0;i<12;i++){src.fillStyle=`rgb(${i*23},${i*23},${i*23})`;src.fillRect(30+i*27,490,27,65);}
    originalPixels=src.getImageData(0,0,width,height).data;
    $('.image-credit').textContent='Synthetic swatches · load a photo to assess appearance';applySampleLighting();
  }
  function applySampleLighting() {
    if(!originalPixels)return;
    pixels=new Uint8ClampedArray(originalPixels);const kind=$('.sample-light').value;
    for(let i=0;i<pixels.length;i+=4){
      const x=(i/4)%width,y=Math.floor(i/4/width);
      const factor=kind==='dim'?.48:kind==='contrast'?(x>width*.67||y<height*.18?1.55:.68):1;
      for(let c=0;c<3;c++)pixels[i+c]=originalPixels[i+c]*factor*(kind==='warm'?[1.13,1,.86][c]:1);
    }
    src.putImageData(new ImageData(pixels,width,height),0,0);render();
  }
  fallback();
  const sample=new Image();sample.crossOrigin='anonymous';const initialGeneration=imageGeneration;
  sample.onload=()=>{if(imageGeneration!==initialGeneration)return;try{load(sample,'NASA / Eileen Collins · sample, not a Canon reference');}catch{fallback();}};
  sample.onerror=()=>{if(imageGeneration===initialGeneration)fallback();};
  sample.src='https://cdn.jsdelivr.net/gh/scikit-image/scikit-image@v0.19.3/skimage/data/astronaut.png';
  root.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{camera.update({mode:b.dataset.mode});render();});
  $('.iso').onchange=e=>{camera.update({iso:Number(e.target.value)});render();};
  $('.speed').onchange=e=>{camera.update({shutter:Number(e.target.value)});render();};
  $('.wb').onchange=e=>{camera.update({wb:e.target.value});render();};
  $('.adaptive').onchange=e=>{camera.update({adaptive:e.target.checked});render();};
  $('.sample-light').onchange=applySampleLighting;
  $('.recipe').onchange=e=>{camera.update({recipe:e.target.value});render();};
  $('.ev').oninput=e=>{camera.update({ev:Number(e.target.value)/3});render();};
  $('.screen').onclick=e=>{const b=e.currentTarget.getBoundingClientRect();const f=$('.focus');f.style.left=Math.max(10,Math.min(90,(e.clientX-b.left)/b.width*100))+'%';f.style.top=Math.max(15,Math.min(85,(e.clientY-b.top)/b.height*100))+'%';f.classList.add('selected');status('Focus position set · simulated');};
  function compare(){const value=$('.compare').value;source.style.clipPath=`inset(0 ${100-value}% 0 0)`;source.classList.toggle('hidden',!comparison);$('.divider').style.left=value+'%';$('.divider').hidden=!comparison;$('.compare-toggle').textContent='Comparison '+(comparison?'on':'off');$('.compare-toggle').setAttribute('aria-pressed',String(comparison));$('.compare').disabled=!comparison;}
  $('.compare').oninput=compare;$('.compare-toggle').onclick=()=>{comparison=!comparison;compare();};
  const panels=[[$('#digit-options'),$('.options-toggle')],[$('#digit-cameras'),$('.model')],[$('.gallery'),$('.gallery-btn')]];
  let activePanel=null;
  function openPanel(panel) {
    const closing=activePanel && panels.find(([p])=>p===activePanel)?.[1];
    activePanel=panel;
    for(const [p,button] of panels){p.hidden=p!==panel;button.setAttribute('aria-expanded',String(p===panel));}
    $('.scrim').hidden=!panel;
    if(panel) panel.querySelector('.close-panel').focus();
    else closing?.focus();
  }
  for(const [panel,button] of panels) button.onclick=()=>openPanel(activePanel===panel?null:panel);
  root.querySelectorAll('.close-panel').forEach(b=>b.onclick=()=>openPanel(null));
  $('.scrim').onclick=()=>openPanel(null);$('.current').onclick=()=>openPanel(null);
  root.addEventListener('keydown',e=>{if(e.key==='Escape' && activePanel){e.preventDefault();openPanel(null);}});
  function gallery() {
    const list=$('.session-grid');list.replaceChildren();$('.empty').hidden=camera.shots.length>0;
    const retryFocused=document.activeElement===$('.retry-gallery');
    $('.retry-gallery').hidden=!camera.shots.some(s=>s.state==='pending');
    if(retryFocused && $('.retry-gallery').hidden) $('.gallery .close-panel').focus();
    for(const shot of [...camera.shots].reverse()) {
      const fig=document.createElement('figure');fig.className='shot';const img=document.createElement('img');img.src=shot.image;img.alt=`Simulated shot ${shot.id}, ${shot.settings.recipe}`;
      const cap=document.createElement('figcaption');cap.textContent=`#${shot.id} ${shot.settings.recipe} · ${shot.state}`;fig.append(img,cap);list.append(fig);
    }
    if(camera.shots.length){const last=camera.shots.at(-1);const img=document.createElement('img');img.src=last.image;img.alt='Last simulated capture';$('.gallery-btn').replaceChildren(img);}
  }
  function capture(origin='Shutter') {
    try {
      const shot=camera.capture(processed.toDataURL('image/jpeg',.92));const outcome=$('.permission').value;
      status(`${origin} · processing #${shot.id}…`);gallery();
      setTimeout(()=>{camera.complete(shot.id,outcome);gallery();status(shot.state==='saved'?`#${shot.id} auto-saved · simulation only`:`#${shot.id} retained · ${shot.reason}`);},380);
    }catch(e){status(e.message);}
  }
  $('.shutter').onclick=()=>capture();$('.hardware').onclick=()=>capture('Modeled volume event');
  $('.lock').onclick=()=>status('Modeled handoff → G12 ready · real iPhone test required');
  $('.retry-gallery').onclick=()=>$('.retry').click();
  $('.retry').onclick=()=>{for(const s of camera.shots)camera.retry(s.id,$('.permission').value);gallery();const pending=camera.shots.filter(s=>s.state==='pending').length;status(pending?`${pending} still pending · check simulated Photos outcome`:'No pending saves · simulation only');};
  $('input[type=file]').onchange=e=>{
    const file=e.target.files[0];if(!file)return;
    if(file.size>20*1024*1024){status('Choose a sample under 20 MB');return;}
    status('Loading your photo…');
    const generation=++imageGeneration;const reader=new FileReader();reader.onerror=()=>status('Could not read sample');
    reader.onload=()=>{const img=new Image();img.onload=()=>{if(generation!==imageGeneration)return;try{load(img,'Your local test photo · experimental rendering');status('Photo ready · simulated capture');}catch{status('Could not process this sample');}};img.onerror=()=>status('Use a JPEG, PNG, or WebP sample');img.src=reader.result;};reader.readAsDataURL(file);
  };
  if(globalThis.Tweak){const style={accent:'#d7b57a',lcd:false};const tweak=new Tweak({container:$('.phone'),onChange:()=>{root.style.setProperty('--digit-accent',style.accent);root.style.setProperty('--digit-lcd',style.lcd?'1':'0');}});tweak.addColorPicker(style,'accent',{label:'Dial accent'});tweak.addToggle(style,'lcd',{label:'Preview LCD texture'});}
  compare();render();
})();
