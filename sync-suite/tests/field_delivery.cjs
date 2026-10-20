// Isolated DOM fixture: no browser, microphone, network or system clipboard.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../web/workbench.js','utf8');
const start=source.indexOf('const localFieldTargets='),end=source.indexOf("window.addEventListener('xiaoha-mouse-shortcut'",start);
const listeners={};
const field={value:'',selectionStart:0,selectionEnd:0,isConnected:true,disabled:false,readOnly:false,matches:()=>true,setRangeText(text,start,end){this.value=this.value.slice(0,start)+text+this.value.slice(end);this.selectionStart=this.selectionEnd=start+text.length;},dispatchEvent(){listeners.input();}};
const document={activeElement:field,addEventListener:(name,cb)=>{listeners[name]=cb;},execCommand:()=>false};
const window={};vm.runInNewContext(source.slice(start,end),{document,window,crypto:require('node:crypto'),Event:class{}});
let first=window.xiaohaCaptureField(),second=window.xiaohaCaptureField();
assert(window.xiaohaInsertField(first,'第一段'));
assert(window.xiaohaInsertField(second,'第二段'));
assert.equal(field.value,'第一段第二段');
assert.equal(window.xiaohaInsertField(second,'重复'),false);
let token=window.xiaohaCaptureField();listeners.pointerdown();assert.equal(window.xiaohaInsertField(token,'错误位置'),false);
token=window.xiaohaCaptureField();listeners.input();assert.equal(window.xiaohaInsertField(token,'覆盖新输入'),false);
token=window.xiaohaCaptureField();field.isConnected=false;assert.equal(window.xiaohaInsertField(token,'旧页面'),false);field.isConnected=true;
token=window.xiaohaCaptureField();field.readOnly=true;assert.equal(window.xiaohaInsertField(token,'只读'),false);
console.log('local field delivery: 8 checks passed; ordered insertion, one-use tokens and changed-input protection');
