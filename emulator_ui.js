'use strict';
const el=id=>document.getElementById(id);
let wav=null,url=null,busy=false,initialized=false,role=null;
async function api(path,options){const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw Error(data.error||'通信エラー');return data;}
function selectWave(blob,label){wav=blob;if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);el('audio').src=url;el('waveinfo').textContent=label;el('send').disabled=busy;}
async function poll(){try{const s=await api('/api/status');role=s.role;el('title').textContent=role==='radio'?'HACS 無線機エミュレータ':'HACS 航空機受信装置エミュレータ';el(role).hidden=false;
el('state').textContent='状態: '+s.state+' / 模擬PTT: '+(s.ptt?'ON':'OFF');
el('code').textContent=role==='aircraft'?'受信設定コード: '+s.current.selcal_code:'';
el('epoch').textContent='期間: '+(s.current.period_id||'固定')+' / 鍵識別子: '+(s.current.key_id||'なし');
if(!initialized){for(const [k,v]of Object.entries(s.config))el('config').elements[k].value=v;initialized=true;}
const last=s.last, detection=last?.aircraft||last;
const labels={alert:'自機呼び出しを検出',other_station:'他機の呼び出しを検出',not_detected:'呼び出し信号を検出できませんでした',delivery_failed:'航空機への転送に失敗'};
el('result').textContent=(s.last_stale?'旧期間・旧鍵の結果: ':'')+(labels[detection?.status]||'受信結果なし');
el('detail').textContent=last?JSON.stringify(last,null,2):'';el('events').textContent=s.events.map(e=>new Date(e.time*1000).toLocaleTimeString()+' '+e.state+' PTT '+(e.ptt?'ON':'OFF')).join('\n');
}catch(e){el('state').textContent='接続を確認してください: '+e.message;}finally{setTimeout(poll,1000);}}
el('config').onsubmit=async e=>{e.preventDefault();try{await api('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});el('message').textContent='受信設定を反映しました。';}catch(e){el('message').textContent=e.message;}};
el('generate').onsubmit=async e=>{e.preventDefault();try{const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});if(!r.ok)throw Error((await r.json()).error);selectWave(await r.blob(),'生成した試験音声を選択中');}catch(e){el('message').textContent=e.message;}};
el('file').onchange=()=>{if(el('file').files[0])selectWave(el('file').files[0],el('file').files[0].name);};
el('send').onclick=async()=>{if(!wav||busy)return;busy=true;el('send').disabled=true;el('message').textContent='模擬送信中…';try{await api('/api/transmit',{method:'POST',headers:{'Content-Type':'audio/wav'},body:wav});el('message').textContent='転送完了。受信判定を確認してください。';}catch(e){el('message').textContent=e.message;}finally{busy=false;el('send').disabled=!wav;}};
poll();
