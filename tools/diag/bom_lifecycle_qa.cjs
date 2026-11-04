// Isolated synthetic pages only; Browser plugin not available via a listed browser skill.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.EDAKIT_PLAYWRIGHT_MODULE||'playwright');
const web=path.resolve(__dirname,'../../src/edakit/server/web');
(async()=>{const browser=await chromium.launch({channel:process.platform==='win32'?'msedge':undefined,headless:true});try{
const p=await browser.newPage({viewport:{width:1100,height:800}}),errors=[],calls=[],previews=[];
p.on('pageerror',e=>errors.push(e.message));
const headers=['序号','类型','描述','位号','值','封装','数量','厂家','厂家型号','物料编码'];
const rows=Array.from({length:500},(_,i)=>Object.assign(Object.fromEntries(headers.map(h=>[h,h==='序号'?i+1:h==='数量'?1:'sample '+i])),{id:''+i,editId:''+i,included:true,issues:[],codeEditable:true}));
let complete=false;
await p.route('http://bom.local/**',async r=>{const u=new URL(r.request().url());
if(u.pathname==='/api/bom/settings')return r.fulfill({json:{mapping:{描述:'Description',值:'Value'},typeProperty:'Type',templateName:'test'}});
if(u.pathname==='/api/properties/request')return r.fulfill({json:{job:'snapshot'}});
if(u.pathname==='/api/properties/status')return r.fulfill({json:{state:'done',snapshot:{design:'test|test.dsn'}}});
if(u.pathname==='/api/bom/preview'){previews.push(JSON.parse(r.request().postData()));return r.fulfill({json:{headers,rows,design:'test|test.dsn',exportRows:500,exportQuantity:500}});}
if(u.pathname==='/api/bom/webtest'){const body=JSON.parse(r.request().postData());calls.push(body);return r.fulfill({json:body.action==='report'?{containsMaterialValues:false}:{state:complete?'done':'running',busy:!complete,run:'run1',message:complete?'完成':'读取中',summary:{models:500,matched:500}}});}
if(u.pathname==='/api/workbench/navigation')return r.fulfill({json:{revision:1,tab:'bom'}});
if(u.pathname.indexOf('/auth/')===0&&!u.pathname.endsWith('/bom'))return r.fulfill({contentType:'text/html',body:'<title>Other panel</title><p>Other panel</p>'});
const name=u.pathname.indexOf('/auth/')===0?'bom.html':u.pathname==='/'?'workbench.html':u.pathname.split('/').pop();
return r.fulfill({body:fs.readFileSync(path.join(web,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
});
await p.addInitScript(()=>{window.__edakitToken='test';});await p.goto('http://bom.local/');
const frame=await(await p.locator('#panel-bom').elementHandle()).contentFrame();await frame.locator('#search').waitFor();
assert((await p.title()).includes('工作台'));assert((await frame.title()).includes('BOM'));assert.equal(await frame.locator('#webTest > *').count(),0);assert.equal(calls.length,0);
await frame.locator('#refresh').click();await frame.locator('#grid tbody tr').last().waitFor();assert.equal(await frame.locator('#grid tbody tr').count(),500);
const mutations=await p.evaluate(async()=>{let n=0;const o=new MutationObserver(m=>{n+=m.length;});o.observe(document.getElementById('panel-bom'),{attributes:true});for(let i=0;i<20;i++)document.getElementById('tab-bom').click();await new Promise(r=>setTimeout(r,50));o.disconnect();return n;});assert.equal(mutations,0);
await frame.evaluate(()=>{const before=window.edakitBomPageMetrics.headerPasses;for(let i=0;i<60;i++)window.dispatchEvent(new Event('resize'));window.headerBefore=before;});await p.waitForTimeout(80);
assert.equal(await frame.evaluate(()=>window.edakitBomPageMetrics.headerPasses-window.headerBefore),1);
await frame.locator('#tableBody').evaluate(e=>{e.scrollTop=800;e.scrollLeft=200;});await p.waitForTimeout(50);
async function aligned(){const gap=await frame.evaluate(()=>{const a=document.querySelector('#frozenGrid th'),b=document.querySelector('#grid tbody td');return Math.abs(a.getBoundingClientRect().left-b.getBoundingClientRect().left);});assert(gap<1,'Header alignment '+gap);}
await aligned();await p.setViewportSize({width:700,height:600});await p.waitForTimeout(100);await aligned();
await frame.locator('#search').fill('sample 499');await p.waitForTimeout(300);assert.equal(await frame.locator('#grid tbody tr').count(),1);
await frame.locator('#search').fill('');await p.waitForTimeout(300);await frame.locator('#webTestToggle').click();assert.equal(calls.length,0);
assert.equal(await frame.locator('#webProbe,#webClear').count(),0);assert(!(await frame.locator('#webCancel').isVisible()));assert(!(await frame.locator('#webGetReport').isVisible()));assert(!(await frame.locator('#webDiagnostics').getAttribute('open')));
assert.deepEqual(await frame.locator('#webTest button:visible').allTextContents(),['登录并自动匹配']);
await frame.locator('#webUrl').fill('https://alidocs.dingtalk.com/i/nodes/test');await frame.locator('#webStart').click();await frame.locator('#webStatus').filter({hasText:'读取中'}).waitFor();assert.equal(calls.filter(x=>x.action==='auto').length,1);assert.equal(previews.length,1,'Starting first match must not rebuild BOM');
assert(await frame.locator('#webCancel').isVisible());
assert.equal(calls[0].snapshot,'snapshot');assert(Array.isArray(calls[0].excluded));
await p.locator('#tab-properties').click();const count=calls.length;await p.waitForTimeout(1000);assert.equal(calls.length,count,'Hidden matching panel must not poll');complete=true;
await p.locator('#tab-bom').click();await frame.locator('#webStatus').filter({hasText:'已自动更新 BOM'}).waitFor();assert.equal(previews.length,2);assert.equal(previews[1].webMatch,'run1');
await p.waitForTimeout(900);assert.equal(previews.length,2,'Apply once');const statuses=calls.filter(x=>x.action==='status');assert(statuses.length>0);assert.deepEqual(Object.keys(statuses[0]).sort(),['action','session']);
assert(!(await frame.locator('#webCancel').isVisible()));
if(process.env.EDAKIT_QA_OUT){fs.mkdirSync(process.env.EDAKIT_QA_OUT,{recursive:true});await p.screenshot({path:path.join(process.env.EDAKIT_QA_OUT,'bom-simplified.png')});}
await frame.locator('#webDiagnostics summary').click();await frame.locator('#webGetReport').click();await frame.locator('#webReport').waitFor();const report=JSON.parse(await frame.locator('#webReport').inputValue());assert(report.pagePerformance.headerPasses>0);assert.equal(report.containsMaterialValues,false);
assert.equal(errors.length,0,errors.join('\n'));if(process.env.EDAKIT_QA_OUT){fs.mkdirSync(process.env.EDAKIT_QA_OUT,{recursive:true});await p.screenshot({path:path.join(process.env.EDAKIT_QA_OUT,'bom-lifecycle.png')});}
console.log('PASS BOM lifecycle: lazy init, idle no matching, same tab, coalesced header, resize/scroll alignment, filter, hidden pause/resume, full start/minimal poll, single apply, diagnostics');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
