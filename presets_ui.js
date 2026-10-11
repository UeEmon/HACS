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
      if (action==='delete') name.value='';
      message.textContent=action==='delete'?'プリセットを削除しました。':'プリセットを保存しました。';
    } catch(error) {message.textContent=error.message;}
    finally {busy=false;controls();}
  }
  add.onclick=()=>mutate('create'); save.onclick=()=>mutate('update'); remove.onclick=()=>mutate('delete');
  controls(); load().catch(error=>{message.textContent=error.message;});
});
