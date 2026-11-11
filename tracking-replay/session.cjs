/* Session state is shared by the replay UI and deterministic Node regressions. */
const SubjectTracker=typeof module!=='undefined'?require('./tracker.cjs').Tracker:window.Tracker;
class ReplaySession {
  constructor(source){this.source={...source};this.tracker=new SubjectTracker();this.reset();}
  reset(){this.tracker.reset();this.time=null;this.events=[];this.frames=[];}
  result(){return this.tracker.result();}
  record(seconds,event){const result=this.result();this.events.push({seconds,event,...result});return result;}
  select(frame,box,seconds){
    this.tracker.select(frame,box);this.time=seconds;return this.record(seconds,'selection');
  }
  discontinuity(seconds){
    this.time=seconds;
    if(this.result().state==='tracking'){
      this.tracker.lose('Replay discontinuity — reselect');this.record(seconds,'lost');
    }
    return this.result();
  }
  advance(frame,seconds){
    if(this.time!==null&&(seconds<this.time||seconds-this.time>.300001))this.discontinuity(seconds);
    const before=this.result().state;
    const result=this.tracker.update(frame);this.time=seconds;
    if(result.state!==before)this.record(seconds,result.state);
    this.frames.push({seconds,...result});return result;
  }
  report(){return JSON.parse(JSON.stringify({version:1,source:this.source,algorithm:'fixed-scale RGB template; experimental, no identity recognition',events:this.events,frames:this.frames}));}
}
if(typeof module!=='undefined')module.exports={ReplaySession};
if(typeof window!=='undefined')window.ReplaySession=ReplaySession;
