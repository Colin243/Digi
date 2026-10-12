const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CameraSimulation, exposureStops, renderPixels, analyzeScene } = require('../prototype/core.js');

test('capture freezes settings while the next shot is adjusted', () => {
  const c = new CameraSimulation(); const shot = c.capture('image-data');
  c.update({ recipe: 'Neutral', iso: 800 });
  assert.equal(shot.settings.recipe, 'Standard'); assert.equal(shot.settings.iso, 100);
  assert.ok(Object.isFrozen(shot.settings)); assert.equal(shot.state, 'processing');
});
test('denied save retains the image and retry completes the same shot once', () => {
  const c = new CameraSimulation(); const shot = c.capture('retained-image');
  c.complete(shot.id, 'denied'); assert.equal(shot.state, 'pending'); assert.equal(shot.image, 'retained-image');
  c.retry(shot.id, 'allowed'); c.retry(shot.id, 'allowed');
  assert.equal(shot.state, 'saved'); assert.equal(c.shots.length, 1);
});
test('save failure never reports success', () => {
  const c = new CameraSimulation(); const shot = c.capture('image');
  c.complete(shot.id, 'failure'); assert.equal(shot.state, 'pending');
  assert.match(shot.reason, /failed/i);
});
test('late callback cannot overwrite a successful save', () => {
  const c = new CameraSimulation(); const shot = c.capture('image');
  c.complete(shot.id, 'allowed'); c.complete(shot.id, 'failure');
  assert.equal(shot.state, 'saved');
});
test('invalid model, settings and permission cannot silently enter state', () => {
  const c = new CameraSimulation();
  assert.throws(() => c.update({model: 'S95'})); assert.throws(() => c.update({iso: 0}));
  assert.throws(() => c.update({iso: NaN})); assert.throws(() => c.update({frontCamera: true}));
  const s = c.capture('image'); assert.throws(() => c.complete(s.id, 'unknown'));
});
test('manual one stop increase doubles linear exposure; auto ignores manual dials', () => {
  const c = new CameraSimulation(); c.update({ mode: 'Manual', iso: 200 });
  assert.equal(exposureStops(c.settings), 1);
  c.update({ iso: 100, shutter: 250 }); assert.equal(exposureStops(c.settings), -1);
  c.update({ mode: 'Auto', ev: 1 }); assert.equal(exposureStops(c.settings), 1);
});
test('manual exposure does not apply auto compensation a second time', () => {
  const c = new CameraSimulation(); c.update({ mode: 'Manual', ev: 2 });
  assert.equal(exposureStops(c.settings), 0);
});
test('rendering leaves source unchanged and preserves alpha and buffer length', () => {
  const input = new Uint8ClampedArray([35,80,130,255,180,130,110,120]); const before = input.slice();
  const output = renderPixels(input, { ...new CameraSimulation().settings, ev: 1 }, 2, 1);
  assert.deepEqual(input, before); assert.equal(output.length, input.length);
  assert.equal(output[3],255); assert.equal(output[7],120); assert.notDeepEqual(output, input);
});
test('positive exposure brightens a neutral midtone without randomness', () => {
  const input = new Uint8ClampedArray([80,80,80,255]); const settings = new CameraSimulation().settings;
  const a = renderPixels(input,settings,1,1); const b = renderPixels(input,{...settings,ev:1},1,1);
  assert.ok(b[0] > a[0]); assert.deepEqual(b,renderPixels(input,{...settings,ev:1},1,1));
});
test('vivid and neutral treatments differ on a saturated patch', () => {
  const input = new Uint8ClampedArray([160,60,60,255]); const s = new CameraSimulation().settings;
  const a=renderPixels(input,{...s,recipe:'Vivid'},1,1); const b=renderPixels(input,{...s,recipe:'Neutral'},1,1);
  assert.ok(a[0]-a[1] > b[0]-b[1]);
});
test('bad pixel geometry is rejected', () => { assert.throws(() => renderPixels(new Uint8ClampedArray(4),new CameraSimulation().settings,2,2)); });
test('session queue is bounded and failed images are never evicted', () => {
  const c = new CameraSimulation();
  for(let i=0;i<6;i++) { const s=c.capture('image'+i); c.complete(s.id,'denied'); }
  assert.throws(()=>c.capture('overflow'),/full/i); assert.equal(c.shots.length,6);
});

function grayRamp(tint=[1,1,1]) {
  const pixels=new Uint8ClampedArray(64*4);
  for(let i=0;i<64;i++){for(let c=0;c<3;c++)pixels[i*4+c]=(40+i*2.5)*tint[c];pixels[i*4+3]=255;}
  return pixels;
}
test('automatic white balance reduces a mild warm cast in a varied neutral scene',()=>{
  const pixels=grayRamp([1.09,1,.93]);const settings=new CameraSimulation().settings;
  const fixed=renderPixels(pixels,{...settings,wb:'Daylight',adaptive:false},64,1);
  const auto=renderPixels(pixels,{...settings,wb:'Auto',adaptive:false},64,1);
  const cast=p=>{let sum=0;for(let i=0;i<p.length;i+=4)sum+=Math.abs(p[i]-p[i+2]);return sum;};
  assert.ok(cast(auto)<cast(fixed));
});
test('scene analysis avoids inferring white balance from a saturated red scene',()=>{
  const pixels=new Uint8ClampedArray(Array.from({length:64},()=>[180,20,20,255]).flat());
  assert.deepEqual(analyzeScene(pixels,64,1).whiteBalance,[1,1,1]);
});
test('scene analysis remains finite for black, clipped white and transparent inputs',()=>{
  for(const value of [0,255]){
    const pixels=new Uint8ClampedArray(Array.from({length:16},()=>[value,value,value,255]).flat());
    const analysis=analyzeScene(pixels,16,1);assert.ok(analysis.whiteBalance.every(Number.isFinite));
    assert.deepEqual(analysis.whiteBalance,[1,1,1]);
  }
  assert.deepEqual(analyzeScene(new Uint8ClampedArray(64),16,1).whiteBalance,[1,1,1]);
});
test('adaptive tone treatment responds to a scene with deep shadows and bright areas',()=>{
  const pixels=new Uint8ClampedArray(Array.from({length:64},(_,i)=>i<32?[30,30,30,255]:[235,235,235,255]).flat());
  const s={...new CameraSimulation().settings,wb:'Auto'};
  const off=renderPixels(pixels,{...s,adaptive:false},64,1);const on=renderPixels(pixels,{...s,adaptive:true},64,1);
  assert.ok(on[0]>off[0]);assert.ok(on[128]<off[128]);
});
test('lighting options are validated and retained in the capture snapshot',()=>{
  const c=new CameraSimulation();c.update({wb:'Auto',adaptive:true});const shot=c.capture('pixels');
  c.update({adaptive:false});assert.equal(shot.settings.adaptive,true);
  assert.throws(()=>c.update({adaptive:'yes'}));
});
