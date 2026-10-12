document.addEventListener('DOMContentLoaded',()=>{
  const mode=document.getElementById('security-cadence'), token=document.getElementById('security-token'), button=document.getElementById('security-apply'), status=document.getElementById('security-status');
  let revision=null,busy=false,dirty=false;
  mode.onchange=()=>{dirty=true;};
  async function load(){try{const current=await hacsRotation.refresh();revision=current.security_revision||0;if(!dirty)mode.value=current.cadence;}catch(e){status.textContent=e.message;}}
  load();
  button.onclick=async()=>{
    if(busy)return;
    if(!/^[0-9a-fA-F]{64}$/.test(token.value.trim())){status.textContent='64桁の管理トークンを入力してください。';return;}
    if(revision===null){await load();if(revision===null)return;}
    if(!window.confirm('秘匿設定を変更します。生成済み音声は無効になります。受信側の設定コードも確認してください。'))return;
    busy=true;button.disabled=mode.disabled=true;
    try{const response=await fetch('/api/security',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token.value.trim()},body:JSON.stringify({cadence:mode.value,expected_revision:revision})});const data=await response.json();if(!response.ok)throw Error(data.error||'変更できませんでした。');
      window.dispatchEvent(new Event('hacs-period-change'));dirty=false;await load();status.textContent='秘匿設定を適用しました。現在の設定で音声を再生成してください。';
    }catch(e){status.textContent=e.message;await load();}
    finally{token.value='';busy=false;button.disabled=mode.disabled=false;}
  };
});
