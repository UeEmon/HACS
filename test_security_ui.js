const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
(async()=>{const els=Object.fromEntries(['security-cadence','security-token','security-apply','security-status'].map(id=>[id,{value:'',disabled:false,textContent:''}]));let posted=null,events=0;
const context={document:{addEventListener:(_,fn)=>fn(),getElementById:id=>els[id]},window:{confirm:()=>true,dispatchEvent:()=>events++},Event:class{},hacsRotation:{refresh:async()=>({cadence:'off',security_revision:2})},fetch:async(_,o)=>{posted=o;return {ok:true,json:async()=>({cadence:'daily',security_revision:3})};}};
vm.runInNewContext(fs.readFileSync('security_ui.js','utf8'),context);await new Promise(r=>setImmediate(r));
els['security-cadence'].value='daily';els['security-token'].value='ab'.repeat(32);await els['security-apply'].onclick();
assert.equal(JSON.parse(posted.body).cadence,'daily');assert.equal(JSON.parse(posted.body).expected_revision,2);assert.equal(posted.headers.Authorization,'Bearer '+'ab'.repeat(32));assert.equal(els['security-token'].value,'');assert.equal(events,1);assert.equal(els['security-apply'].disabled,false);
console.log('Security UI: authenticated policy request, revision, invalidation and token clearing verified');
})().catch(e=>{console.error(e);process.exitCode=1});
