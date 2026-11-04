(function(){'use strict';
var initialized=false;
function initialize(){if(initialized)return;initialized=true;
var $=function(id){return document.getElementById(id);},panel=$('webTest'),timer=null,front=[],applied='',last=null,applyStarted=0,activeSnapshot='',starting=false,pollPending=false,disposed=false;
function visible(){return !disposed&&!document.hidden&&(!window.frameElement||(' '+window.frameElement.className+' ').indexOf(' active ')>=0);}
function el(tag,text){var e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
function add(tag,text,parent){var e=el(tag,text);(parent||panel).appendChild(e);return e;}
add('h2','钉钉物料自动匹配');
add('p','登录钉钉后自动匹配，仅更新本次 BOM，不修改原理图或源表。');
var config=add('div');config.className='webAutoLink';
var label=add('label','物料总表链接',config),url=add('input',undefined,label);url.id='webUrl';url.type='url';url.placeholder='粘贴钉钉知识库表格链接（首次填写）';
try{url.value=sessionStorage.getItem('edakit-web-document')||'';}catch(e){}
var buttons=add('div',undefined,config);buttons.className='webActions';
function button(id,text,fn,parent){var b=el('button',text);b.id=id;b.onclick=fn;(parent||buttons).appendChild(b);return b;}
var status=add('p','准备就绪');status.id='webStatus';status.setAttribute('role','status');
var progress=add('progress');progress.id='webProgress';progress.max=1;progress.value=0;progress.hidden=true;
var stats=add('p');stats.id='webStats';
var details=add('details');details.id='webDiagnostics';add('summary','故障诊断',details);
add('p','匹配异常时可复制报告协助排查。断开连接会清除本次网页匹配结果，恢复本地编码表。',details);
var report=add('textarea',undefined,details);report.id='webReport';report.readOnly=true;report.hidden=true;report.setAttribute('aria-label','匹配计时报告');
function say(t,error){status.textContent=t;status.className=error?'error':'';}
function context(full){var c=window.edakitBomWebTest.context(!full);if(!c){say('请先读取整个工程',true);return null;}return c;}
function api(body,done){var x=new XMLHttpRequest(),start=Date.now();x.open('POST','/api/bom/webtest',true);x.timeout=15000;x.setRequestHeader('Content-Type','application/json');x.onload=function(){var r;try{r=JSON.parse(x.responseText);}catch(e){done('匹配服务返回无效');return;}if(x.status>=400){done(r.message||r.error||'匹配请求失败');return;}if(body.action!=='status'&&front.length<500)front.push({stage:'request_'+body.action+'_ms',ms:Date.now()-start});done(null,r);};x.onerror=function(){done('匹配服务连接失败');};x.ontimeout=function(){done('服务响应超时，可查看诊断状态，请勿重复启动');};x.send(JSON.stringify(body));}
function update(r){last=r;if(!visible())return;var busy=!!r.busy;say(r.message,r.state==='error'||r.state==='cancelled');progress.hidden=!busy;progress.max=r.total||1;progress.value=r.done||0;var s=r.summary||{};stats.textContent=s.models?'匹配 '+(s.matched||0)+' / '+s.models+'；本次未命中 '+(s.unmatchedInRange||0)+'，冲突 '+(s.conflicts||0)+'；耗时 '+((s.batch_ms||0)/1000).toFixed(2)+' 秒（不含登录等待）':'';
$('webStart').disabled=busy||starting;$('webClose').disabled=busy||starting;$('webCancel').disabled=!busy;$('webCancel').hidden=!busy;url.disabled=busy||starting;
if(busy){clearTimeout(timer);timer=setTimeout(poll,700);}else{clearTimeout(timer);if(r.state==='done'&&r.run&&r.run!==applied){var c=context();if(!c||c.snapshot!==activeSnapshot){say('工程已重新读取，请重新自动匹配；旧结果未应用',true);return;}applied=r.run;applyStarted=Date.now();window.edakitBomWebTest.apply(r.run);say('正在自动更新本次 BOM…');}}
}
function poll(){timer=null;if(pollPending||!visible())return;var c=context();if(!c)return;pollPending=true;api({action:'status',session:c.session},function(e,r){pollPending=false;if(e){say(e,true);return;}update(r);});}
function start(){if(starting||(last&&last.busy))return;var c=context(true);if(!c)return;if(!url.value.trim()){say('首次使用请粘贴物料总表链接，之后只需登录',true);url.focus();return;}starting=true;front=[];applied='';activeSnapshot=c.snapshot;report.hidden=true;window.edakitBomWebTest.clear();try{sessionStorage.setItem('edakit-web-document',url.value.trim());}catch(e){}var body={action:'auto',url:url.value.trim()};Object.keys(c).forEach(function(k){body[k]=c[k];});$('webStart').disabled=true;url.disabled=true;say('正在打开钉钉，你只需完成登录…');api(body,function(e,r){starting=false;if(e){$('webStart').disabled=false;url.disabled=false;say(e,true);return;}update(r);});}
button('webStart','登录并自动匹配',start).className='primary';
var cancel=button('webCancel','取消匹配',function(){var c=context();if(c)api({action:'cancel',session:c.session},function(e,r){if(e)say(e,true);else update(r);});});cancel.disabled=true;cancel.hidden=true;
function getReport(){var c=context();if(!c)return;api({action:'report',session:c.session},function(e,r){if(e){say(e,true);return;}r.frontend=front.slice();var m=window.edakitBomPageMetrics||{};r.pagePerformance={initMs:m.initMs,firstYieldMs:m.firstYieldMs,headerPasses:m.headerPasses};report.value=JSON.stringify(r,null,2);report.hidden=false;details.open=true;report.focus();report.select();try{document.execCommand('copy');}catch(x){}say('诊断报告已选中，可 Ctrl+C 复制；不包含物料内容和凭证');});}
button('webGetReport','复制诊断报告',getReport,details);
button('webClose','断开连接',function(){var c=context();if(!c)return;applied=last&&last.run||'';window.edakitBomWebTest.clear();api({action:'close',session:c.session},function(e,r){if(e)say(e,true);else update(r);});},details);
window.edakitWebTestTiming=function(item){if(front.length<500)front.push(item);if(applied&&item.stage==='bom_render_ms'){if(applyStarted){front.push({stage:'apply_total_ms',ms:Date.now()-applyStarted});applyStarted=0;}say('已自动更新 BOM。请核对匹配统计；未命中和冲突项保留待处理。');}};
$('webTestToggle').onclick=function(){panel.hidden=false;if(url.value.trim())start();else url.focus();};
function visibility(){clearTimeout(timer);timer=null;if(visible()&&last){if(last.busy)poll();else update(last);}}
window.addEventListener('edakitvisibilitychange',visibility);
document.addEventListener('visibilitychange',visibility);
window.addEventListener('unload',function(){disposed=true;clearTimeout(timer);});
}
document.getElementById('webTestToggle').onclick=function(){initialize();document.getElementById('webTestToggle').onclick();};
})();
