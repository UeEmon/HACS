// Unit test of epoch/key guards; does not drive a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

(async () => {
  for (const filename of ['index.html','receiver.html']) {
    const html=fs.readFileSync(filename,'utf8');
    for (const match of html.matchAll(/<script[^>]*\bsrc="([^"]+)"[^>]*>([\s\S]*?)<\/script>/g)) {
      assert.equal(match[2].trim(),'','外部script内の処理はブラウザが実行しない');
      assert.ok(fs.existsSync(match[1].replace(/^\//,'')));
    }
  }
  let metadata = {rotation_enabled:true,cadence:'daily',period_id:'D-2026-10-12',
    key_id:'first',seconds_until_update:3600,next_update_jst:'2026-10-13T00:00:00+09:00'};
  const events=[], panel={textContent:''};
  const context={
    document:{getElementById:()=>panel,addEventListener:()=>{}},
    window:{dispatchEvent:event=>events.push(event.type)},
    Event:class {constructor(type){this.type=type;}},
    setTimeout:()=>1,clearTimeout:()=>{},
    fetch:async()=>({ok:true,json:async()=>({...metadata})})
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('rotation_ui.js','utf8'),context);
  const rotation=context.window.hacsRotation;
  await rotation.refresh();
  await rotation.assertPeriod('D-2026-10-12',2.2,'first');
  metadata={...metadata,key_id:'replacement'};
  await assert.rejects(rotation.assertPeriod('D-2026-10-12',2.2,'first'));
  await rotation.assertPeriod('D-2026-10-12',2.2,'replacement');
  metadata={...metadata,period_id:'D-2026-10-13'};
  await assert.rejects(rotation.assertPeriod('D-2026-10-12',0,'replacement'));
  metadata={...metadata,seconds_until_update:1};
  await assert.rejects(rotation.assertPeriod('D-2026-10-13',2.2,'replacement'));
  assert.ok(events.length>=3);
  metadata={rotation_enabled:false,cadence:'off',period_id:null,key_id:null,seconds_until_update:null};
  await rotation.assertPeriod('',2.2,'');
  console.log('画面側の日付切替・鍵切替・更新直前の再生拒否・鍵なし互換を確認');
})().catch(error=>{console.error(error);process.exitCode=1;});
