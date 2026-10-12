(function (root) {
  class CameraSimulation {
    constructor() { this.settings = { model: 'G12', mode: 'Auto', iso: 100, shutter: 125, ev: 0, wb: 'Auto', adaptive: true, recipe: 'Standard' }; this.shots = []; this.sequence = 0; }
    update(patch) {
      const rules = { model: ['G12'], mode: ['Auto', 'Manual'], iso: [80,100,200,400,800,1600,3200], shutter: [15,30,60,125,250,500,1000], wb: ['Auto','Daylight','Cloudy','Tungsten'], adaptive:[true,false], recipe: ['Standard','Neutral','Vivid'] };
      for (const [key,value] of Object.entries(patch)) {
        if(key === 'ev') { if(!Number.isFinite(value) || value < -2 || value > 2) throw Error('Invalid exposure'); }
        else if(!rules[key]?.includes(value)) throw Error('Unsupported '+key);
      }
      this.settings = { ...this.settings, ...patch };
    }
    capture(image) {
      if(!image) throw Error('No image to capture');
      if(this.shots.length >= 6) {
        const index = this.shots.findIndex(shot => shot.state === 'saved');
        if(index < 0) throw Error('Session queue full: retry pending saves first');
        this.shots.splice(index,1);
      }
      const shot = { id: ++this.sequence, settings: Object.freeze({...this.settings}), image, state: 'processing', reason: '' };
      this.shots.push(shot); return shot;
    }
    complete(id,permission) {
      if(!['allowed','denied','failure'].includes(permission)) throw Error('Invalid permission');
      const shot = this.shots.find(s=>s.id===id);
      if(!shot || shot.state === 'saved') return;
      shot.state = permission === 'allowed' ? 'saved' : 'pending';
      shot.reason = permission === 'denied' ? 'Photos permission denied' : permission === 'failure' ? 'Photos write failed' : '';
    }
    retry(id,permission) { const shot=this.shots.find(s=>s.id===id); if(shot?.state==='pending') this.complete(id,permission); }
  }
  function exposureStops(settings) {
    return settings.mode === 'Manual' ? Math.log2((settings.iso/100)*(125/settings.shutter)) : settings.ev;
  }
  const decode=v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;
  const encode=v=>v<=0.0031308?12.92*v:1.055*v**(1/2.4)-0.055;
  function validatePixels(pixels,width,height) {
    if(!Number.isInteger(width) || !Number.isInteger(height) || width<1 || height<1 || pixels.length!==width*height*4) throw Error('Invalid pixel dimensions');
  }
  // Conservative neutral-pixel heuristic. This is NOT ML or illuminant ground truth.
  function analyzeScene(pixels,width,height) {
    validatePixels(pixels,width,height);
    const histogram=new Array(256).fill(0),sum=[0,0,0];let total=0,neutral=0;
    const step=Math.max(1,Math.floor(width*height/4096));
    for(let p=0;p<width*height;p+=step) {
      const i=p*4;if(pixels[i+3]<250)continue;
      const rgb=[pixels[i]/255,pixels[i+1]/255,pixels[i+2]/255];const hi=Math.max(...rgb),lo=Math.min(...rgb);
      const l=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];histogram[Math.round(l*255)]++;total++;
      if(l>.12 && l<.88 && hi>0 && (hi-lo)/hi<.25){for(let c=0;c<3;c++)sum[c]+=decode(rgb[c]);neutral++;}
    }
    function quantile(q){let n=0;for(let i=0;i<256;i++){n+=histogram[i];if(n>=Math.max(1,total*q))return i/255;}return 0;}
    const low=quantile(.1),high=quantile(.9);let whiteBalance=[1,1,1];
    if(neutral>=8 && neutral/Math.max(1,total)>.05 && high-low>.08) {
      const mean=sum.reduce((a,b)=>a+b,0)/3;
      whiteBalance=sum.map(v=>Math.min(1.22,Math.max(.82,mean/Math.max(v,1e-8))));
    }
    return {whiteBalance,neutralFraction:neutral/Math.max(1,total),low,high,
      shadowLift:low<.18?Math.min(.045,(.18-low)*.3):0,
      highlightCompression:high>.82 && high-low>.45?.35:0};
  }
  // Exploratory coefficients, NOT measured Canon processing. Assumes an sRGB input.
  function renderPixels(pixels,settings,width,height) {
    validatePixels(pixels,width,height);
    const output = new Uint8ClampedArray(pixels.length);
    const gain = 2**exposureStops(settings);
    const saturation = {Standard:1.04,Neutral:0.86,Vivid:1.25}[settings.recipe];
    const contrast = {Standard:1.035,Neutral:0.94,Vivid:1.1}[settings.recipe];
    const scene=analyzeScene(pixels,width,height);
    const wb = settings.wb==='Auto'?scene.whiteBalance:{Daylight:[1.025,1,0.985],Cloudy:[1.1,1,0.92],Tungsten:[0.83,0.97,1.2]}[settings.wb];
    for(let i=0;i<pixels.length;i+=4) {
      const rgb=[0,1,2].map(c=>Math.min(1,decode(pixels[i+c]/255)*gain*wb[c]));
      let y=0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];
      if(settings.adaptive && y>0) {
        const mapped=y+scene.shadowLift*Math.sqrt(y)*(1-y)**2-scene.highlightCompression*Math.max(0,y-.6)**2;
        const scale=Math.max(0,mapped)/y;for(let c=0;c<3;c++)rgb[c]*=scale;y=mapped;
      }
      for(let c=0;c<3;c++) {
        const linear=Math.max(0,Math.min(1,y+(rgb[c]-y)*saturation));
        const value=(encode(linear)-0.5)*contrast+0.5;
        output[i+c]=Math.max(0,Math.min(255,value*255));
      }
      output[i+3]=pixels[i+3];
    }
    return output;
  }
  const api = { CameraSimulation, exposureStops, renderPixels, analyzeScene };
  if (typeof module !== 'undefined') module.exports = api;
  else root.DigitSimulation = api;
})(globalThis);
