// Pure VM/DOM fixtures: no browser, native input, external requests or real keys.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const web=process.env.XH_VOICE_WEB||path.join(__dirname,'../web'),win=process.env.XH_VOICE_PLATFORM==='windows';
class Element{
 constructor(id){this.id=id;this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.type='';this.textContent='';this.listeners={};this.attrs={};this.classList={toggle(){}};}
 addEventListener(name,fn){this.listeners[name]=fn;}
 setAttribute(name,value){this.attrs[name]=value;}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
(async()=>{
 const ids=['voice-english-form','english-enabled','english-endpoint','english-model','english-key','english-status','english-save','english-test','english-record-shortcut','english-eye','english-api-details','english-test-result','english-shortcut-dialog','english-shortcut-cancel'];
 const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)])),events={},docEvents={},calls=[],nativeCalls=[],errors=[];let checkCount=0;
 const check=(v,message)=>{assert.ok(v,message);checkCount++;},flush=()=>new Promise(resolve=>setImmediate(resolve));
 let config={enabled:true,endpoint:'https://api.example.invalid/v1/chat/completions',model:'synthetic-model',shortcut:{keyCode:win?163:54,modifiers:0,label:win?'右 Ctrl':'右 Command'},credential_saved:true,revision:'fixture-r1',saved_at:'2026-11-02T08:00:00Z'},finishTest;
 const document={hidden:false,getElementById:id=>elements[id],addEventListener:(k,fn)=>docEvents[k]=fn};
 const context={document,window:{addEventListener:(k,fn)=>events[k]=fn},Date,JSON,Object,Promise,setTimeout:()=>1,setInterval:()=>1,clearInterval(){},
  localStorage:new Proxy({},{get(){throw Error('Secrets must not be cached')}}),hasNative:()=>true,
  native:async(action,value)=>{nativeCalls.push({action,value});return{};},
  api:async(route,body)=>{calls.push({route,body});if(route==='translation'){if(body){config={...config,...body,credential_saved:true,revision:'fixture-r2'};delete config.credential;}return structuredClone(config);}if(route==='translation-credential')return{credential:'synthetic-VM-key'};if(route==='translation-test')return new Promise(resolve=>finishTest=resolve);throw Error('Unexpected route');},
  safe:fn=>Promise.resolve().then(fn).catch(e=>errors.push(e.message)),modifierLabels:win?{ControlRight:'右 Ctrl',ControlLeft:'左 Ctrl'}:{MetaRight:'右 Command',MetaLeft:'左 Command'},keyMap:win?{ControlRight:163,ControlLeft:162,KeyT:84}:{MetaRight:54,MetaLeft:55,KeyT:17}};
 vm.runInNewContext(fs.readFileSync(path.join(web,'voice-english.js'),'utf8'),context);
 await flush();check(calls.length===1&&calls[0].route==='translation','page load only reads nonsecret configuration');
 check(elements['english-key'].value===''&&elements['english-key'].type==='password','saved key is masked without reading vault');
 check(elements['english-key'].placeholder.includes('已保存')&&elements['english-model'].value==='synthetic-model','saved model and credential presence are visible');
 check(!elements['english-test'].disabled,'saved valid profile can be tested manually');
 await elements['english-eye'].onclick();check(elements['english-key'].type==='text'&&elements['english-key'].value==='synthetic-VM-key','explicit eye reads saved token');
 check(calls.find(c=>c.route==='translation-credential').body.reveal===true,'reveal is explicitly scoped');
 await elements['english-eye'].onclick();elements['english-model'].value='changed-model';elements['voice-english-form'].listeners.input({target:elements['english-model']});await elements['english-eye'].onclick();check(elements['english-key'].type==='text'&&elements['english-key'].value==='synthetic-VM-key','editing model does not disable explicit key reveal');
 document.hidden=true;docEvents.visibilitychange();check(elements['english-key'].type==='password'&&elements['english-key'].value==='','leaving page hides and clears revealed credential');document.hidden=false;
 elements['english-key'].value='synthetic-new-key';elements['voice-english-form'].listeners.input({target:elements['english-key']});
 check(elements['english-test'].disabled&&elements['english-status'].textContent.includes('未保存'),'dirty profile cannot accidentally test old key');
 elements['voice-english-form'].onsubmit({preventDefault(){}});await flush();
 check(calls.filter(c=>c.route==='translation'&&c.body).length===1,'one explicit save');
 check(nativeCalls.some(c=>c.action==='validateEnglishShortcut'),'finish key conflicts are validated before save');
 check(elements['english-key'].value===''&&elements['english-key'].type==='password','successful save clears the entered key');
 check(elements['english-status'].textContent.includes('已保存')&&!elements['english-test'].disabled,'save feedback and test affordance restore');
 const running=elements['english-test'].onclick();await flush();check(elements['english-test-result'].textContent.includes('正在翻译')&&elements['english-test'].disabled,'test has immediate timed progress and prevents duplicates');
 finishTest({ok:true,current:true,text:'Meet tomorrow at ten.',milliseconds:321});await running;
 check(elements['english-test-result'].textContent.includes('0.32 秒')&&elements['english-test-result'].textContent.includes('Meet tomorrow'),'manual timing and translated sample appear');
 await elements['english-record-shortcut'].onclick();check(elements['english-shortcut-dialog'].open&&nativeCalls.some(c=>c.action==='beginShortcut'),'shortcut editing is a dialog and suspends activation');
 const key=code=>({code,preventDefault(){},stopPropagation(){},repeat:false});events.keydown(key(win?'ControlLeft':'MetaLeft'));events.keyup(key(win?'ControlLeft':'MetaLeft'));await flush();
 check(elements['english-record-shortcut'].textContent===(win?'左 Ctrl':'左 Command')&&!elements['english-shortcut-dialog'].open,'a replacement finish key is visible and dialog closes');
 check(nativeCalls.some(c=>c.action==='cancelShortcut')&&!nativeCalls.some(c=>c.action==='shortcut'),'editing English key does not replace voice key');
 events['xiaoha-native-state']({detail:{recording:true}});check(elements['english-save'].disabled&&elements['english-record-shortcut'].disabled,'configuration changes disabled during recording');
 check(errors.length===0,'no VM errors');
 const html=fs.readFileSync(path.join(web,'workbench.html'),'utf8');for(const id of ids)check((html.match(new RegExp('id="'+id+'"','g'))||[]).length===1,'one actual HTML element '+id);
 console.log(JSON.stringify({passed:true,checks:checkCount,realNetwork:false,nativeKeysPosted:false,realVaultUsed:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
