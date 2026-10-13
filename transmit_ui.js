// Transmit through the radio host service. SPDX-License-Identifier: Apache-2.0
// Enabled only for the audio that is currently generated AND passed the internal loopback.
(function(){
  const TERMINAL=['completed','failed','cancelled','rejected','submit_failed'];
  const STATUS={requested:'受付中',accepted:'受付済み（開始待ち）',running:'送信中',completed:'完了（PTT解除済み）',failed:'失敗',
    cancelled:'中止',rejected:'拒否（送信していません）',submit_failed:'ホストへの投入に失敗（送信していません）',unknown:'不明（ホストから結果を取得できません）'};
  const EVENTS={started:'開始',guard_ok:'鍵・期間を照合',audio_prepare:'音声デバイス準備',ptt_on:'PTT ON',audio_start:'音声出力開始',
    audio_complete:'音声出力完了',ptt_off:'PTT OFF',audio_stop:'音声停止',cancel_requested:'中止要求',release_error:'解除処理の異常',finished:'終了'};
  const HOST={not_configured:'未設定',unreachable:'接続できません',unconfigured:'未接続（設定未適用）',idle:'待機中',busy:'送信中'};
  window.hacsTransmitLabels={STATUS,EVENTS,HOST,TERMINAL};
  const state={audio:null,passed:false,host:null,job:null,busy:false,timer:null,hostTimer:null};
  let el={};

  function describeHost(h){
    if(!h)return '確認中…';
    let text=HOST[h.state]||h.state;
    if(h.reachable&&h.profile)text+=' / 方式: '+(h.profile.backend==='host_audio_serial'?'実出力':'ドライラン（実出力なし）')+
      ' / 出力レベル: '+Math.round((h.profile.output_level??.5)*100)+'%';
    if(h.reachable&&h.profile?.backend==='host_audio_serial'&&!h.physical_output_ready)text+=' / ホストで実出力が許可されていません';
    if(h.error)text+=' / '+h.error;
    return text;
  }
  function render(){
    if(!el.button)return;
    const h=state.host, jobActive=state.job&&!TERMINAL.includes(state.job.status)&&state.job.status!=='unknown';
    const ready=!!(state.audio&&state.passed&&h&&h.reachable&&h.state==='idle'&&h.profile&&
      (h.profile.backend!=='host_audio_serial'||h.physical_output_ready));
    el.button.disabled=state.busy||jobActive||!ready;
    el.cancel.disabled=!jobActive;
    el.host.textContent='無線機ホスト: '+describeHost(h);
    if(!state.job&&!state.busy){
      el.status.textContent=!state.audio?'音声を生成し、内部ループバック確認に合格すると送信できます。':
        !state.passed?'内部ループバック確認に合格すると送信できます。':
        !ready?'無線機ホストの準備ができていません（「無線機インターフェース」タブで設定を適用）。':
        '送信できます。送信内容はホストに適用した出力レベルで生成し直します。';
    }
  }
  function showJob(job){
    state.job=job;
    const physical=job.physical_output?'実出力':'ドライラン';
    el.status.textContent='送信 '+(STATUS[job.status]||job.status)+' / 機番号 '+job.tail_number+' → '+job.code+' / '+physical+
      (job.error?'\n'+job.error:'')+'\nジョブID: '+job.job_id+'（相手の受信成功は確認していません）';
    el.events.textContent='';
    for(const e of job.events||[]){
      const li=document.createElement('li');
      li.textContent=(e.elapsed_seconds??'').toString().padStart(6,' ')+'秒  '+(EVENTS[e.event]||e.event)+(e.detail?'：'+e.detail:'');
      el.events.appendChild(li);
    }
    render();
  }
  async function json(url,options){
    const r=await fetch(url,options);let d={};
    try{d=await r.json()}catch{}
    if(!r.ok)throw Error(d.error||('HTTP '+r.status));
    return d;
  }
  async function refreshHost(){
    try{state.host=await json('/api/radio-host')}
    catch(e){state.host={configured:false,reachable:false,state:'unreachable',error:e.message}}
    window.dispatchEvent(new CustomEvent('hacs-radio-host',{detail:state.host}));
    render();
    return state.host;
  }
  async function poll(jobId){
    clearTimeout(state.timer);
    try{
      const job=await json('/api/transmit/'+jobId);
      if(state.job&&state.job.job_id!==jobId)return;
      showJob(job);
      if(TERMINAL.includes(job.status)||job.status==='unknown'){refreshHost();window.dispatchEvent(new CustomEvent('hacs-transmit-finished',{detail:job}));return;}
    }catch(e){el.status.textContent='送信状態を取得できません: '+e.message+'（再試行します）';}
    state.timer=setTimeout(()=>poll(jobId),500);
  }
  async function send(){
    if(el.button.disabled||!state.audio)return;
    const a=state.audio, h=state.host, physical=h?.profile?.backend==='host_audio_serial';
    const message='機番号 '+a.tail+'（'+(a.mode==='selcal32'?'SELCAL 32':'従来16音')+'）を無線機から送信します。'+
      (physical?'\n\n実際に音声出力とPTT操作を行い、電波を発射します。':'\n\nホストはドライラン設定のため、実際の出力は行いません。')+'\nよろしいですか？';
    if(!window.confirm(message))return;
    state.busy=true;state.job=null;el.events.textContent='';el.status.textContent='送信を要求中…';render();
    try{
      await hacsRotation.assertPeriod(a.period,5,a.key);
      const job=await json('/api/transmit',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({tail_number:a.tail,mode:a.mode,period_id:a.period,key_id:a.key,confirm:true})});
      showJob(job);
      if(!TERMINAL.includes(job.status))poll(job.job_id);
    }catch(e){state.job=null;el.status.textContent='送信できませんでした: '+e.message;}
    finally{state.busy=false;render();}
  }
  async function cancel(){
    if(!state.job)return;
    el.cancel.disabled=true;
    try{showJob(await json('/api/transmit/'+state.job.job_id+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}))}
    catch(e){el.status.textContent='中止要求に失敗しました: '+e.message;render();}
  }
  window.hacsRadioHost={refresh:refreshHost,get current(){return state.host}};
  window.addEventListener('hacs-audio-invalidated',()=>{state.audio=null;state.passed=false;render();});
  window.addEventListener('hacs-audio-generated',e=>{state.audio=e.detail;state.passed=false;render();});
  window.addEventListener('hacs-loopback-result',e=>{
    const r=e.detail,a=state.audio;
    state.passed=!!(a&&r.passed&&r.tail_number===a.tail&&(r.mode||a.mode)===a.mode&&(r.period_id||'')===a.period&&(r.key_id||'')===a.key);
    render();
  });
  document.addEventListener('DOMContentLoaded',()=>{
    el={button:document.getElementById('transmit'),cancel:document.getElementById('transmit-cancel'),status:document.getElementById('transmit-status'),
        events:document.getElementById('transmit-events'),host:document.getElementById('transmit-host')};
    if(!el.button)return;
    el.button.onclick=send;el.cancel.onclick=cancel;
    render();refreshHost();
    state.hostTimer=setInterval(()=>{if(!state.job||TERMINAL.includes(state.job.status)||state.job.status==='unknown')refreshHost()},5000);
  });
})();
