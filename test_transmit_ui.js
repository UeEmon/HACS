const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
(async()=>{
  const listeners={}, dom={};
  const node=()=>({disabled:false,textContent:'',children:[],appendChild(c){this.children.push(c)},set onclick(f){this._click=f},get onclick(){return this._click}});
  for(const id of ['transmit','transmit-cancel','transmit-status','transmit-events','transmit-host'])dom[id]=node();
  let host={configured:true,reachable:true,state:'idle',physical_output_allowed:false,physical_output_ready:false,
            profile:{backend:'dry_run',output_level:.5,timing:{lead_seconds:.3,tail_seconds:.2,max_ptt_seconds:5}}};
  const posted=[]; let jobStatus='running', confirmAnswer=true, confirmText='';
  const job=s=>({job_id:'11111111-2222-3333-4444-555555555555',status:s,tail_number:'5501',code:'EM-DL',physical_output:false,
                 events:[{event:'ptt_on',elapsed_seconds:.31}],error:null});
  const timers=[];
  const context={
    document:{addEventListener:(n,f)=>{if(n==='DOMContentLoaded')context._ready=f},getElementById:id=>dom[id],createElement:()=>({textContent:''})},
    window:{addEventListener:(n,f)=>listeners[n]=f,dispatchEvent:e=>listeners[e.type]?.(e),confirm:t=>{confirmText=t;return confirmAnswer}},
    CustomEvent:class{constructor(t,o){this.type=t;this.detail=o?.detail}},
    setTimeout:(f)=>{timers.push(f);return timers.length},clearTimeout:()=>{},setInterval:()=>0,
    hacsRotation:{assertPeriod:async()=>{}},
    fetch:async(url,options)=>{
      if(url==='/api/radio-host')return {ok:true,json:async()=>host};
      if(url==='/api/transmit'){posted.push(JSON.parse(options.body));return {ok:true,status:202,json:async()=>job('accepted')}}
      if(url.endsWith('/cancel'))return {ok:true,json:async()=>job('cancelled')};
      if(url.startsWith('/api/transmit/'))return {ok:true,json:async()=>job(jobStatus)};
      throw Error('unexpected '+url);
    }};
  context.window.hacsRotation=context.hacsRotation;
  vm.runInNewContext(fs.readFileSync('transmit_ui.js','utf8'),context);
  context._ready();
  await new Promise(r=>setImmediate(r));
  const btn=dom['transmit'];
  assert.equal(btn.disabled,true,'disabled without audio');
  const audio={url:'blob:x',tail:'5501',mode:'selcal16',period:'',key:''};
  listeners['hacs-audio-generated']({detail:audio});
  assert.equal(btn.disabled,true,'disabled before loopback');
  listeners['hacs-loopback-result']({detail:{passed:true,tail_number:'0001',mode:'selcal16',period_id:'',key_id:''}});
  assert.equal(btn.disabled,true,'loopback result for another tail does not count');
  listeners['hacs-loopback-result']({detail:{passed:false,tail_number:'5501',mode:'selcal16',period_id:'',key_id:''}});
  assert.equal(btn.disabled,true,'failed loopback');
  listeners['hacs-loopback-result']({detail:{passed:true,tail_number:'5501',mode:'selcal16',period_id:null,key_id:null}});
  assert.equal(btn.disabled,false,'enabled after matching loopback pass');
  // Host not ready blocks sending
  host={...host,state:'busy'};await context.window.hacsRadioHost.refresh();assert.equal(btn.disabled,true);
  host={...host,state:'idle',profile:{...host.profile,backend:'host_audio_serial'},physical_output_ready:false};
  await context.window.hacsRadioHost.refresh();assert.equal(btn.disabled,true,'physical profile without permission');
  host={...host,physical_output_ready:true};await context.window.hacsRadioHost.refresh();assert.equal(btn.disabled,false);
  // Declined confirmation sends nothing; physical warning shown
  confirmAnswer=false;await btn.onclick();assert.equal(posted.length,0);assert.match(confirmText,/電波を発射/);
  confirmAnswer=true;await btn.onclick();
  assert.deepEqual(posted[0],{tail_number:'5501',mode:'selcal16',period_id:'',key_id:'',confirm:true});
  assert.equal(btn.disabled,true,'disabled while job active');
  assert.equal(dom['transmit-cancel'].disabled,false);
  await timers.shift()?.();await new Promise(r=>setImmediate(r));
  assert.match(dom['transmit-status'].textContent,/送信中/);
  assert.ok(dom['transmit-events'].children[0].textContent.includes('PTT ON'));
  await dom['transmit-cancel'].onclick();
  assert.match(dom['transmit-status'].textContent,/中止/);
  assert.equal(dom['transmit-cancel'].disabled,true);
  // Invalidating audio disables sending again
  listeners['hacs-audio-invalidated']();assert.equal(btn.disabled,true);
  console.log('Transmit UI: loopback gating, host readiness, confirmation, polling, cancel verified');
})().catch(e=>{console.error(e);process.exitCode=1});
