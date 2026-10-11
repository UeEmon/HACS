document.addEventListener('DOMContentLoaded', () => {
  const select=document.getElementById('preset'), name=document.getElementById('preset-name');
  const tail=document.getElementById('code'), mode=document.getElementById('mode');
  const add=document.getElementById('preset-add'), save=document.getElementById('preset-save');
  const remove=document.getElementById('preset-delete'), message=document.getElementById('preset-status');
  let items=[], busy=false;
  function controls() {
    save.disabled=remove.disabled=busy || !select.value;
    add.disabled=select.disabled=name.disabled=busy;
  }
  async function load(selected='') {
    const response=await fetch('/api/presets'); const data=await response.json();
    if (!response.ok) throw Error(data.error || 'プリセットを取得できませんでした。');
    items=data.presets; select.replaceChildren(new Option('手入力／新規登録',''));
    for (const item of items) select.add(new Option(item.name+' / '+item.tail_number+' / '+(item.mode==='selcal32'?'32音':'16音'),String(item.id)));
    select.value=String(selected); controls();
  }
  select.onchange=()=>{
    const item=items.find(item=>String(item.id)===select.value);
    if (item) {
      if (tail.disabled || mode.disabled) {select.value='';controls();return;}
      tail.value=item.tail_number; mode.value=item.mode; name.value=item.name;
      mode.dispatchEvent(new Event('change')); tail.dispatchEvent(new Event('input'));
      message.textContent='プリセットを選択しました。現在の受信設定コードを確認して音声を生成してください。';
    } else name.value='';
    controls();
  };
  async function mutate(action) {
    if (busy) return;
    if (action==='delete' && !window.confirm('選択したプリセットを削除しますか？')) return;
    const data={action,name:name.value,tail_number:tail.value,mode:mode.value};
    if (action!=='create') data.id=Number(select.value);
    busy=true; controls();
    try {
      const response=await fetch('/api/presets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      const result=await response.json(); if (!response.ok) throw Error(result.error||'登録処理に失敗しました。');
      await load(result.preset ? result.preset.id : '');
      window.dispatchEvent(new Event('hacs-presets-change'));
      if (action==='delete') name.value='';
      message.textContent=action==='delete'?'プリセットを削除しました。':'プリセットを保存しました。';
    } catch(error) {message.textContent=error.message;}
    finally {busy=false;controls();}
  }
  add.onclick=()=>mutate('create'); save.onclick=()=>mutate('update'); remove.onclick=()=>mutate('delete');
  controls(); load().catch(error=>{message.textContent=error.message;});
});

// Each output uses a fresh server snapshot; codes are never stored in presets.
document.addEventListener('DOMContentLoaded', () => {
  const list=document.getElementById('preset-list'), download=document.getElementById('preset-export');
  const status=document.getElementById('preset-export-status'), table=document.getElementById('preset-code-table');
  let busy=false, revision=0;
  function clear() {revision++;table.hidden=true;table.querySelector('tbody').replaceChildren();}
  window.addEventListener('hacs-period-change',()=>{clear();status.textContent='鍵または期間が更新されました。一覧・CSVを再出力してください。';});
  window.addEventListener('hacs-presets-change',()=>{clear();status.textContent='プリセットが変更されました。一覧を再出力してください。';});
  async function output(csv) {
    if (busy) return;
    busy=true;list.disabled=download.disabled=true;clear();status.textContent='一覧を作成中…';
    try {
      const current=await hacsRotation.refresh(), requestRevision=revision;
      const query=new URLSearchParams({period_id:current.period_id||'',key_id:current.key_id||''});
      const response=await fetch((csv?'/api/presets/export.csv?':'/api/presets/codes?')+query);
      if (!response.ok) {const data=await response.json();throw Error(data.error||'一覧を取得できませんでした。');}
      if (csv) {
        const blob=await response.blob();
        await hacsRotation.assertPeriod(response.headers.get('X-HACS-Period')||'',0,response.headers.get('X-HACS-Key-ID')||'');
        if (requestRevision!==revision) throw Error('出力中に設定が変わりました。再出力してください。');
        const url=URL.createObjectURL(blob), link=document.createElement('a');
        link.href=url;link.download='HACS-presets-'+(current.period_id||'fixed')+'.csv';link.click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);status.textContent='CSVを保存しました。期間・鍵識別子は各行に記載しています。';
      } else {
        const data=await response.json();await hacsRotation.assertPeriod(data.period_id||'',0,data.key_id||'');
        if (requestRevision!==revision) throw Error('出力中に設定が変わりました。再出力してください。');
        const body=table.querySelector('tbody');
        for (const item of data.presets) {
          const row=document.createElement('tr');
          for (const value of [item.name,item.tail_number,item.mode==='selcal32'?'SELCAL 32':'従来16音',item.selcal_code]) {
            const cell=document.createElement('td');cell.textContent=value;row.append(cell);
          }
          body.append(row);
        }
        table.hidden=!data.presets.length;
        status.textContent=data.presets.length+'件 / 期間: '+(data.period_id||'固定')+' / 鍵識別子: '+(data.key_id||'なし')+'\n作成日時: '+data.server_time_jst+(data.next_update_jst?'\n次回更新: '+data.next_update_jst:'');
      }
    } catch(error) {clear();status.textContent=error.message;}
    finally {busy=false;list.disabled=download.disabled=false;}
  }
  list.onclick=()=>output(false);download.onclick=()=>output(true);
});
