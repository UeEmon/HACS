document.addEventListener('DOMContentLoaded',()=>{
  const tabs=Array.from(document.querySelectorAll('[role="tab"]'));
  function activate(tab,focus=false){for(const item of tabs){const selected=item===tab;item.setAttribute('aria-selected',String(selected));item.tabIndex=selected?0:-1;document.getElementById(item.getAttribute('aria-controls')).hidden=!selected;}if(focus)tab.focus();}
  for(const [i,tab]of tabs.entries()){
    tab.onclick=()=>activate(tab);
    tab.onkeydown=e=>{let next;if(e.key==='ArrowRight')next=(i+1)%tabs.length;if(e.key==='ArrowLeft')next=(i+tabs.length-1)%tabs.length;if(e.key==='Home')next=0;if(e.key==='End')next=tabs.length-1;if(next!==undefined){e.preventDefault();activate(tabs[next],true);}};
  }
  const key='hacs.activity.v1',rows=document.getElementById('activity-rows'),status=document.getElementById('activity-status');
  let records=[];
  try{const saved=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(saved))records=saved.filter(x=>x&&typeof x==='object').slice(0,200);}catch{status.textContent='保存済み履歴を読み込めませんでした。';}
  function render(){rows.replaceChildren();for(const item of records){const row=document.createElement('tr');for(const value of [item.time,item.action,item.tail,item.result]){const cell=document.createElement('td');cell.textContent=value||'—';row.append(cell);}rows.append(row);}}
  function add(action,tail,result){records.unshift({time:new Date().toISOString(),action,tail,result});records=records.slice(0,200);try{localStorage.setItem(key,JSON.stringify(records));}catch{status.textContent='履歴の保存に失敗しました。この画面内でのみ保持します。';}render();}
  window.addEventListener('hacs-audio-generated',e=>add('音声生成',e.detail.tail,e.detail.mode));
  window.addEventListener('hacs-loopback-result',e=>add('内部ループバック',e.detail.tail_number,e.detail.mode+' / '+(e.detail.passed?'合格':'不合格')));
  document.getElementById('activity-export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(records,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='HACS-activity.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  document.getElementById('activity-clear').onclick=()=>{if(!window.confirm('このブラウザの操作履歴を削除しますか？'))return;try{localStorage.removeItem(key);records=[];render();status.textContent='操作履歴を削除しました。';}catch{status.textContent='履歴を削除できませんでした。';}};
  render();
});
