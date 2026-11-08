"""Browser queue and slide application contracts using GJS, without Chromium."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_preview_queue_and_application(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = Path('static/js/tabs/blocks_browser.js').read_text()
    script = tmp_path / 'blocks.mjs'
    script.write_text('''
const esc = s => String(s ?? '');
let calls = [], resolve;
const api = (url,options={}) => {
  calls.push([url,JSON.parse(options.body || '{}')]);
  return new Promise(r => { resolve = r; });
};
const document = {querySelectorAll:() => []};
const target = {isConnected:true, querySelector:() => null,
  matches:() => true, classList:{contains:() => false}};
const assert = (ok,msg) => { if (!ok) throw Error(msg); };
''' + source + '''
const b = {ref:'number_slam'};
const first = requestBlockPreview(b,'16:9','trial',{},target);
await requestBlockPreview(b,'16:9','motion',{},target);
await requestBlockPreview(b,'9:16','trial',{title:'Newest'},target);
assert(calls.length === 1,'one in flight');
resolve({stale:true});
await Promise.resolve(); await Promise.resolve();
assert(calls.length === 2,'one pending request replaces older pending');
assert(calls[1][1].aspect === '9:16' && calls[1][1].values.title === 'Newest','newest wins');
resolve({disabled:true}); await first;
assert(!blockPreviewBusy,'gate released');
const controls = Object.fromEntries(['play','scrub','time','loop'].map(k => [k,{}]));
const player = {querySelector:key => controls[key.replace('#block-player-','')]};
const video = {duration:5,currentTime:0,paused:true,pause() { this.paused=true; },play() { this.paused=false; return Promise.resolve(); }};
bindBlockPlayer(player,video);
assert(controls.scrub.max === 5 && controls.play.textContent === 'Play','metadata bound');
controls.scrub.value = '2.25'; controls.scrub.oninput();
assert(video.currentTime === 2.25 && controls.time.textContent === '2.25 / 5.00 s','scrub sets video time');
controls.play.onclick(); assert(!video.paused,'play control');
controls.play.onclick(); assert(video.paused,'pause control');
controls.loop.onchange({target:{checked:false}}); assert(!video.loop,'loop toggle');
const selection = {block:'number_slam',vars:{title:'Mine'}};
const apply = applyBlockToSlide('p1','s1',selection);
assert(calls.at(-1)[0] === '/api/projects/p1/slides/s1','existing PATCH path');
assert(calls.at(-1)[1].cues.blocks[0] === selection ||
       calls.at(-1)[1].cues.blocks[0].vars.title === 'Mine','scratch applied');
assert(Object.keys(calls.at(-1)[1].cues).join() === 'blocks','other cue keys absent');
resolve({}); await apply;
assert(blockTrialField('title',{type:'text',default:'sample',max_length:20},0).includes('type="text"'),'typed input');
assert(blockTrialField('data',{type:'table',default:[]},0).includes('Paste CSV'),'table entry');
const status = {}, inline = {}, attributes = {};
const table = {id:'block-var-0', dataset:{key:'rows',type:'table'}, setAttribute:(k,v) => attributes[k]=v};
const detail = {querySelector:key => key === '#block-trial-status' ? status : inline, querySelectorAll:() => [table]};
blockTrialError(detail,'rows row 2 column value: expected number');
assert(inline.textContent === status.textContent && inline.textContent.includes('row 2 column value'),'row/column error inline');
assert(attributes['aria-invalid'] === 'true','field marked invalid');
blockTrialError(detail,'CSV row 1: expected 2 columns');
assert(inline.textContent.includes('CSV row 1'),'CSV parser errors inline');
blockTrialError(detail,'Refreshing preview…');
assert(inline.textContent === '' && attributes['aria-invalid'] === 'false','old error cleared');
const state = {project:{aspect:'portrait',slides:[{id:'s1',cues:{blocks:[selection]}}]}};
let opened;
renderBlocks = async (path,options) => { opened = {path,options}; };
await openBlockPicker('p1','s1');
assert(opened.path === selection.block && opened.options.selection === selection,'edit opens saved scratch');
assert(opened.options.aspect === '9:16' && calls.length === 3,'opening edit does not apply');
await openChannelBlockBrowser('ctest','number_slam');
assert(opened.options.mode === 'channel' && opened.options.channel === 'ctest','reusable channel mode');
const nodes = {'#block-description':{value:'A receipt'},'#block-result':{textContent:''},'#blocks-grid':{}};
const $ = key => nodes[key];
const pr = {id:'preset1',scope:'project',name:'Our chapter',block:'number_slam',values:{value:9},badge:'This project'};
blocksBrowser = {presets:[pr],items:[],options:{aspect:'9:16'}};
assert(blockPresetCard(pr).includes('This project'),'preset badge');
assert(blockPresetCard({...pr,missing:true}).includes('Block missing'),'missing block labelled');
assert(blockPriority({ref:'number_slam',channels:[]},[pr],'c1') > blockPriority({ref:'other',channels:[]},[pr],'c1'),'project preset ranks first');
const beforePresets = calls.length;
const standalonePresets = loadBlockPresets({project:'p1'},[{id:'c1',name:'Other channel'}]);
await Promise.resolve(); await Promise.resolve();
assert(calls.length === beforePresets+1 && calls.at(-1)[0] === '/api/projects/p1/block-presets','standalone excludes other channel presets');
resolve([pr]);
assert((await standalonePresets)[0].badge === 'This project','project scope badge');
const gridPaint = paintBlocksGrid, detailPaint = paintBlockDetails;
let detailAspect;
paintBlocksGrid = () => {};
paintBlockDetails = aspect => { detailAspect = aspect; };
chooseBlockPreset(pr);
assert(blocksBrowser.trial.values.value === 9 && blocksBrowser.trial.preset.scope === 'project','values and provenance selected');
assert(detailAspect === '9:16','project aspect retained');
paintBlocksGrid = gridPaint; paintBlockDetails = detailPaint;

const location = {hash:'#/blocks'};
let complete;
const watchJob = (id,kind,fn) => { assert(kind === 'create block','creation job'); complete = fn; };
blocksBrowser = {selected:'number_slam',options:{mode:'pick'}};
const before = calls.length, button = {};
assert(blockCreationResult() === '' && calls.length === before,'painting result never calls model');
const creation = describeBlock(button);
assert(button.disabled && calls.at(-1)[0] === '/api/blocks/describe','explicit Create only');
assert(calls.at(-1)[1].description === 'A receipt','description retained');
resolve({job:'jcreate'}); await creation;
await complete({result:{id:'user/receipt',usage:[{usage:{input_tokens:12,output_tokens:6}}]}});
assert(opened.path === 'user/receipt' && opened.options.mode === 'pick','new block selected in same browser mode');
assert(blockCreationResult().includes('12 input tokens'),'usage preserved');
await complete({error:'Check failed'});
assert(blockCreationResult().includes('Check failed'),'job errors preserved');
blockPreviewAs = 'channel:ctheme';
for (const kind of ['trial','motion']) {
  const themed = requestBlockPreview(b,'16:9',kind,{},target);
  assert(calls.at(-1)[1].theme_context.owner === 'ctheme','trial and hover inherit Preview as');
  resolve({disabled:true}); await themed;
}
const visible = {isConnected:true,dataset:{themedRef:'title_card',themedAspect:'16:9'}};
const hidden = {...visible,isConnected:false};
themedPosterQueue = [{target:visible,browser:blocksBrowser,choice:blockPreviewAs},
                     {target:hidden,browser:blocksBrowser,choice:blockPreviewAs}];
const beforePosters = calls.length, posters = drainThemedPosters();
assert(calls.length === beforePosters+1 && calls.at(-1)[1].ref === 'title_card','one visible poster at a time');
resolve({posters:[{url:'/fixture.png'}]}); await posters;
assert(visible.src === '/fixture.png' && calls.length === beforePosters+1,'removed cards never render');
blockPreviewAs = '';
const defaults = requestBlockPreview(b,'16:9','trial',{},target);
assert(!calls.at(-1)[1].theme_context,'Default restores authored block theme');
resolve({disabled:true}); await defaults;



''')
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
