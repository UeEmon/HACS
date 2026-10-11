document.addEventListener('DOMContentLoaded', () => {
  const token=document.getElementById('admin-token'), reason=document.getElementById('key-reason');
  const rotate=document.getElementById('key-rotate'), history=document.getElementById('key-history');
  const message=document.getElementById('key-status'), output=document.getElementById('key-events');
  let busy=false;
  async function operate(change) {
    if (busy) return;
    if (!/^[0-9a-fA-F]{64}$/.test(token.value.trim())) {message.textContent='64桁の管理トークンを入力してください。';return;}
    if (change && !window.confirm('新しい共通鍵へ即時切替します。旧鍵の音声は使用できなくなります。共有ストアに接続した受信シミュレータも更新されます。実受信装置や別環境のコード更新は別途必要です。実行しますか？')) return;
    busy=true; rotate.disabled=history.disabled=true;
    try {
      const options={headers:{Authorization:'Bearer '+token.value.trim()}};
      if (change) {
        const current=await hacsRotation.refresh();
        options.method='POST'; options.headers['Content-Type']='application/json';
        options.body=JSON.stringify({action:'rotate',expected_key_id:current.key_id,reason:reason.value});
      }
      const response=await fetch('/api/keys',options), data=await response.json();
      if (!response.ok) throw Error(data.error||'鍵管理操作に失敗しました。');
      if (change) {
        await hacsRotation.refresh(); output.replaceChildren();
        message.textContent='共通鍵を更新しました。鍵識別子: '+data.key_id+'。現在の受信設定コードを確認してください。';
      } else {
        output.replaceChildren();
        for (const item of data.events) {
          const row=document.createElement('p');
          row.textContent='世代 '+item.generation+' / '+item.key_id+' / '+item.updated_utc+' / '+item.reason;
          output.append(row);
        }
        message.textContent='更新履歴を表示しました。日時はUTCです。';
      }
    } catch(error) {message.textContent=error.message;}
    finally {token.value='';busy=false;rotate.disabled=history.disabled=false;}
  }
  rotate.onclick=()=>operate(true); history.onclick=()=>operate(false);
});
