'use strict';
// The menu-bar account entry rejoins the same native workbench shell.
if(window.webkit?.messageHandlers?.xiaoha&&new URLSearchParams(location.search).get('embedded')!=='1')location.replace('/workbench#sync');
const $=id=>document.getElementById(id), titles={clipboard:'共享文字',glossary:'词库纠正',preferences:'使用偏好',usage:'使用统计',history:'本机历史',devices:'登录设备'};
let me=null, health={}, cache={cursor:0,items:{},queue:[],usage_total:{},devices:[],usage_by_device:[]}, running=false, loadingPrefs=false, desktopConflicts=[];
const platform=()=>/iPad/.test(navigator.userAgent)||(/Macintosh/.test(navigator.userAgent)&&navigator.maxTouchPoints>1)?'iPad':/iPhone/.test(navigator.userAgent)?'iPhone':/Android/.test(navigator.userAgent)?'Android':/Win/.test(navigator.userAgent)?'Windows':/Mac/.test(navigator.userAgent)?'Mac':'Web';
let device=localStorage.getItem('xh-sync-browser-device');if(!device){device=crypto.randomUUID();localStorage.setItem('xh-sync-browser-device',device);}
$('device-name').value=platform()+' · 浏览器';
function msg(text,error=false){$('message').textContent=text;$('message').hidden=!text;$('message').classList.toggle('error',error);}
function save(){if(me)localStorage.setItem('xh-sync-account:'+me.account_id,JSON.stringify(cache));}
function restore(){cache={cursor:0,items:{},queue:[],usage_total:{},devices:[],usage_by_device:[]};localStorage.setItem('xh-sync-last-identity',JSON.stringify({account_id:me.account_id,username:me.username,device_id:me.device_id}));try{const raw=JSON.parse(localStorage.getItem('xh-sync-account:'+me.account_id));if(raw&&raw.items&&Array.isArray(raw.queue))cache=raw;}catch{} }
async function api(path,body,method){const h={};if(body!==undefined){h['Content-Type']='application/json';if(me)h['X-CSRF-Token']=me.csrf;}const response=await fetch(path,{method:method||(body===undefined?'GET':'POST'),credentials:'same-origin',headers:h,body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});let value;try{value=await response.json();}catch{value={detail:'服务暂时无法访问'};}if(!response.ok){const e=new Error(typeof value.detail==='string'?value.detail:value.detail?.message||'操作失败，请重试');e.status=response.status;e.payload=value.detail;throw e;}return value;}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function button(text,action,cls){const n=node('button',text,cls);n.type='button';n.onclick=()=>Promise.resolve(action()).catch(e=>msg(e.message,true));return n;}
function item(kind,id){return cache.items[kind+'/'+id];}
function pref(id,fallback){const pending=[...cache.queue].reverse().find(o=>o.kind==='preference'&&o.id===id);return pending?pending.value.value:(item('preference',id)?.value.value??fallback);}
function tab(id){if(!titles[id])id='clipboard';document.querySelectorAll('[data-view]').forEach(n=>n.hidden=n.dataset.view!==id);document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab===id));$('page-title').textContent=titles[id];if(id==='history'&&me)loadHistory();}
$('nav').onclick=e=>{const n=e.target.closest('[data-tab]');if(n){location.hash=n.dataset.tab;tab(n.dataset.tab);}};window.addEventListener('hashchange',()=>tab(location.hash.slice(1)));tab(location.hash.slice(1));
function requireLogin(){if(!me){msg('请先登录账号',true);return false;}return true;}
function queue(kind,id,value,deleted=false,base=null){if(!requireLogin())return;const old=cache.queue.find(o=>o.kind===kind&&o.id===id);if(old){msg('这一项还有待同步的修改，请先同步或处理冲突',true);return;}cache.queue.push({operation_id:crypto.randomUUID(),kind,id,value,deleted,base_revision:base??item(kind,id)?.revision??0});save();render();sync();}
function emptyRows(where,text){where.replaceChildren(node('p',text,'empty'));}
function rows(where,values,make){where.replaceChildren();if(!values.length){emptyRows(where,'这里还没有内容');return;}values.forEach(v=>where.append(make(v)));}
function render(){
  if(!me)return;
  $('workspace').hidden=false;$('auth').hidden=true;$('logout').hidden=false;$('account-label').textContent=me.username+' · '+platform();
  document.body.dataset.theme=pref('theme','cocoa');document.body.classList.toggle('large-text',pref('text_size','normal')==='large');
  const shared=item('clipboard','current'),pending=[...cache.queue].reverse().find(o=>o.kind==='clipboard'&&o.id==='current');
  const draft=typeof cache.editorDraft==='string'?cache.editorDraft:null;
  if(document.activeElement!==$('shared-text'))$('shared-text').value=draft??pending?.value.text??shared?.value.text??'';
  $('copy-shared').textContent=draft!==null||pending?'复制本机草稿':'复制云端文字';
  $('text-count').textContent=[...$('shared-text').value].length.toLocaleString()+' 字';
  $('clipboard-meta').textContent=draft!==null?'本机未共享的草稿':pending?'本机待同步的草稿':shared?'更新于 '+new Date(shared.updated_at*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):'还没有共享文字';
  const glossary=Object.values(cache.items).filter(x=>x.kind==='glossary'&&!x.deleted).sort((a,b)=>a.value.term.localeCompare(b.value.term,'zh-CN'));
  rows($('word-list'),glossary,w=>{const row=node('div',undefined,'row'),text=node('div');text.append(node('p',w.value.term,'title'),node('p',w.value.aliases.length?'纠正：'+w.value.aliases.join('、'):'已保存词语','sub'));const actions=node('div',undefined,'button-row');actions.append(button('编辑',()=>{cache.wordDraft={id:w.id,base:w.revision,term:w.value.term,aliases:w.value.aliases.join('，')};save();render();$('word-term').focus();}),button('删除',()=>queue('glossary',w.id,{},true,w.revision),'danger'));row.append(text,actions);return row;});
  if(document.activeElement?.closest('#word-form')===null){const w=cache.wordDraft;$('word-term').value=w?.term||'';$('word-aliases').value=w?.aliases||'';$('word-save').textContent=w?.id?'保存词条':'添加词条';$('word-cancel').hidden=!w?.id;}
  if(document.activeElement?.closest('#prefs-form')===null){$('pref-theme').value=pref('theme','cocoa');$('pref-text-size').value=pref('text_size','normal');$('pref-replacements').checked=pref('apply_replacements',true);$('pref-dictation').checked=pref('sync_dictation_text',true);}
  const selected=$('usage-device').value;$('usage-device').replaceChildren(new Option('全部设备','all'));cache.devices.forEach(d=>$('usage-device').add(new Option(d.name,d.id)));if([...$('usage-device').options].some(o=>o.value===selected))$('usage-device').value=selected;
  renderUsage();
  rows($('device-list'),cache.devices,d=>{const row=node('div',undefined,'row'),text=node('div');text.append(node('p',d.name+(d.id===me.device_id?' · 当前设备':''),'title'),node('p',d.platform+' · '+(d.revoked?'已退出':'已连接'),'sub'));row.append(text);if(!d.revoked)row.append(button('退出设备',async()=>{if(!confirm('退出“'+d.name+'”？已有统计会保留。'))return;await api('/api/devices/'+d.id+'/revoke',{});if(d.id===me.device_id){signedOut();return;}await sync();},'danger'));return row;});
  $('queue-label').textContent=cache.queue.length?cache.queue.length+' 项保留在本机，等待同步':'没有待同步更新';renderConflicts();
}
function renderUsage(){const selected=$('usage-device').value;const visible=cache.usage_by_device.filter(x=>selected==='all'||x.device_id===selected);const t=visible.reduce((a,x)=>({characters:a.characters+x.characters,sessions:a.sessions+x.sessions,seconds:a.seconds+x.seconds}),{characters:0,sessions:0,seconds:0});$('usage-characters').textContent=t.characters.toLocaleString();$('usage-sessions').textContent=t.sessions.toLocaleString();$('usage-minutes').textContent=(t.seconds/60).toLocaleString('zh-CN',{maximumFractionDigits:1});rows($('usage-list'),visible,r=>{const row=node('div',undefined,'row'),d=cache.devices.find(d=>d.id===r.device_id);row.append(node('p',d?.name||'已退出的设备','title'),node('p',r.characters.toLocaleString()+' 字 · '+r.sessions+' 次 · '+(r.seconds/60).toFixed(1)+' 分钟','sub'));return row;});}
$('usage-device').onchange=renderUsage;
function renderConflicts(){const values=cache.queue.filter(o=>o.conflict).concat(desktopConflicts);$('conflicts').hidden=!values.length;$('conflict-list').replaceChildren();values.forEach(op=>{const n=node('div',undefined,'conflict-item');n.append(node('p',op.kind==='clipboard'?'共享文字':op.kind==='glossary'?'词库条目':'使用偏好','title'));n.append(node('div','本机：'+JSON.stringify(op.value),'conflict-preview'),node('div','另一设备：'+JSON.stringify(op.conflict.current?.value??{}),'conflict-preview'));const actions=node('div',undefined,'button-row');actions.append(button('保留本机这份',async()=>{if(op.desktop){await api('/local/resolve',{operation_id:op.operation_id,choice:'local'});await loadDesktop();return;}op.base_revision=op.conflict.current?.revision||0;op.operation_id=crypto.randomUUID();delete op.conflict;save();render();sync();}),button('使用另一设备的更新',async()=>{if(op.desktop){await api('/local/resolve',{operation_id:op.operation_id,choice:'cloud'});await loadDesktop();return;}const current=op.conflict.current;if(current)cache.items[op.kind+'/'+op.id]=current;cache.queue=cache.queue.filter(x=>x!==op);save();render();sync();}));n.append(actions);$('conflict-list').append(n);});}
async function sync(){if(!me||running)return;if(!me.csrf){await start();return;}running=true;try{for(const op of [...cache.queue]){if(op.conflict)continue;try{const body={...op};delete body.conflict;await api('/api/mutate',body);cache.queue=cache.queue.filter(x=>x.operation_id!==op.operation_id);save();}catch(e){if(e.status===409){op.conflict=e.payload;save();continue;}throw e;}}
  const next=await api('/api/state?since='+cache.cursor);if(next.reset)cache.items={};next.items.forEach(x=>cache.items[x.kind+'/'+x.id]=x);cache.cursor=next.revision;cache.devices=next.devices;cache.usage_by_device=next.usage_by_device;cache.usage_total=next.usage_total;save();$('network').textContent='已同步';render();
}catch(e){$('network').textContent=e.status===401?'需要重新登录':'离线 · 修改保留在本机';if(e.status===401)signedOut(false);else if(e.status&&e.status!==409)msg(e.message,true);}finally{running=false;}}
function signedOut(clearCookie=true){me=null;desktopConflicts=[];localStorage.removeItem('xh-sync-last-identity');cache={cursor:0,items:{},queue:[],devices:[],usage_by_device:[],usage_total:{}};$('workspace').hidden=true;$('auth').hidden=false;$('logout').hidden=true;$('shared-text').value='';document.body.dataset.theme='cocoa';}
async function login(register=false){const form=$('login-form');if(!form.reportValidity())return;const controls=form.querySelectorAll('button');controls.forEach(n=>n.disabled=true);try{if(health.desktop){await api('/local/connect',{server:$('server-url').value});}me=await api(register?'/api/register':'/api/login',{username:$('username').value,password:$('password').value,device_id:device,device_name:$('device-name').value,platform:platform(),invite:$('invite').value});$('password').value='';restore();render();msg('账号已连接。同步内容与本机历史分别保存。');await sync();if(health.desktop)await loadDesktop();}catch(e){msg(e.message,true);}finally{controls.forEach(n=>n.disabled=false);}}
$('login-form').onsubmit=e=>{e.preventDefault();login();};$('register').onclick=()=>login(true);
$('logout').onclick=async()=>{try{await api('/api/logout',{});signedOut();msg('已退出账号。本机待同步修改保留在这个账号下。');}catch(e){msg(e.message,true);}};
$('shared-text').oninput=()=>{$('text-count').textContent=[...$('shared-text').value].length.toLocaleString()+' 字';if(me){cache.editorDraft=$('shared-text').value;save();}};
$('share-text').onclick=()=>{if(cache.queue.some(o=>o.kind==='clipboard'&&o.id==='current')){msg('已有一份待同步草稿，请先同步或处理冲突；新的编辑已保留在本机。',true);return;}const text=$('shared-text').value;cache.editorDraft=null;queue('clipboard','current',{text});};
$('copy-shared').onclick=async()=>{try{await navigator.clipboard.writeText($('shared-text').value);msg('已复制，去需要的位置粘贴即可。');}catch{msg('当前浏览器未允许直接复制，请选择文字后使用系统复制。',true);}};
$('read-clipboard').onclick=async()=>{try{$('shared-text').value=await navigator.clipboard.readText();$('shared-text').oninput();msg('已读取到编辑区，点“共享这段文字”后才会上传。');}catch{msg('请直接在编辑区粘贴，再点“共享这段文字”。',true);}};
$('word-form').oninput=()=>{cache.wordDraft={...(cache.wordDraft||{}),term:$('word-term').value,aliases:$('word-aliases').value};save();};
$('word-cancel').onclick=()=>{cache.wordDraft=null;save();$('word-form').reset();$('word-save').textContent='添加词条';$('word-cancel').hidden=true;render();};
$('word-form').onsubmit=e=>{e.preventDefault();const term=$('word-term').value.trim(),aliases=[...new Set($('word-aliases').value.split(/[,，、]/).map(s=>s.trim()).filter(Boolean))];if(!term||aliases.length>20||aliases.some(a=>a.length>100)){msg('请填写词语；误识别写法最多20个，每个不超过100字。',true);return;}const draft=cache.wordDraft,id=draft?.id||crypto.randomUUID();if(cache.queue.some(o=>o.kind==='glossary'&&o.id===id)){msg('这个词条还有待同步更新，请先同步或处理冲突。',true);return;}cache.wordDraft=null;queue('glossary',id,{term,aliases},false,draft?.id?draft.base:null);$('word-form').reset();$('word-save').textContent='添加词条';$('word-cancel').hidden=true;};
$('prefs-form').onsubmit=e=>{e.preventDefault();const values={theme:$('pref-theme').value,text_size:$('pref-text-size').value,apply_replacements:$('pref-replacements').checked,sync_dictation_text:$('pref-dictation').checked};Object.entries(values).forEach(([id,value])=>{if(pref(id,({theme:'cocoa',text_size:'normal',apply_replacements:true,sync_dictation_text:true})[id])!==value)queue('preference',id,{value});});};
async function loadDesktop(){try{const c=await api('/local/settings');$('desktop-enabled').checked=c.enabled;desktopConflicts=(c.conflicts||[]).map(o=>({...o,desktop:true}));renderConflicts();$('auto-send').checked=c.send_clipboard;$('auto-receive').checked=c.receive_clipboard;$('usage-sync').checked=c.usage_sync;$('desktop-state').textContent=c.status||'后台开关仅对这台设备生效';$('desktop-controls').hidden=false;$('desktop-note').hidden=true;}catch(e){msg(e.message,true);}}
$('save-desktop').onclick=async()=>{try{await api('/local/settings',{enabled:$('desktop-enabled').checked,send_clipboard:$('auto-send').checked,receive_clipboard:$('auto-receive').checked,usage_sync:$('usage-sync').checked});msg('这台设备的后台开关已保存。');await loadDesktop();}catch(e){msg(e.message,true);}};
async function loadHistory(){if(!health.desktop){emptyRows($('history-list'),'此浏览器入口没有录音历史。请在录音设备查看自己的本机历史。');return;}try{const result=await api('/local/history');$('history-list').replaceChildren();if(!result.records.length){emptyRows($('history-list'),'本机还没有完成的录音。');return;}result.records.forEach(r=>{const n=node('article',undefined,'history-record');const head=node('div',undefined,'section-heading');head.append(node('span',new Date(r.created_at).toLocaleString('zh-CN'),'muted'),button('复制',()=>navigator.clipboard.writeText(r.text)));n.append(head,node('p',r.text,'history-text'));$('history-list').append(n);});}catch(e){msg(e.message,true);}}
async function start(){try{health=await api('/api/health');$('environment').textContent=health.desktop?'本机组件':(health.local_only?'仅本机 · 尚未上云':'账号同步');$('network').textContent='服务可用';$('register').hidden=!health.signup_enabled;$('invite-field').hidden=!health.signup_enabled;$('server-field').hidden=!health.desktop;if(health.desktop){$('server-url').value=health.server||'';$('register').hidden=true;$('invite-field').hidden=true;}
  try{me=await api('/api/me');restore();render();await sync();if(health.desktop)await loadDesktop();}catch(e){if(e.status!==401)msg(e.message,true);}
}catch{try{const last=JSON.parse(localStorage.getItem('xh-sync-last-identity'));if(last){me={...last,csrf:''};restore();render();}}catch{}msg('暂时无法连接服务。离线修改会留在当前账号的本机队列，重连后继续。',true);$('network').textContent='离线 · 修改保留在本机';}}
window.addEventListener('online',start);setInterval(()=>{if(!document.hidden){sync();if(health.desktop&&me)loadDesktop();}$('back-workbench').hidden=!health.desktop;},4000);start().then(()=>$('back-workbench').hidden=!health.desktop);
if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});

const embedded=new URLSearchParams(location.search).get('embedded')==='1'&&window.parent!==window;
let hostTheme='cocoa';
if(embedded){
 document.body.classList.add('embedded-sync');
 const tabs=$('nav');document.querySelector('main').prepend(tabs);
 tabs.querySelector('[data-tab="glossary"]').firstChild.textContent='账号词库';
 tabs.querySelector('[data-tab="preferences"]').firstChild.textContent='同步偏好';
 tabs.querySelector('[data-tab="usage"]').firstChild.textContent='汇总统计';
 tabs.querySelector('[data-tab="history"]').hidden=true;
 const main=document.querySelector('main');
 const reportSize=()=>{
  const top=main.getBoundingClientRect().top,form=document.getElementById('login-form');
  const bottom=Math.max(main.scrollHeight,...Array.from(main.children).filter(n=>!n.hidden&&getComputedStyle(n).display!=='none').map(n=>n.getBoundingClientRect().bottom-top),document.getElementById('auth').hidden?0:form.getBoundingClientRect().top-top+form.scrollHeight);
  parent.postMessage({type:'xh-sync-height',height:Math.ceil(bottom)+10},location.origin);
 };
 const resizeObserver=new ResizeObserver(reportSize);resizeObserver.observe(main);
 let sizeFrame;const scheduleSize=()=>{cancelAnimationFrame(sizeFrame);sizeFrame=requestAnimationFrame(reportSize);};
 const contentObserver=new MutationObserver(scheduleSize);contentObserver.observe(main,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class','style']});
 window.addEventListener('resize',scheduleSize);document.fonts?.ready.then(scheduleSize);scheduleSize();
 window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==parent)return;if(e.data?.type==='xh-host-theme'&&['cocoa','mint','ink'].includes(e.data.theme)){hostTheme=e.data.theme;document.body.dataset.theme=hostTheme;}if(e.data?.type==='xh-sync-tab'&&titles[e.data.tab]){location.hash=e.data.tab;tab(e.data.tab);}});
 new MutationObserver(()=>{if(document.body.dataset.theme!==hostTheme)document.body.dataset.theme=hostTheme;}).observe(document.body,{attributes:true,attributeFilter:['data-theme']});
}else{document.querySelector('main').prepend($('back-workbench'));}


