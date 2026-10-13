// Radio host connection panel and server-side transmit history. SPDX-License-Identifier: Apache-2.0
document.addEventListener('DOMContentLoaded',()=>{
  const $=id=>document.getElementById(id);
  const stateEl=$('radio-host-state'), apply=$('radio-host-apply'), release=$('radio-host-release'), devicesBtn=$('radio-host-devices'),
        message=$('radio-host-message'), list=$('radio-host-device-list'), historyBtn=$('transmit-history-load'),
        rows=$('transmit-history-rows'), historyStatus=$('transmit-history-status');
  if(!stateEl)return;
  const labels=()=>window.hacsTransmitLabels||{HOST:{},STATUS:{}};
  let busy=false;
  function show(h){
    const L=labels();
    if(!h){stateEl.textContent='確認中…';return;}
    const lines=['状態: '+(L.HOST[h.state]||h.state)];
    if(h.reachable){
      lines.push('実出力の許可: '+(h.physical_output_allowed?'あり（--allow-physical-output）':'なし（ドライランのみ）'));
      if(h.profile){
        const p=h.profile;
        lines.push('適用中の設定: '+(p.name||'')+' / '+(p.backend==='host_audio_serial'?'実出力':'ドライラン')+
          ' / 音声: '+(p.audio_device??'—')+' / PTT: '+(p.serial_port||'—')+' '+(p.control_line||'').toUpperCase()+
          ' / 前待ち'+p.timing.lead_seconds+'秒・後待ち'+p.timing.tail_seconds+'秒・上限'+p.timing.max_ptt_seconds+'秒');
        lines.push('機器確認: '+(p.checked_utc||'—')+'（UTC。ポートは開かず存在のみ確認）');
      }
    } else if(h.error) lines.push(h.error);
    stateEl.textContent=lines.join('\n');
    const usable=h.reachable&&h.state!=='busy';
    apply.disabled=busy||!usable; release.disabled=busy||!usable||!h.profile; devicesBtn.disabled=busy||!h.reachable;
  }
  window.addEventListener('hacs-radio-host',e=>show(e.detail));
  async function post(action){
    busy=true;show(window.hacsRadioHost?.current);
    message.textContent=action==='apply'?'保存済みの無線機設定をホストへ適用中…':'ホストの設定を解除中…';
    try{
      const r=await fetch('/api/radio-host/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
      const d=await r.json().catch(()=>({}));
      if(!r.ok)throw Error(d.error||('HTTP '+r.status));
      message.textContent=action==='apply'?'適用しました（機器の存在を確認。PTTは操作していません）。':'設定を解除しました。';
    }catch(e){message.textContent=(action==='apply'?'適用できませんでした: ':'解除できませんでした: ')+e.message;}
    finally{busy=false;await window.hacsRadioHost?.refresh();}
  }
  apply.onclick=()=>post('apply');
  release.onclick=()=>post('release');
  devicesBtn.onclick=async()=>{
    list.textContent='';message.textContent='ホストの機器を取得中…';
    try{
      const r=await fetch('/api/radio-host/devices'),d=await r.json();
      if(!r.ok)throw Error(d.error||'取得できません。');
      const add=t=>{const li=document.createElement('li');li.textContent=t;list.appendChild(li);};
      if(d.audio.available)d.audio.devices.forEach(x=>add('音声 ID '+x.id+'：'+x.name+'（出力'+x.output_channels+'ch'+(x.host_api?'・'+x.host_api:'')+'）'));
      else add('音声機器を取得できません：'+(d.audio.reason||''));
      if(d.serial.available)(d.serial.ports.length?d.serial.ports:[{device:'（なし）'}]).forEach(x=>add('シリアル：'+x.device+(x.description?'（'+x.description+'）':'')));
      else add('シリアルポートを取得できません：'+(d.serial.reason||''));
      message.textContent='ホストの機器一覧です。設定欄にはIDまたは名前・ポートをそのまま入力してください。';
    }catch(e){message.textContent='機器一覧を取得できません: '+e.message;}
  };
  async function loadHistory(){
    historyStatus.textContent='取得中…';rows.textContent='';
    try{
      const r=await fetch('/api/transmit/history'),d=await r.json();
      if(!r.ok)throw Error(d.error||'取得できません。');
      const L=labels();
      for(const rec of d.records){
        const tr=document.createElement('tr');
        for(const v of [rec.created_utc,rec.tail_number,rec.code+' / '+(rec.mode==='selcal32'?'32音':'16音'),
                        rec.physical_output?'実出力':'ドライラン',(L.STATUS[rec.status]||rec.status)+(rec.error?'：'+rec.error:'')]){
          const td=document.createElement('td');td.textContent=v;tr.appendChild(td);
        }
        rows.appendChild(tr);
      }
      historyStatus.textContent=d.records.length+'件（新しい順、サーバ保存、UTC）。相手の受信成功は記録していません。';
    }catch(e){historyStatus.textContent='送信履歴を取得できません: '+e.message;}
  }
  historyBtn.onclick=loadHistory;
  window.addEventListener('hacs-transmit-finished',()=>{if(rows.childElementCount)loadHistory();});
  show(window.hacsRadioHost?.current);
});
