document.addEventListener('DOMContentLoaded',()=>{
  const button=document.getElementById('loopback'), status=document.getElementById('loopback-status');
  let audio=null, revision=0, busy=false;
  window.addEventListener('hacs-audio-invalidated',()=>{
    audio=null;revision++;button.disabled=true;
    status.textContent='現在の設定で音声を生成してから確認してください。';
  });
  window.addEventListener('hacs-audio-generated',event=>{
    audio=event.detail;revision++;button.disabled=busy;
    status.textContent='未確認。「内部ループバック確認」で生成音声を検査してください。';
  });
  button.onclick=async()=>{
    if (!audio || busy) return;
    const selected=audio, currentRevision=revision;
    busy=true;button.disabled=true;status.textContent='生成WAVを受信処理で解析中…';
    try {
      await hacsRotation.assertPeriod(selected.period,0,selected.key);
      const wav=await fetch(selected.url), blob=await wav.blob();
      const response=await fetch('/api/loopback?'+new URLSearchParams({tail_number:selected.tail,mode:selected.mode,period_id:selected.period,key_id:selected.key}),{
        method:'POST',headers:{'Content-Type':'audio/wav'},body:blob
      });
      const result=await response.json();if (!response.ok) throw Error(result.error||'確認に失敗しました。');
      await hacsRotation.assertPeriod(result.period_id||'',0,result.key_id||'');
      if (currentRevision!==revision) return;
      const detected=result.detection.calls.map(call=>call.code).join(', ')||'未検出';
      status.textContent=(result.passed?'合格：生成音声と受信検出コードが一致しました。':'不合格：生成音声を確認してください。')+
        '\n機番号: '+result.tail_number+' / 期待コード: '+result.selcal_code+' / 検出: '+detected+
        '\n音声: '+result.detection.sample_rate+' Hz / '+result.detection.duration_seconds+'秒'+
        (result.detection.calls.length?'\n信号長: '+result.detection.calls[0].pulse_seconds?.join('秒 / ')+'秒 / 無音間隔: '+result.detection.calls[0].gap_seconds+'秒':'')+
        '\n期間: '+(result.period_id||'固定')+' / 鍵識別子: '+(result.key_id||'なし');
    } catch(error) {if (currentRevision===revision) status.textContent='確認できませんでした: '+error.message;}
    finally {busy=false;button.disabled=!audio;}
  };
});
