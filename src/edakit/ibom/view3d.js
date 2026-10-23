/* Offline board preview. three.js r158; optional occt-import-js 0.0.23. */
(function(){
'use strict';
const api=window.__ibom3d;if(!api||!window.THREE)return;
const T=window.THREE,data=api.data,info=data.preview3d||{models:{},boardThickness:1.6};
const svg=document.getElementById('boardView'),wrap=svg.parentElement,toolbar=document.getElementById('resetView').parentElement;
wrap.style.position='relative';
const toggle=document.createElement('button');toggle.type='button';toggle.id='toggle3d';toggle.textContent='3D 预览';toolbar.insertBefore(toggle,toolbar.firstChild);
const host=document.createElement('div');host.id='board3d';Object.assign(host.style,{position:'absolute',inset:'0',display:'none',background:'#edf1f5',touchAction:'none'});wrap.appendChild(host);
const status=document.createElement('div');status.id='preview3dStatus';Object.assign(status.style,{position:'absolute',left:'12px',top:'12px',padding:'7px 10px',background:'rgba(255,255,255,.94)',borderRadius:'7px',fontSize:'12px',pointerEvents:'none',maxWidth:'80%'});host.appendChild(status);
let renderer,scene,camera,root,active=false,ready=false,loading=false,lastSide='top';let yaw=0,pitch=.65,distance=100,target=new T.Vector3(),drag=null;const parts=[],pickables=[];
const cx=(data.board.minX+data.board.maxX)/2,cy=(data.board.minY+data.board.maxY)/2;
const span=Math.max(data.board.maxX-data.board.minX,data.board.maxY-data.board.minY,10),thickness=info.boardThickness||1.6;
let realCount=0,missingCount=0,failed=0;const outlines=[];const selection=document.createElement("div");selection.id="preview3dSelection";Object.assign(selection.style,{position:"absolute",left:"12px",bottom:"12px",maxWidth:"75%",padding:"8px 11px",background:"rgba(255,255,255,.96)",border:"2px solid #f97316",borderRadius:"7px",fontSize:"13px",pointerEvents:"none",display:"none"});host.appendChild(selection);
function bytes(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0));}
function shape(points){if(!points||points.length<3)return null;const s=new T.Shape();s.moveTo(points[0].x,points[0].y);points.slice(1).forEach(p=>s.lineTo(p.x,p.y));s.closePath();return s;}
function material(color){return new T.MeshStandardMaterial({color,roughness:.72,metalness:.08});}
function mesh(geometry,color){return new T.Mesh(geometry,material(color));}
function remember(group,c,real){group.userData={ref:c.refdes,bomId:c.bomId,real};group.traverse(o=>{if(o.isMesh||o.isLine){o.material=o.material.clone();o.userData.base=o.material.color.clone();pickables.push(o);}});root.add(group);parts.push(group);}
function surfaceGroup(c){const g=new T.Group(),bottom=c.side==='bottom',z=bottom?-thickness/2-.04:thickness/2+.04;
 (c.drawingShapes||[]).filter(s=>s.source==='silkscreen').forEach(s=>{const points=s.points.map(p=>new T.Vector3(p.x,p.y,z));if(points.length<2)return;const geom=new T.BufferGeometry().setFromPoints(points),mat=new T.LineBasicMaterial({color:0xe8e5cf});g.add(s.type==='polygon'?new T.LineLoop(geom,mat):new T.Line(geom,mat));});
 (c.padShapes||[]).forEach(p=>{const angle=T.MathUtils.degToRad(p.rotation||0),radius=p.diameter/2,w=Math.max(p.width,.03),h=Math.max(p.height,.03);let outline;
 if(p.primitive==='circle'){outline=new T.Shape();outline.absarc(0,0,radius,0,Math.PI*2,false);}else outline=shape([{x:-w/2,y:-h/2},{x:w/2,y:-h/2},{x:w/2,y:h/2},{x:-w/2,y:h/2}]);
 for(const hole of info.boardHoles||[]){const dx=hole.x-p.x,dy=hole.y-p.y,x=dx*Math.cos(angle)+dy*Math.sin(angle),y=-dx*Math.sin(angle)+dy*Math.cos(angle),r=hole.diameter/2;
 if(p.primitive==='circle'?Math.hypot(x,y)+r<=radius+.001:Math.abs(x)+r<=w/2+.001&&Math.abs(y)+r<=h/2+.001){const cut=new T.Path();cut.absarc(x,y,r,0,Math.PI*2,true);outline.holes.push(cut);}}
 const pad=mesh(new T.ExtrudeGeometry(outline,{depth:.04,bevelEnabled:false,curveSegments:24}),0xb58a44);pad.material.metalness=.55;pad.material.roughness=.38;pad.rotation.z=angle;pad.material.polygonOffset=true;pad.material.polygonOffsetFactor=-1;pad.material.polygonOffsetUnits=-2;pad.position.set(p.x,p.y,bottom?-thickness/2-.04:thickness/2+.01);g.add(pad);});
 const label=c.refdesLabel;
 if(label){const canvas=document.createElement('canvas');canvas.width=512;canvas.height=128;const ctx=canvas.getContext('2d');ctx.fillStyle='#eeeadd';ctx.font='100px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(c.refdes,256,66,500);const texture=new T.CanvasTexture(canvas);texture.colorSpace=T.SRGBColorSpace;texture.anisotropy=renderer.capabilities.getMaxAnisotropy();
 const angle=T.MathUtils.degToRad(label.rotation),vertical=Math.abs(Math.sin(angle))>Math.abs(Math.cos(angle)),w=label.maxX-label.minX,h=label.maxY-label.minY;
 const text=new T.Mesh(new T.PlaneGeometry(vertical?h:w,vertical?w:h),new T.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,alphaTest:.1,side:T.DoubleSide,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-3}));text.position.set((label.minX+label.maxX)/2,(label.minY+label.maxY)/2,z+.005*(bottom?-1:1));text.rotation.z=angle;if(bottom)text.rotation.x=Math.PI;if(label.mirrored)text.scale.x=-1;text.userData.silkscreen=true;g.add(text);}
 return g;}
function footprintOnly(c){remember(surfaceGroup(c),c,false);missingCount++;}
function realGroup(c,result){const model=c.model3d,container=new T.Group(),placed=new T.Group();
 result.meshes.forEach(m=>{const geom=m.__geometry||new T.BufferGeometry();if(!m.__geometry){geom.setAttribute('position',new T.Float32BufferAttribute(m.attributes.position.array,3));geom.setIndex(m.index.array);if(m.attributes.normal)geom.setAttribute('normal',new T.Float32BufferAttribute(m.attributes.normal.array,3));else geom.computeVertexNormals();m.__geometry=geom;}const color=m.color?new T.Color(...m.color).convertSRGBToLinear():new T.Color(0x777f86);placed.add(mesh(geom,color));});
 placed.rotation.set(...model.rotation.map(T.MathUtils.degToRad),'ZYX');placed.position.set(...model.offset);container.add(placed);
 container.rotation.z=T.MathUtils.degToRad(c.rotation||0);if(c.side==='bottom')container.scale.set(1,-1,-1);
 container.position.set(c.x,c.y,c.side==='bottom'?-thickness/2:thickness/2);const group=new T.Group();group.add(container,surfaceGroup(c));remember(group,c,true);realCount++;}
function summary(){status.textContent='真实模型 '+realCount+' · 无模型 '+missingCount+(failed?'（模型加载失败 '+failed+'）':'')+'（仅焊盘/丝印） · 板厚 '+thickness+' mm（示意）｜拖动旋转，滚轮缩放，Shift 拖动平移';}
function draw(){if(!renderer||!active)return;camera.aspect=host.clientWidth/Math.max(1,host.clientHeight);camera.near=Math.max(.03,distance-span*.85);camera.far=Math.max(camera.near+1,distance+span*2);camera.updateProjectionMatrix();renderer.setSize(host.clientWidth,host.clientHeight,false);camera.position.set(target.x+distance*Math.sin(yaw)*Math.sin(pitch),target.y-distance*Math.cos(yaw)*Math.sin(pitch),target.z+distance*Math.cos(pitch));camera.up.set(0,0,1);camera.lookAt(target);renderer.render(scene,camera);}
function reset(){target.set(0,0,0);yaw=0;pitch=api.readState().side==='bottom'?Math.PI-.65:.65;distance=span*1.8;draw();}
async function init(){if(ready||loading)return;loading=true;status.textContent='正在准备 3D 预览…';try{
 renderer=new T.WebGLRenderer({antialias:true,alpha:false,logarithmicDepthBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.NoToneMapping;renderer.setClearColor(0xc4c4c4);renderer.domElement.style.cssText='width:100%;height:100%;display:block';host.insertBefore(renderer.domElement,status);
 scene=new T.Scene();scene.add(new T.HemisphereLight(0xffffff,0x666666,.95));const light=new T.DirectionalLight(0xffffff,1.4);light.position.set(80,-100,180);scene.add(light);const back=new T.DirectionalLight(0xffffff,.65);back.position.set(-80,80,-100);scene.add(back);
 camera=new T.PerspectiveCamera(35,1,.01,span*100);root=new T.Group();root.position.set(-cx,-cy,0);scene.add(root);
 const profile=shape(data.profile&&data.profile.length?data.profile:[{x:data.board.minX,y:data.board.minY},{x:data.board.maxX,y:data.board.minY},{x:data.board.maxX,y:data.board.maxY},{x:data.board.minX,y:data.board.maxY}]);
 for(const hole of info.boardHoles||[]){const cut=new T.Path();cut.absarc(hole.x,hole.y,hole.diameter/2,0,Math.PI*2,true);profile.holes.push(cut);}
 const board=mesh(new T.ExtrudeGeometry(profile,{depth:thickness,bevelEnabled:false,steps:1}),0x171b19);board.position.z=-thickness/2;board.material.polygonOffset=true;board.material.polygonOffsetFactor=1;board.material.polygonOffsetUnits=1;root.add(board);
 const parsed={};let occt=null;for(const [key,entry] of Object.entries(info.models||{})){await new Promise(r=>setTimeout(r,0));try{status.textContent='正在加载真实模型：'+entry.name;if(entry.format==='allegro-facets'){if(entry.meshes&&entry.meshes.length)parsed[key]={success:true,meshes:entry.meshes};}else{if(!occt)occt=await occtimportjs({wasmBinary:bytes(window.__ibomWasm)});const result=occt.ReadStepFile(bytes(entry.data),{linearUnit:'millimeter',linearDeflectionType:'absolute_value',linearDeflection:.06,angularDeflection:.35});if(result.success&&result.meshes.length)parsed[key]=result;}}catch(e){console.warn('3D model preview failed',entry.name,e);}}
 for(const c of data.components){if(c.x==null||c.y==null)continue;if(c.model3d&&parsed[c.model3d.key])realGroup(c,parsed[c.model3d.key]);else{if(c.model3d)failed++;footprintOnly(c);}}
 ready=true;loading=false;summary();reset();sync();
 host.addEventListener('pointerdown',e=>{if(e.target===status)return;drag={x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY};host.setPointerCapture(e.pointerId);});
 host.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.lastX,dy=e.clientY-drag.lastY;if(e.shiftKey){const factor=distance/host.clientHeight*.5;const right=new T.Vector3().setFromMatrixColumn(camera.matrixWorld,0),up=new T.Vector3().setFromMatrixColumn(camera.matrixWorld,1);target.addScaledVector(right,-dx*factor).addScaledVector(up,dy*factor);}else{yaw-=dx*.008;pitch=Math.max(.03,Math.min(Math.PI-.03,pitch+dy*.008));}drag.lastX=e.clientX;drag.lastY=e.clientY;draw();});
 host.addEventListener('pointerup',e=>{if(!drag)return;const click=Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<4;drag=null;if(click){
 const rect=host.getBoundingClientRect(),ray=new T.Raycaster();ray.params.Line.threshold=Math.max(.025,distance*.0005);ray.setFromCamera(new T.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),camera);
 const hit=ray.intersectObjects(pickables,false).find(h=>{let o=h.object;while(o&&!o.userData.ref)o=o.parent;return o&&o.visible;});let picked=null;
 if(hit){picked=hit.object;while(picked&&!picked.userData.ref)picked=picked.parent;}
 if(!picked){const point=new T.Vector3(),z=api.readState().side==='bottom'?-thickness/2:thickness/2;if(ray.ray.intersectPlane(new T.Plane(new T.Vector3(0,0,1),-z),point)){let best=Infinity;for(const g of parts){if(!g.visible)continue;const box=new T.Box3().setFromObject(g),size=box.getSize(new T.Vector3()),area=size.x*size.y;if(point.x>=box.min.x-.1&&point.x<=box.max.x+.1&&point.y>=box.min.y-.1&&point.y<=box.max.y+.1&&area<best){picked=g;best=area;}}}}
 if(picked)api.selectRow(picked.userData.bomId);
 }});
 host.addEventListener('pointercancel',()=>drag=null);host.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(span*.06,Math.min(span*12,distance*Math.exp(e.deltaY*.001)));draw();},{passive:false});
 renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();status.textContent='3D 上下文已丢失，请切回简图或重新打开页面';});
 }catch(error){loading=false;status.textContent='3D 预览无法启动：'+error.message+'；可切回简图继续使用';console.warn(error);}}
function sync(){if(!ready||!active)return;const state=api.readState(),visible=new Set(api.visible());if(lastSide!==state.side){lastSide=state.side;reset();}
 for(const helper of outlines){scene.remove(helper);helper.geometry.dispose();helper.material.dispose();}outlines.length=0;const chosen=[];
 parts.forEach(g=>{g.visible=visible.has(g.userData.bomId)&&(state.boardMode!=='current'||g.userData.bomId===state.selectedBomId);const selected=g.visible&&g.userData.bomId===state.selectedBomId;
 g.traverse(m=>{if(!m.isMesh&&!m.isLine)return;if(m.userData.silkscreen)m.visible=selected;m.material.color.copy(m.userData.base);if(selected)m.material.color.setHex(0xef4444);else if(state.done[g.userData.bomId])m.material.color.setHex(0x22a655);if(m.material.emissive)m.material.emissive.setHex(selected?0x7f1010:0x000000);});
 if(selected){chosen.push(g.userData.ref);const box=new T.Box3().setFromObject(g);if(!box.isEmpty()){box.expandByScalar(.16);const helper=new T.Box3Helper(box,0xff7900);helper.material.depthTest=false;helper.material.depthWrite=false;helper.renderOrder=1000;scene.add(helper);outlines.push(helper);}}
 });
 selection.style.display=chosen.length?'block':'none';selection.textContent='已选：'+chosen.slice(0,14).join(', ')+(chosen.length>14?' …':'')+' · '+chosen.length+' 个器件';selection.dataset.count=String(chosen.length);draw();}
window.edakitIBOM3D={sync,inspect:()=>parts.map(g=>{const box=new T.Box3().setFromObject(g),point=box.getCenter(new T.Vector3()).project(camera),rect=host.getBoundingClientRect();return{ref:g.userData.ref,real:g.userData.real,selected:g.visible&&g.userData.bomId===api.readState().selectedBomId,size:box.getSize(new T.Vector3()).toArray(),surfaces:g.children.length,screen:{x:rect.left+(point.x+1)*rect.width/2,y:rect.top+(1-point.y)*rect.height/2}};}),view:()=>({near:camera.near,far:camera.far,outlines:outlines.length})};toggle.onclick=async()=>{active=!active;host.style.display=active?'block':'none';svg.style.visibility=active?'hidden':'';toggle.textContent=active?'简图':'3D 预览';toggle.setAttribute('aria-pressed',String(active));if(active){await init();sync();}};
document.getElementById('resetView').addEventListener('click',()=>{if(active){reset();summary();}});new ResizeObserver(draw).observe(host);
})();
