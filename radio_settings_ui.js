document.addEventListener('DOMContentLoaded',()=>{
  const form=document.getElementById('radio-settings-form'),f=form.elements,message=document.getElementById('radio-settings-status');
  const save=document.getElementById('radio-settings-save'),reload=document.getElementById('radio-settings-load'),download=document.getElementById('radio-settings-export');
  let revision=null,busy=false;

  function controls(value){busy=value;save.disabled=reload.disabled=download.disabled=value;}
  function populate(p){f.output_level.value=Math.round((p.output_level??.5)*100);f.output_level.dispatchEvent(new Event('input'));f.name.value=p.name;f.manufacturer.value=p.radio.manufacturer;f.model.value=p.radio.model;f.backend.value=p.backend;f.device_type.value=typeof p.audio_input.host_output_device==='number'?'id':'name';f.device.value=p.audio_input.host_output_device??'';f.channels.value=p.audio_input.channels;f.port.value=p.ptt.serial_port??'';f.line.value=p.ptt.control_line;f.polarity.value=String(p.ptt.active_high);f.lead.value=p.timing.lead_seconds;f.tail.value=p.timing.tail_seconds;f.maximum.value=p.timing.max_ptt_seconds;}
  async function request(options){const r=await fetch('/api/radio-settings',options),d=await r.json();if(!r.ok)throw Error(d.error||'設定を取得できません。');return d;}
  async function load(){if(busy)return;controls(true);try{const d=await request();revision=d.revision;populate(d.profile);message.textContent='保存設定を読み込みました（世代 '+revision+'）。機器との接続確認は未実施です。';}catch(e){message.textContent=e.message;}finally{controls(false);}}
  form.onsubmit=async e=>{e.preventDefault();if(busy)return;if(revision===null){message.textContent='先に設定を再読込してください。';return;}controls(true);try{
    if(f.device_type.value==='id'&&!/^\d+$/.test(f.device.value.trim()))throw Error('デバイスIDは0以上の整数で指定してください。');
    const profile={profile_version:'HACS-RADIO-v1',name:f.name.value,backend:f.backend.value,output_level:Number(f.output_level.value)/100,radio:{manufacturer:f.manufacturer.value,model:f.model.value},audio_input:{host_output_device:f.device_type.value==='id'?Number(f.device.value):f.device.value,channels:Number(f.channels.value)},ptt:{method:'serial_control_line',serial_port:f.port.value,control_line:f.line.value,active_high:f.polarity.value==='true'},timing:{lead_seconds:Number(f.lead.value),tail_seconds:Number(f.tail.value),max_ptt_seconds:Number(f.maximum.value)}};
    const d=await request({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,profile})});revision=d.revision;message.textContent='設定を保存しました（世代 '+revision+'）。ホストへ適用する場合はJSONを出力してください。';
  }catch(e){message.textContent=e.message;}finally{controls(false);}};
  reload.onclick=()=>{if(window.confirm('未保存の編集を破棄して保存設定を読み込みますか？'))load();};
  download.onclick=async()=>{if(busy)return;controls(true);try{const d=await request();const url=URL.createObjectURL(new Blob([JSON.stringify(d.profile,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='HACS-radio-profile.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message.textContent='保存済み設定を出力しました。未保存の編集は含みません。';}catch(e){message.textContent=e.message;}finally{controls(false);}};
  load();
});
