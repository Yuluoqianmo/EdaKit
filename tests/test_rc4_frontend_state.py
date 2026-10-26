"""Execute shipped ES5 persistence/row-sizing/preview logic with Node's VM."""
import json
import shutil
import subprocess
from pathlib import Path
import esprima
import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node') or 'C:/Users/32657/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'


def functions(source,names):
    tree=esprima.parseScript(source,{'range':True}).toDict()
    found={}
    def walk(node):
        if not isinstance(node,dict):return
        if node.get('type')=='FunctionDeclaration' and node['id']['name'] in names:
            found[node['id']['name']]=source[node['range'][0]:node['range'][1]]
        for value in node.values():
            if isinstance(value,dict):walk(value)
            elif isinstance(value,list):
                for item in value:walk(item)
    walk(tree)
    assert set(found)==set(names)
    return '\n'.join(found.values())


def test_shipped_frontend_state_logic(tmp_path):
    if not Path(NODE).exists() and not shutil.which(NODE):pytest.skip('Node unavailable')
    props=(ROOT/'frontend/properties/properties.js').read_text(encoding='utf-8')
    bom=(ROOT/'frontend/bom/bom.js').read_text(encoding='utf-8')
    propfunc=functions(props,['readStore','persistSnapshot','flushDraft','persist','restoreDrafts','archiveDraft','resizeRows'])
    bomfunc=functions(bom,['project'])
    script=r'''
const vm=require('vm'),assert=require('assert');
const store={},timers=[],nodes={};
const ctx={JSON,Date,Math,Object,String,localStorage:{getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v},removeItem:k=>delete store[k]},sessionStorage:{getItem:()=>null},setTimeout:f=>(timers.push(f),timers.length),clearTimeout:()=>{},storeKey:'test',snapshot:null,snapshotJob:'',scope:'design',drafts:{},conflicts:{},history:[],pair:null,savedSnapshot:null,storageBlocked:false,quotaWarned:false,orphanGroups:[],draftTimer:null,count:x=>Object.keys(x).length,drawOrphans:()=>{},message:()=>{},$:k=>(nodes[k]||(nodes[k]={}))};
vm.createContext(ctx);vm.runInContext(PROPS,ctx);
store.test=JSON.stringify({snapshot:{design:'dsn',rows:[]},job:'j',drafts:{a:{id:'0/1',name:'Value',value:'1K'}}});ctx.restoreDrafts();assert(ctx.snapshot);assert(JSON.parse(store['test:snap']).pair);ctx.drafts.a.value='2K';ctx.persist();timers.pop()();assert.equal(JSON.parse(store.test).drafts.a.value,'2K');
const snap=JSON.parse(store['test:snap']);snap.pair.rev='wrong';store['test:snap']=JSON.stringify(snap);ctx.snapshot=null;ctx.restoreDrafts();assert(!ctx.snapshot);assert.equal(JSON.parse(store['test:orphan']).length,1);ctx.restoreDrafts();assert.equal(JSON.parse(store['test:orphan']).length,1);
const cells=[{style:{height:'120px'},content:18,get scrollHeight(){return Math.max(parseFloat(this.style.height),this.content)}}];ctx.resizeRows([{querySelectorAll:()=>cells}]);assert.equal(cells[0].style.height,'35px');
let callback,rendered=0;const bt=[];const b={editVersion:0,previewTimer:null,job:'j',busy:false,data:null,clearTimeout:()=>{},setTimeout:f=>(bt.push(f),bt.length),request:()=>({}),api:(p,q,cb)=>{callback=cb},render:()=>rendered++,message:()=>{},save:()=>{}};vm.createContext(b);vm.runInContext(BOM,b);b.project();bt.shift()();b.project();callback(null,{rows:[],exportRows:0});assert.equal(rendered,0);bt.shift()();callback(null,{rows:[],exportRows:0});assert.equal(rendered,1);console.log('PASS shipped storage pairing, orphan dedup, debounce, row shrink, stale preview');
'''.replace('PROPS',json.dumps(propfunc)).replace('BOM',json.dumps(bomfunc))
    path=tmp_path/'state.cjs';path.write_text(script,encoding='utf-8')
    r=subprocess.run([NODE,str(path)],capture_output=True,text=True,timeout=20)
    assert r.returncode==0,r.stdout+r.stderr
