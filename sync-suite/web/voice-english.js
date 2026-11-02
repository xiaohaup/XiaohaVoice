'use strict';
// Independent translation config. Never cache API keys in localStorage or logs.
(()=>{
 const $=id=>document.getElementById(id),form=$('voice-english-form');if(!form)return;
 let config=null,shortcut={keyCode:54,modifiers:0,label:'右 Command'},dirty=false,busy=false,visible=false,edited=false,recording=false,nativeRecording=false,candidate=null,modifier=null,started=0,clock;
 const eyeMarkup='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
 const note=(text,error=false)=>{const n=$('english-status');n.textContent=text;n.classList.toggle('error-text',error);};
 const value=()=>({enabled:$('english-enabled').checked,endpoint:$('english-endpoint').value.trim(),model:$('english-model').value.trim(),credential:edited?$('english-key').value:'',shortcut});
 function controls(){
  $('english-save').disabled=busy||nativeRecording;$('english-test').disabled=busy||dirty||!config?.credential_saved||!config?.endpoint||!config?.model||nativeRecording;
  $('english-record-shortcut').disabled=busy||nativeRecording;$('english-eye').disabled=busy||!edited&&!config?.credential_saved;
 }
 function hideKey(){if(!edited)$('english-key').value='';$('english-key').type='password';visible=false;$('english-eye').innerHTML=eyeMarkup;$('english-eye').setAttribute('aria-label','显示翻译 API Key');}
 function changed(){dirty=true;note('有未保存的修改');controls();}
 function apply(v){config=v;shortcut=v.shortcut;edited=false;dirty=false;hideKey();$('english-enabled').checked=v.enabled;$('english-endpoint').value=v.endpoint;$('english-model').value=v.model;$('english-key').placeholder=v.credential_saved?'已保存 · 留空继续使用':'填写此翻译服务的 API Key';$('english-record-shortcut').textContent=shortcut.label;$('english-api-details').open=!v.credential_saved;const time=v.saved_at?new Date(v.saved_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):'';note(time?'已保存 '+time+(v.enabled?' · 英文输出已开启':' · 英文输出已关闭'):'未配置 · 原文输入正常使用');renderTest(v.last_test);controls();}
 function renderTest(v){const n=$('english-test-result');n.hidden=!v;if(!v){n.textContent='';return;}n.textContent=v.ok?'连通 · '+(v.milliseconds/1000).toFixed(2)+' 秒 · '+v.text:'未通过 · '+(v.detail||'请检查配置');n.classList.toggle('error-text',!v.ok);}
 async function load(){if(dirty||busy)return;try{apply(await api('translation'));}catch(e){note(e.message,true);}}
 form.addEventListener('input',e=>{if(e.target.id==='english-key')edited=true;changed();});
 $('english-enabled').addEventListener('change',changed);
 form.onsubmit=e=>{e.preventDefault();safe(async()=>{
  if(busy||nativeRecording)return;busy=true;controls();note('正在保存…');
  try{if(hasNative())await native('validateEnglishShortcut',shortcut);apply(await api('translation',value()));}
  catch(e){note(e.message,true);}finally{busy=false;controls();}
 });};
 $('english-eye').onclick=()=>safe(async()=>{
  if(visible){hideKey();return;}
  if(!edited){const revision=config?.revision;if(!config?.credential_saved)return;busy=true;controls();
   try{const r=await api('translation-credential',{revision,reveal:true});if(config?.revision!==revision||edited)return;$('english-key').value=r.credential;}
   finally{busy=false;controls();}}
  visible=true;$('english-key').type='text';$('english-eye').innerHTML=eyeMarkup.replace('</svg>','<path d="M4 4 20 20"/></svg>');$('english-eye').setAttribute('aria-label','隐藏翻译 API Key');
 });
 $('english-test').onclick=()=>safe(async()=>{
  if(busy||dirty||!config)return;hideKey();busy=true;controls();started=Date.now();$('english-test-result').hidden=false;
  const tick=()=>{$('english-test-result').textContent='正在翻译固定测试句 · '+((Date.now()-started)/1000).toFixed(1)+' 秒';};tick();clock=setInterval(tick,100);
  const revision=config.revision;
  try{const r=await api('translation-test',{revision});clearInterval(clock);if(config?.revision!==revision||!r.current){note('配置已改变，请按新配置测试',true);return;}config.last_test=r;renderTest(r);}
  catch(e){clearInterval(clock);renderTest({ok:false,detail:e.message});}
  finally{clearInterval(clock);busy=false;controls();}
 });
 async function closeRecorder(){recording=false;$('english-shortcut-dialog').close();if(hasNative())await native('cancelShortcut');}
 async function choose(c){if(!recording)return;if(hasNative())await native('validateEnglishShortcut',c);shortcut=c;$('english-record-shortcut').textContent=c.label;await closeRecorder();changed();}
 $('english-record-shortcut').onclick=()=>safe(async()=>{if(nativeRecording)return;if(hasNative())await native('beginShortcut');recording=true;candidate=null;modifier=null;$('english-shortcut-dialog').showModal();setTimeout(()=>{if(recording)safe(closeRecorder);},30000);});
 $('english-shortcut-cancel').onclick=()=>safe(closeRecorder);
 $('english-shortcut-dialog').addEventListener('cancel',e=>{e.preventDefault();safe(closeRecorder);});
 window.addEventListener('keydown',e=>{
  if(!recording)return;e.preventDefault();e.stopPropagation();if(e.code==='Escape'){safe(closeRecorder);return;}if(e.repeat)return;
  if(modifierLabels[e.code]){modifier={keyCode:keyMap[e.code],modifiers:0,label:modifierLabels[e.code]};return;}
  const code=keyMap[e.code],mask=(e.shiftKey?0x20000:0)|(e.ctrlKey?0x40000:0)|(e.altKey?0x80000:0)|(e.metaKey?0x100000:0);
  if(code===undefined||!mask&&!/^F\d+$/.test(e.code)){modifier=null;return;}
  candidate={keyCode:code,modifiers:mask,label:[e.ctrlKey?'Control':'',e.altKey?'Option':'',e.shiftKey?'Shift':'',e.metaKey?'Command':'',e.code.replace('Key','').replace('Space','空格')].filter(Boolean).join(' + '),code:e.code};
 },true);
 window.addEventListener('keyup',e=>{if(!recording)return;e.preventDefault();e.stopPropagation();if(candidate?.code===e.code){const c={...candidate};delete c.code;safe(()=>choose(c));}else if(!candidate&&modifier&&modifier.keyCode===keyMap[e.code])safe(()=>choose(modifier));},true);
 window.addEventListener('xiaoha-mouse-shortcut',e=>{if(recording)safe(()=>choose(e.detail));});
 window.addEventListener('xiaoha-native-state',e=>{nativeRecording=!!e.detail?.recording;controls();});
 window.addEventListener('xiaoha-view',e=>{if((e.detail==='voice'||e.detail==='asr'))safe(load);else{hideKey();if(recording)safe(closeRecorder);}});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)hideKey();});
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 safe(load);
})();
