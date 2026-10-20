/* Element-owned scrolling avoids the native WK viewport scroller and its theme. */
(() => {
 const root=document.documentElement,body=document.body,entries=new Map();
 const syncTheme=()=>root.dataset.theme=body.dataset.theme||'cocoa';syncTheme();
 new MutationObserver(syncTheme).observe(body,{attributes:true,attributeFilter:['data-theme']});
 const primary=document.getElementById('page-scroll');
 if(!primary)return;
 let scheduled=false;
 function render(entry){
  const {target,track,thumb}=entry,r=target.getBoundingClientRect(),main=target===primary;
  const top=main?0:Math.max(0,r.top),bottom=main?innerHeight:Math.min(innerHeight,r.bottom),height=Math.max(0,bottom-top),range=target.scrollHeight-target.clientHeight;
  track.hidden=range<=1||height<20||r.width===0||(main&&body.classList.contains('embedded-sync'));
  if(track.hidden)return;
  track.style.left=(main?innerWidth-10:r.right-10)+'px';track.style.top=top+'px';track.style.height=height+'px';
  const length=Math.min(height,Math.max(30,height*target.clientHeight/target.scrollHeight)),offset=(height-length)*target.scrollTop/range;
  thumb.style.height=length+'px';thumb.style.transform='translateY('+offset+'px)';
  track.setAttribute('aria-valuenow',String(Math.round(target.scrollTop/range*100)));
  entry.travel=height-length;entry.range=range;
 }
 function update(){scheduled=false;for(const entry of entries.values())render(entry);}
 function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
 function reveal(entry){clearTimeout(entry.timer);entry.track.classList.add('is-scrolling');entry.timer=setTimeout(()=>entry.track.classList.remove('is-scrolling'),850);}
 function add(target){
  if(entries.has(target))return;
  const track=document.createElement('div'),thumb=document.createElement('div');track.className='xh-scroll-track';thumb.className='xh-scroll-thumb';track.append(thumb);body.append(track);
  track.setAttribute('role','scrollbar');track.setAttribute('aria-label',target===primary?'页面滚动':'内容滚动');track.setAttribute('aria-orientation','vertical');track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');track.setAttribute('aria-controls',target.id);track.tabIndex=0;
  const entry={target,track,thumb};entries.set(target,entry);
  target.addEventListener('scroll',()=>{reveal(entry);schedule();},{passive:true});
  track.addEventListener('pointerdown',e=>{
   e.preventDefault();if(e.target!==thumb){const r=track.getBoundingClientRect();target.scrollTop=(e.clientY-r.top-parseFloat(thumb.style.height)/2)/entry.travel*entry.range;render(entry);}
   const startY=e.clientY,startTop=target.scrollTop;track.setPointerCapture(e.pointerId);track.classList.add('is-dragging');
   const move=ev=>{target.scrollTop=startTop+(ev.clientY-startY)/entry.travel*entry.range;};
   const end=()=>{track.classList.remove('is-dragging');track.removeEventListener('pointermove',move);track.removeEventListener('pointerup',end);track.removeEventListener('pointercancel',end);reveal(entry);};
   track.addEventListener('pointermove',move);track.addEventListener('pointerup',end);track.addEventListener('pointercancel',end);
  });
  track.addEventListener('keydown',e=>{const steps={ArrowDown:40,ArrowUp:-40,PageDown:target.clientHeight*.85,PageUp:-target.clientHeight*.85};if(e.key==='Home')target.scrollTop=0;else if(e.key==='End')target.scrollTop=target.scrollHeight;else if(e.key in steps)target.scrollTop+=steps[e.key];else return;e.preventDefault();reveal(entry);});
  new ResizeObserver(schedule).observe(target);schedule();
 }
 function scan(){add(primary);document.querySelectorAll('.runtime-log-list,.select-menu,#application-details').forEach(add);for(const [target,entry] of entries)if(!target.isConnected){clearTimeout(entry.timer);entry.track.remove();entries.delete(target);}schedule();}
 new MutationObserver(scan).observe(primary,{childList:true,subtree:true});window.addEventListener('resize',schedule);document.addEventListener('scroll',schedule,{capture:true,passive:true});scan();
})();
