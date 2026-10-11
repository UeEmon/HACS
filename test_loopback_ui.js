const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
(async()=>{
  const listeners={}, button={disabled:true}, status={textContent:''};
  const document={addEventListener:(name,fn)=>{if(name==='DOMContentLoaded')fn()},getElementById:id=>id==='loopback'?button:status};
  let calls=0, result={passed:true,tail_number:'5501',selcal_code:'EM-DL',detection:{calls:[{code:'EM-DL',pulse_seconds:[1,1],gap_seconds:.2}],sample_rate:48000,duration_seconds:2.2}};
  let resolve, deferred=false;
  const context={document,window:{addEventListener:(name,fn)=>listeners[name]=fn},URLSearchParams,
    hacsRotation:{assertPeriod:async()=>{}},fetch:async(url,options)=>{
      calls++;
      if(!options)return {blob:async()=>Buffer.from('actual wav')};
      if(deferred)await new Promise(r=>resolve=r);
      assert.equal(options.headers['Content-Type'],'audio/wav');
      return {ok:true,json:async()=>result};
    }};
  vm.runInNewContext(fs.readFileSync('loopback_ui.js','utf8'),context);
  const generated=()=>listeners['hacs-audio-generated']({detail:{url:'blob:audio',tail:'5501',mode:'selcal16',period:'',key:''}});
  generated();assert.equal(button.disabled,false);await button.onclick();
  assert.match(status.textContent,/合格/);assert.equal(calls,2);
  result={...result,passed:false};await button.onclick();assert.match(status.textContent,/不合格/);
  deferred=true;const pending=button.onclick();while(!resolve)await new Promise(r=>setImmediate(r));
  listeners['hacs-audio-invalidated']();resolve();await pending;
  assert.equal(button.disabled,true);assert.match(status.textContent,/生成してから/);
  console.log('Loopback UI: PCM submission, pass/fail display, stale-result suppression verified');
})().catch(error=>{console.error(error);process.exitCode=1});
