const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{constructor(){this.attrs={};this.children=[];this.hidden=false;}setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k];}focus(){this.focused=true;}replaceChildren(){this.children=[];}append(x){this.children.push(x);}}
const ids={}, listeners={},storage={};
const tabs=['transmit','connection','presets','security','history'].map((name,i)=>{const t=new Element();t.setAttribute('aria-controls','panel-'+name);ids['panel-'+name]=new Element();ids['panel-'+name].hidden=i!==0;return t;});
for(const id of ['activity-rows','activity-status','activity-clear','activity-export'])ids[id]=new Element();
const context={document:{addEventListener:(_,fn)=>fn(),querySelectorAll:()=>tabs,getElementById:id=>ids[id],createElement:()=>new Element()},window:{addEventListener:(n,fn)=>listeners[n]=fn,confirm:()=>true},localStorage:{getItem:k=>storage[k],setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]},Date,JSON,URL,Blob,setTimeout};
vm.runInNewContext(fs.readFileSync('tabs_ui.js','utf8'),context);
tabs[3].onclick();assert.equal(ids['panel-security'].hidden,false);assert.equal(ids['panel-transmit'].hidden,true);assert.equal(tabs[3].attrs['aria-selected'],'true');
tabs[3].onkeydown({key:'ArrowRight',preventDefault(){}});assert.equal(ids['panel-history'].hidden,false);assert.equal(tabs[4].focused,true);
listeners['hacs-audio-generated']({detail:{tail:'0001',mode:'selcal16'}});assert.equal(ids['activity-rows'].children.length,1);assert.equal(JSON.parse(storage['hacs.activity.v1'])[0].tail,'0001');
ids['activity-clear'].onclick();assert.equal(ids['activity-rows'].children.length,0);assert.equal(storage['hacs.activity.v1'],undefined);
console.log('Tabs: selection, keyboard navigation, history persistence and deletion verified');
