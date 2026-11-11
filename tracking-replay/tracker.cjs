/* Shared by browser replay and Node regressions. No model or face data. */
class Tracker {
  constructor(){this.reset();}

  validFrame(frame){
    return frame && Number.isInteger(frame.width) && frame.width>0 &&
      Number.isInteger(frame.height) && frame.height>0 &&
      frame.data instanceof Uint8ClampedArray && frame.data.length===frame.width*frame.height*4;
  }

  reset(){
    this.size=null;this.state='unselected';this.box=null;this.template=null;this.reason='Select a subject';
  }

  select(frame,box){
    if(!this.validFrame(frame))throw Error('Invalid RGBA frame');
    const {x,y,w,h}=box;
    if(![x,y,w,h].every(Number.isFinite)||w<6||h<6||x<0||y<0||x+w>frame.width||y+h>frame.height)
      throw Error('Select a box inside the frame, at least 6 × 6 pixels');
    this.size=[frame.width,frame.height];this.box={x,y,w,h};this.template=this.sample(frame,box);
    this.state='tracking';this.reason='Selected subject';
  }

  sample(frame,box){
    const values=[];
    for(let j=0;j<12;j++)for(let i=0;i<8;i++){
      const x=Math.min(frame.width-1,Math.floor(box.x+(i+.5)*box.w/8));
      const y=Math.min(frame.height-1,Math.floor(box.y+(j+.5)*box.h/12));
      const p=(y*frame.width+x)*4;
      values.push(frame.data[p],frame.data[p+1],frame.data[p+2]);
    }
    return values;
  }

  error(frame,box){
    // A qualifying match is <= .035, and a rival is within .05 of it.
    // Stop sampling candidates too different to affect either decision.
    let sum=0,n=0;
    for(let j=0;j<12;j++)for(let i=0;i<8;i++){
      const x=Math.min(frame.width-1,Math.floor(box.x+(i+.5)*box.w/8));
      const y=Math.min(frame.height-1,Math.floor(box.y+(j+.5)*box.h/12));
      const p=(y*frame.width+x)*4;
      for(let c=0;c<3;c++)sum+=Math.abs(frame.data[p+c]-this.template[n++]);
      if(sum>.085*this.template.length*255)return Infinity;
    }
    return sum/(this.template.length*255);
  }

  lose(reason){this.state='lost';this.box=null;this.reason=reason;return this.result();}
  result(){return {state:this.state,box:this.box?{...this.box}:null,reason:this.reason};}

  update(frame){
    if(this.state!=='tracking')return this.result();
    if(!this.validFrame(frame))return this.lose('Invalid frame — reselect');
    if(frame.width!==this.size[0]||frame.height!==this.size[1])
      return this.lose('Frame dimensions changed — reselect');
    const previous=this.box,radius=Math.max(24,previous.w),candidates=[];
    for(let y=Math.max(0,Math.floor(previous.y-radius));y<=Math.min(frame.height-previous.h,previous.y+radius);y++)
      for(let x=Math.max(0,Math.floor(previous.x-radius));x<=Math.min(frame.width-previous.w,previous.x+radius);x++){
        const box={...previous,x,y},error=this.error(frame,box);
        if(Number.isFinite(error))candidates.push({box,error});
      }
    candidates.sort((a,b)=>a.error-b.error);
    const best=candidates[0];
    if(!best||best.error>.035)return this.lose('Appearance changed or subject occluded — reselect');
    const rival=candidates.find(c=>Math.abs(c.box.x-best.box.x)>=previous.w*.75||Math.abs(c.box.y-best.box.y)>=previous.h*.75);
    if(rival&&rival.error-best.error<.05)return this.lose('Ambiguous subjects — reselect');
    // Never adapt the original template: doing so can absorb an occluder.
    this.box=best.box;this.reason='Appearance match (experimental)';return this.result();
  }
}
if(typeof module!=='undefined')module.exports={Tracker};
if(typeof window!=='undefined')window.Tracker=Tracker;
