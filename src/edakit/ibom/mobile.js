/* Offline mobile controls; shares the existing BOM selection and progress state. */
(function(){
'use strict';
const api=window.__ibom3d;if(!api)return;
const narrow=window.matchMedia('(max-width:1080px)'),sidebar=document.querySelector('.sidebar');
const nav=document.createElement('nav');nav.className='mobile-nav';nav.setAttribute('aria-label','移动端视图');
nav.innerHTML='<button type="button" data-pane="list" aria-pressed="true">物料</button><button type="button" data-pane="board" aria-pressed="false">板图</button><button type="button" class="mobile-done" disabled>标记完成</button>';
document.body.appendChild(nav);
const done=nav.querySelector('.mobile-done');
const sideButtons=[];
document.querySelectorAll('.sidebar [data-side]').forEach(original=>{if(original.style.display==='none')return;const button=document.createElement('button');button.type='button';button.className='mobile-side';button.textContent=original.dataset.side==='top'?'顶面':'底面';button.onclick=()=>original.click();document.querySelector('.canvas-toolbar .toolbar').appendChild(button);sideButtons.push({button,side:original.dataset.side});});
if(!((api.data.images||{}).top||(api.data.images||{}).bottom))document.getElementById('imageOpacityRow').hidden=true;
function fit(){if(narrow.matches)api.fitViewBox();else document.getElementById('boardView').setAttribute('viewBox','0 0 1000 700');}
function pane(value){document.body.classList.toggle('mobile-board',value==='board');nav.querySelectorAll('[data-pane]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.pane===value)));fit();window.dispatchEvent(new Event('resize'));}
nav.querySelectorAll('[data-pane]').forEach(b=>b.addEventListener('click',()=>pane(b.dataset.pane)));
function sync(){const state=api.readState();sideButtons.forEach(({button,side})=>button.classList.toggle('active',side===state.side));const row=api.data.bomRows.find(r=>r.id===state.selectedBomId);done.disabled=!row;done.setAttribute('aria-pressed',String(!!(row&&state.done[row.id])));done.textContent=row&&state.done[row.id]?'已完成 · 撤销':'标记完成';done.title=row?row.references.join(', '):'先选择物料';}
done.addEventListener('click',()=>{const id=api.readState().selectedBomId;if(id!==null)api.toggleDone(id);sync();});
const more=document.createElement('button');more.type='button';more.className='mobile-more';more.textContent='更多选项';more.setAttribute('aria-expanded','false');sidebar.querySelector('.controls').appendChild(more);
more.onclick=()=>{const expanded=sidebar.classList.toggle('mobile-expanded');more.setAttribute('aria-expanded',String(expanded));more.textContent=expanded?'收起选项':'更多选项';};
const zoom=document.createElement('div');zoom.className='mobile-zoom';zoom.innerHTML='<button type="button" aria-label="缩小板图">−</button><button type="button" aria-label="放大板图">+</button>';document.querySelector('.canvas-wrap').appendChild(zoom);
zoom.querySelectorAll('button').forEach((button,i)=>button.onclick=()=>{const factor=i?1.4:1/1.4;if(window.edakitIBOM3D&&window.edakitIBOM3D.zoom(factor))return;api.zoom(factor);});
function focus(){if(window.edakitIBOM3D&&window.edakitIBOM3D.focusSelected())return;api.focusSelected();}
const locate=document.createElement('button');locate.type='button';locate.className='mobile-side';locate.textContent='定位选中';locate.onclick=focus;document.querySelector('.canvas-toolbar .toolbar').appendChild(locate);
sidebar.querySelector('#bomList').addEventListener('click',e=>{if(!narrow.matches||e.target.closest('label,input,button'))return;if(e.target.closest('.bom-row')){pane('board');requestAnimationFrame(focus);}});
function resize(){if(!narrow.matches)pane('list');}
if(narrow.addEventListener)narrow.addEventListener('change',resize);else narrow.addListener(resize);
// Activate a button from the completed touch rather than relying on a delayed
// compatibility click after a canvas gesture. Suppress its compatibility events, even if opening a panel moves the target.
let buttonTouch=null,lastButtonTap=null;
document.addEventListener('pointerdown',e=>{if(e.pointerType!=='touch'||!narrow.matches)return;if(!e.isPrimary){buttonTouch=null;return;}const button=e.target.closest('button');buttonTouch=button&&!button.disabled?{button,id:e.pointerId,x:e.clientX,y:e.clientY,time:performance.now()}:null;},true);
document.addEventListener('pointermove',e=>{if(buttonTouch&&buttonTouch.id===e.pointerId&&Math.hypot(e.clientX-buttonTouch.x,e.clientY-buttonTouch.y)>8)buttonTouch=null;},true);
document.addEventListener('pointercancel',()=>buttonTouch=null,true);
window.addEventListener('blur',()=>buttonTouch=null);
document.addEventListener('pointerup',e=>{const tap=buttonTouch;buttonTouch=null;if(!tap||e.pointerId!==tap.id||performance.now()-tap.time>700||tap.button.disabled)return;if(e.target.closest('button')!==tap.button)return;lastButtonTap={x:e.clientX,y:e.clientY,time:performance.now()};e.preventDefault();tap.button.click();},true);
['mousedown','mouseup','click'].forEach(type=>document.addEventListener(type,e=>{if(e.isTrusted&&lastButtonTap&&performance.now()-lastButtonTap.time<700&&Math.hypot(e.clientX-lastButtonTap.x,e.clientY-lastButtonTap.y)<10&&e.detail>0){e.preventDefault();e.stopImmediatePropagation();}},true));
new ResizeObserver(fit).observe(document.querySelector('.canvas-wrap'));
window.edakitMobile={sync};sync();
})();
