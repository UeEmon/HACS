const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
(async()=>{let invalidations=0,posted;const fields=Object.fromEntries(['name','manufacturer','model','backend','device_type','device','channels','port','line','polarity','lead','tail','maximum','output_level'].map(k=>[k,{value:'',dispatchEvent(){invalidations++;}}]));
const ids={'radio-settings-form':{elements:fields}};for(const id of ['radio-settings-status','radio-settings-save','radio-settings-load','radio-settings-export'])ids[id]={disabled:false,textContent:''};
const profile={name:'Test',backend:'host_audio_serial',radio:{manufacturer:'Test',model:'A'},audio_input:{host_output_device:3,channels:2},ptt:{serial_port:'COM3',control_line:'rts',active_high:true},timing:{lead_seconds:.3,tail_seconds:.2,max_ptt_seconds:5},output_level:.25};
const context={document:{addEventListener:(_,fn)=>fn(),getElementById:id=>ids[id]},Event:class{},window:{confirm:()=>true},fetch:async(_,options)=>{if(options)posted=JSON.parse(options.body);return{ok:true,json:async()=>({revision:1,profile})};}};
vm.runInNewContext(fs.readFileSync('radio_settings_ui.js','utf8'),context);await new Promise(r=>setImmediate(r));
assert.equal(fields.output_level.value,25);assert.equal(invalidations,1);for(const field of Object.values(fields))field.value=String(field.value);fields.output_level.value='30';await ids['radio-settings-form'].onsubmit({preventDefault(){}});assert.equal(posted.profile.output_level,.3);assert.equal(posted.profile.audio_input.host_output_device,3);assert.equal(posted.revision,1);
console.log('Radio settings UI: shared level initialization/invalidation and profile serialization verified');
})().catch(e=>{console.error(e);process.exitCode=1});
