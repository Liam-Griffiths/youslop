"""Finish-stage interactions without a browser, renders, uploads or model calls."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_publish_lifecycle(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(p).read_text() for p in (
        'static/js/shell.js', 'static/js/tabs/render.js', 'static/js/tabs/thumb.js',
        'static/js/timeline/draw.js'))
    harness = r'''
const loop = new imports.gi.GLib.MainLoop(null, false);
function check(ok, msg) { if (!ok) throw new Error(msg); }
const body={innerHTML:''}, thumb={innerHTML:''}, progress={innerHTML:''}, upload={disabled:false};
const $=s=>s==='#tabbody'?body:s==='#publish-thumb-tools'?thumb:s==='#publish-progress'?progress:
  s.includes('doYoutubeUpload')?upload:null;
function node(){return {style:{},children:[],append(...items){this.children.push(...items);},querySelector:()=>null};}
const document={querySelectorAll:()=>[],createElement:node};
const esc=s=>String(s??'').replaceAll('<','&lt;').replaceAll('"','&quot;');
const fmtTime=t=>String(t);
const formatPicker=()=>'<div>Video style</div>';
const isCut=()=>false, chapterCount=()=>0, videoTag=()=>'<video id="render-output"></video>';
const ensureChannelsLoaded=async()=>{};
const state={stage:'publish',project:{id:'p1',style:{format:'kenburns',vignette:0,ken_burns_amount:0,
 transition:0,music_db:-18},slides:[{}],recorded_count:1,channel_id:'c1',
 title:'Test',idea:'Test',thumb:{},youtube:{connected:true},description:'Description'},
 templates:[],endTemplates:[],youtubeCategories:[],thumbStyles:[],channels:[]};
let posts=[], ready=false, saves=0, actionMode=false;
const finish={check:{findings:[]},review:{},
 segments:[{type:'picture',paragraphs:[{start:1,chapter:'Chapter'}]}, {type:'sponsor',start:5}],total:10};
const api=async(path, opts={})=>{
 if(opts.method && opts.method!=='GET') {
   posts.push(path);
   if(actionMode) return {proposal:{field:'title',old:'Old',new:'New'}};
   throw new Error('unexpected write');
 }
 if(path.endsWith('/timeline')) return finish;
 if(path.endsWith('/stages')) return [{id:'publish',status:ready?'ready':'todo'}];
 return [];
};
const toast=()=>{};
const tlMount=()=>{throw new Error('Timeline must stay in Edit');};
let thumbPending={}, thumbTimer;
const clearTimeout=()=>{}, setTimeout=()=>{saves++;};
async function run(){
 check(stageTab('publish','thumb')==='render' && stageTab('publish','render')==='render','old subroutes use merged screen');
 await paintRender();
 check(posts.length===0,'page load never renders, uploads or calls model');
 for(const label of ['Check','Review by Claude','Render','Thumbnail','Description & chapters','Upload'])
   check(body.innerHTML.includes(label),'missing finish step '+label);
 check(body.innerHTML.includes('Music bed') && body.innerHTML.includes('Pause between paragraphs'),'sound controls kept');
 check(thumb.innerHTML.includes('Headline') && thumb.innerHTML.includes('Draw thumbnail'),'thumbnail tools mounted');
 check(body.innerHTML.includes('Sponsor') && body.innerHTML.includes('Chapter'),'chapters include sponsors');
 check(upload.disabled,'upload blocked before render');
 const before=body.innerHTML;
 saveThumb({uppercase:true},true);
 check(body.innerHTML===before && saves===1,'thumbnail repaint preserves finish screen');
 state.project.render={output:'out/test.mp4',duration:10,size_mb:1,slides:1,verify:{p0:0,p1:1}};
 ready=true;
 await paintRender();
 check(!upload.disabled && body.innerHTML.includes('Finished video'),'verified current render enables upload and output');
 check(body.innerHTML.includes('Verified after render') && body.innerHTML.includes('Show in folder'),'output controls present');
 ready=false; await doYoutubeUpload();
 check(posts.length===0,'upload rechecks readiness after project edits');
 await paintRender(); check(upload.disabled,'stale render blocks upload');
 ready=true; state.project.render.verify.p0=1;
 await paintRender(); check(upload.disabled,'P0 verification blocks upload');
 state.job={kind:'render',lines:['Rendering 4 segments','  segments 2/4'],elapsed:3};
 paintPublishProgress();
 check(progress.innerHTML.includes('value="2" max="4"'),'real segment progress');
 check(posts.length===0,'all repaints remain read only');
 // Shared finding actions must use Publish's project and refresh callbacks,
 // even though Timeline has never mounted (TL is deliberately undefined).
 actionMode=true;
 let refreshed=0, applied=0;
 const row=node();
 tlFixButtons(row,{id:'note1',fix:{kind:'title'}},true,{
   pid:'p1',refresh:async()=>refreshed++,refreshProject:async()=>applied++,
 });
 await row.children[2].onclick();
 check(refreshed===1 && posts.at(-1)==='/api/projects/p1/review/note1','keep refreshes Publish');
 await row.children[0].onclick();
 const proposal=row.children.at(-1);
 await proposal.children[1].onclick();
 check(applied===1,'apply refreshes Publish without mounting Edit');
}
let failure;
run().catch(e=>failure=e).finally(()=>loop.quit());
loop.run();
if(failure) throw failure;
'''
    path = tmp_path / 'publish.js'
    path.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
