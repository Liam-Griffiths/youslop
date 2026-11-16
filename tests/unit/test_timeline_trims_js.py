"""Exercise actual trim gestures with GJS, without a browser or Node."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_trim_gestures(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text() for name in ('edit', 'sections', 'trims'))
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);};
const near=(a,b)=>Math.abs(a-b)<.00001;
class El {
 constructor(left='0px',width='118px'){this.style={left,width};this.dataset={};this.handlers={};this.children=[];this.offsetWidth=160;this.offsetHeight=20;this.offsetTop=22;}
 append(el){this.children.push(el);el.parent=this;} remove(){this.parent.children=this.parent.children.filter(n=>n!==this);} setPointerCapture(){} hasPointerCapture(){return false;}
 addEventListener(k,f){this.handlers[k]=f;} removeEventListener(k){delete this.handlers[k];}
}
const pic=new El(), later=new El('120px'), plus=new El('120px','');
pic.dataset.seg='0';
const track=new El(); track.querySelectorAll=s=>s.includes('.tl-pictures')?[pic]:[pic,later,plus];
const document={createElement:()=>new El(),addEventListener(k,f){this.key=f;},removeEventListener(){this.key=null;}};
const sc=new El();sc.scrollLeft=80;sc.clientWidth=400;
track.querySelector=()=>pic;
const $=s=>s==='#tl-scroll'?sc:track;
const hint=()=>track.children.find(n=>n.className==='tl-track-hint');
const visible=()=>{
 const n=hint(),left=parseFloat(n.style.left);
 check(n.parent===track&&left>=sc.scrollLeft+4&&left+n.offsetWidth<=sc.scrollLeft+sc.clientWidth-4,'hint clamped inside visible track');
 check(parseFloat(n.style.top)===24,'hint covers the command row, above pictures');
};
const q={id:'s1',start:0,duration:6,timing:{gap:{value:2}},word_times:[]};
const next={id:'s2',start:6,duration:6,timing:{gap:{value:1}},word_times:[]};
const segment={ref:'0',type:'picture',paragraphs:[q],start:0,duration:6};
let rows=[q,next];
const tlParas=()=>rows, tlSegs=()=>[segment,{start:6,duration:6}];
const sel={kind:'picture',id:'0',sid:'s1',t0:0,t1:6};
const tlItems=()=>[sel];
const TL={pid:'p',zoom:20,cur:7,selections:[sel],selection:sel,data:{total:12}};
const state={project:{id:'p',updated_at:1}};
const tlPause=()=>{},tlSelect=s=>{TL.selection=s;},tlFps=()=>30;
let message='',requests=[];
const tlMsg=s=>{message=s;};
const tlRefresh=async()=>{},tlInspector=()=>{},tlDraw=()=>{};
const crypto={randomUUID:()=> 'gesture'};
const api=async(path,opts)=>{requests.push({path,...opts});return state.project;};
let tlInspectorQueue=Promise.resolve();
const event=(x,extra={})=>({button:0,pointerId:1,clientX:x,altKey:true,
 preventDefault(){},stopPropagation(){this.stopped=true;},...extra});
const key=(k,extra={})=>({key:k,target:{closest:()=>null},...extra});
async function run(){
 tlWireTrims();
 check(pic.children.length===1&&pic.children[0].dataset.trimEdge==='end','only narrated right edge');
 const body=event(60,{altKey:false,target:{closest:()=>null}});pic.handlers.pointerdown(body);
 check(!TL.drag&&!body.stopped,'ordinary body press keeps scrub/section behavior');
 tlTrimPointer(event(120),pic,sel,[q],'end');pic.onpointermove(event(140));
 check(parseFloat(later.style.left)===140&&parseFloat(plus.style.left)===140,'ripple moves later rows and + buttons live');
 check(hint().textContent.includes('7.00 s, +1.00 · Ripple')&&!requests.length&&!message,'live length on track without player overlay or saves');
 visible();sc.scrollLeft=500;sc.handlers.scroll();visible();
 sc.scrollLeft=0;sc.clientWidth=120;hint().offsetWidth=112;sc.handlers.scroll();visible();
 check(hint().style.maxWidth==='112px','hint fits narrow viewport');
 sc.clientWidth=400;sc.handlers.scroll();visible();
 pic.onpointerup(event(140));await tlInspectorQueue;
 check(requests.length===1&&JSON.parse(requests[0].body).delta===1&&requests[0].editGesture==='gesture','one PATCH per drag');
 check(later.style.left==='120px','geometry restored for refresh');
 check(!hint()&&!sc.handlers.scroll,'drop removes hint and scroll listener');
 tlTrimPointer(event(120),pic,sel,[q],'end');pic.onpointermove(event(160));
 document.key({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});
 check(!TL.drag&&requests.length===1&&later.style.left==='120px','Escape cancels without a save');
 check(!hint()&&!sc.handlers.scroll,'Escape removes hint and scroll listener');
 tlTrimPointer(event(120),pic,sel,[q],'end');pic.onpointermove(event(160));pic.onlostpointercapture();
 check(!TL.drag&&requests.length===1,'capture loss cancels');
 check(!hint()&&!sc.handlers.scroll,'capture loss removes hint');
 tlTrimPointer(event(120),pic,sel,[q],'end');pic.onpointermove(event(160));pic.onpointercancel();
 check(!hint()&&!sc.handlers.scroll&&requests.length===1,'pointer cancel removes hint');
 const plan=tlTrimPlan([q],'end',10,true);
 check(plan.delta===1&&plan.changes.reduce((s,c)=>s+c.delta,0)===0,'roll limited by neighbour silence');
 check(tlTrimPlan([q],'end',-10,false).delta===-2,'speech clamp');
 check(!!tlTrimPlan([q],'start',1,false).hint,'narrated start refuses');
 check(tlSnap(7.1,[{start:7,end:7}],30,6,20,false).t===7,'playhead/edit snap candidate');
 check(tlSnap(7.1,[{start:7,end:7}],30,6,20,true).t===7.1,'Alt bypass');
 check(tlTrimKey(key(']')),'end keyboard trim');await tlInspectorQueue;
 check(JSON.parse(requests.at(-1).body).delta===1,'trim end to playhead');
 tlTrimKey(key('}',{shiftKey:true}));await tlInspectorQueue;
 check(near(JSON.parse(requests.at(-1).body).delta,1/30),'Shift end one frame');
 check(!tlTrimKey(key(']',{target:{closest:()=>({})}})),'text fields ignore shortcuts');
 TL.selection={kind:'cue'};check(!tlTrimKey(key(']')),'other lanes keep navigation');TL.selection=sel;
 q.insert={kind:'clip',shoot_id:'s',source_id:'f',in_s:2,out_s:8,seconds:6};
 tlTrimSources.set('s/f',20);rows=[q,next];
 check(tlTrimPlan([q],'slip',100,false).delta===12,'slip source end bounded');
 check(tlTrimPlan([q],'slip',-100,false).delta===-2,'slip source start bounded');
 check(near(tlTrimPlan([q],'start',-100,false).delta,-5.95),'insert minimum length');
 tlTrimKey(key('{',{shiftKey:true}));await tlInspectorQueue;
 check(near(JSON.parse(requests.at(-1).body).delta,-1/30),'Shift start trims one frame');
 state.project.kind='clip';check(!tlTrimKey(key(']')),'clip project retains word trim UI');
 print('trim gestures passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'trims.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'trim gestures passed' in result.stdout
