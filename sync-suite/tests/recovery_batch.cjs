// Isolated batch model: no native app, files, system trash or network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../web/workbench.js','utf8');
const start=source.indexOf('function recoveryBatchSnapshot'),end=source.indexOf('function updateRecoveryBulk',start);
const c={};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
(async()=>{
 const rows=[{id:'a',seconds:1},{id:'retry',retrying:true},{id:'active',recording:true},{id:'b',seconds:2},{id:'a'}];
 const snapshot=c.recoveryBatchSnapshot(rows);assert.equal(snapshot.map(r=>r.id).join(','),'a,b');
 rows[0].seconds=99;assert.equal(snapshot[0].seconds,1);
 let inFlight=0,peak=0;const calls=[],progress=[];
 const result=await c.moveRecoveryBatch(rows,async value=>{inFlight++;peak=Math.max(peak,inFlight);calls.push(value);await Promise.resolve();inFlight--;if(value.id==='a'){rows.push({id:'newly-arrived'});return {ok:true};}throw Error('synthetic trash failure');},(done,total)=>progress.push([done,total]));
 assert.equal(peak,1);assert.equal(calls.map(x=>x.id).join(','),'a,b');assert(calls.every(x=>x.confirmed===true));
 assert.equal(result.moved.join(','),'a');assert.equal(result.failed.join(','),'b');assert.equal(JSON.stringify(progress),'[[1,2],[2,2]]');
 const cancelled=await c.moveRecoveryBatch([{id:'keep'}],async()=>({cancelled:true}));assert.equal(cancelled.moved.length,0);assert.equal(cancelled.failed.length,1);
 console.log('recovery batch: 10 checks passed; exact snapshot, serial calls, active/retry exclusions and partial failure');
})().catch(e=>{console.error(e);process.exitCode=1;});
