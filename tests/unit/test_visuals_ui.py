"""Picker contracts with synthetic paragraphs; no browser, network or render."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_visual_picker_js(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required for plain JS picker checks')
    bootstrap = r'''
      import GLib from 'gi://GLib';
      const nodes = {}, $ = key => nodes[key] ||= {innerHTML:'', value:'map', textContent:''};
      const esc = s => String(s ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
      const cutInfo = () => null;
      const isStage = f => f === 'stage', isCut = f => f === 'loudmouth';
      const fmtTime = s => s+'s', thumbUrl = c => '/thumb/'+c.id;
      const document = {querySelectorAll: () => []};
      const loadBlockPresets = async () => [], blockPriority = () => 0;
      const blockPoster = b => `<img src="/poster/${b.ref}" alt="${b.name}">`;
      const location = {}, state = {tab:'media', project:{id:'p1',aspect:'landscape',style:{format:'kenburns'},
        slides:Array.from({length:40},(_,i)=>({id:'s'+i,title:'Picture <'+i+'>',narration:'Paragraph '+i,
          visual_note:'A map',prefer_kind:'image',take:{duration: i+1},candidates:[
            {id:'c'+i,provider:'library',title:'Map '+i,kind:'image',focal:[.2,.3]}],chosen_id:'c'+i}))}};
      const assert = (v,m) => {if(!v) throw Error(m);};
      let picked, pickKind;
      const openLocalMediaPicker = (kind, fn) => { pickKind = kind; picked = fn; };
      let calls=[];
      const api = async (url, opts={}) => {
        calls.push([url,JSON.parse(opts.body || '{}')]);
        if (url === '/api/projects/p1') return JSON.parse(JSON.stringify(state.project));
        if (url === '/api/footage/shoots') return [];
        if (url === '/api/blocks') return ['number_slam','percentage_ring','quote_card'].map(ref =>
          ({ref,name:ref,kind:'segment',aspects:['16:9','9:16'],category:'data'}));
        if (url.endsWith('/block-suggestions')) return [{block:'number_slam',vars:{value:42},reason:'Number'}];
        if (url.endsWith('/preview')) return {disabled:true};
        if (url.endsWith('/footage/fill')) return {slides:state.project.slides};
        return {slide:{candidates:[{id:'ft1',provider:'footage',kind:'video',title:'Boats',
          in_s:2,out_s:10,labels:['harbour']}],chosen_id:'c0'}};
      };
      const saveSlide = async (sid, fields) => {
        calls.push([sid,fields]);
        const s = state.project.slides.find(s => s.id === sid);
        const cues = {...s.cues,...fields.cues};
        Object.assign(s,fields);
        if (fields.cues) s.cues = cues;
        return s;
      };
    '''
    checks = r'''
      const p = state.project;
      paintMedia();
      let html = $('#tabbody').innerHTML;
      assert(html.includes('visual-grid') && html.includes('visual-sequence'), 'shared shell');
      assert((html.match(/class="btn ghost visual-group"/g)||[]).length === 40, 'all groups');
      assert(html.includes('Search footage') && !html.includes('cut/'), 'footage picker, no render URL');
      assert(html.includes('Picture &lt;0>'), 'escape narration');
      await Promise.resolve();
      assert(calls.length === 1 && calls[0][0] === '/api/footage/shoots', 'metadata only on paint');
      selectVisualSource('Library');
      html = $('#tabbody').innerHTML;
      assert((html.match(/<img /g)||[]).length === 42, 'only group thumbnails, selected preview and selected candidates');
      assert((html.match(/<img /g)||[]).length === (html.match(/loading="lazy"/g)||[]).length, 'every image lazy');
      await choose('s0','c0');
      assert(calls.at(-1)[1].chosen_id === 'c0', 'shared choose/save path');
      await searchVisual('s0','Library');
      assert(calls.at(-1)[1].source === 'library', 'local source routing');
      pickVisualLibrary('s0');
      assert(pickKind === 'image', 'shared local image picker');
      await picked({id:'1',title:'Exact map',kind:'image'});
      assert(calls.at(-2)[1].source === 'library' && calls.at(-2)[1].asset_id === '1','exact Library asset, no archive');
      assert(calls.at(-1)[1].chosen_id === 'lib1','selected local candidate applied');
      p.slides[0].chosen_id = 'c0';

      state.visualHasFootage = true;
      await suggestVisualFootage(p, p.slides[0]);
      assert(p.slides[0].chosen_id === 'c0', 'suggestions preserve selection');
      selectVisualSource('Footage');
      html = $('#tabbody').innerHTML;
      assert(visualSources(p)[0] === 'Footage', 'footage first with a shoot');
      assert(html.includes('2.000–10.000 s') && html.includes('harbour'), 'range and label chips');
      assert(html.includes('Fill the rest from footage'), 'fill available');
      await choose('s0','ft1');
      assert(calls.at(-1)[1].chosen_id === 'ft1', 'choose footage via existing save');
      await fillVisualFootage();
      assert(calls.at(-1)[0].endsWith('/footage/fill'), 'explicit fill route');
      state.visualHasFootage = false;
      selectVisual('s39');
      assert($('#tabbody').innerHTML.includes('Picture 40'), 'last group selectable');
      p.picture_runs = [['s0','s1'],...p.slides.slice(2).map(s=>[s.id])];
      selectVisual('s1');
      assert($('#tabbody').innerHTML.includes('Give this one its own picture'), 'held controls');
      assert($('#tabbody').innerHTML.includes('3s from the takes'), 'run duration from takes');
      delete p.picture_runs;
      for(const [format,delivery,aspect,tab] of [['stage','voice_over','landscape','3D'],
        ['essay','on_camera','landscape','Layout'],['loudmouth','voice_over','portrait','Blocks']]) {
        p.style.format=format;p.delivery=delivery;p.aspect=aspect;delete state.visualSource;
        paintMedia(); assert($('#tabbody').innerHTML.includes(`selectVisualSource('${tab}')`), 'format source '+tab);
      }
      assert(!$('#tabbody').innerHTML.includes('/cut/'), 'no generated cut thumbnail');
      for(const s of p.slides) s.take={};
      paintMedia(); assert($('#tabbody').innerHTML.includes('by group count (unvoiced)'), 'honest unvoiced mix');
      p.style.format='kenburns';p.delivery='voice_over';p.aspect='landscape';
      selectVisualSource('Scenes');
      for (let i=0;i<6;i++) await Promise.resolve();
      html = $('#tabbody').innerHTML;
      assert(html.includes('More blocks…') && html.includes('/poster/number_slam'), 'compact local suggestion posters');
      assert(calls.some(([url]) => url.endsWith('/block-suggestions')), 'offline suggestions endpoint');
      assert(!calls.some(([url]) => url.endsWith('/preview')), 'suggestions do not render');
      const selected = p.slides[0];
      selected.cues = {blocks:[{block:'number_slam',vars:{value:42}}]};
      selectVisual(selected.id);
      for (let i=0;i<6;i++) await Promise.resolve();
      html = $('#tabbody').innerHTML;
      assert(html.includes('>Edit</button>') && html.includes('>Remove</button>'), 'saved block controls');
      assert(html.includes('Block preview disabled for snapshots.'), 'honest disabled trial state');
      const preview = calls.find(([url]) => url.endsWith('/preview'));
      assert(preview[1].kind === 'trial' && preview[1].values.value === 42, 'saved vars trial');
      visualBlockData(p).trials.set(visualTrialKey(p,selected), {url:'/trial-still.png'});
      paintMedia();
      assert($('#tabbody').innerHTML.includes('/trial-still.png'), 'trial replaces preview placeholder');
      selected.cues = {};
      const board = p.slides[1];
      board.kind = 'board'; board.board_lead = 'Keep this board';
      delete state.visualSource;
      selectVisual(board.id);
      html = $('#tabbody').innerHTML;
      assert(html.includes('Edit the board') && html.includes('Write the boards'), 'board controls in photo project');
      assert(html.includes('Board 1 ·') && html.includes('Documentary photo 39 ·'), 'resolved counts');
      assert(visualFormatSources(p, selected)[0] === 'Footage', 'photo sources stay available');
      assert(visualFormatSources(p, board)[0] === 'Board', 'board sources');
      board.kind = 'loudmouth';
      paintMedia();
      assert($('#tabbody').innerHTML.includes('Edit the cues') && $('#tabbody').innerHTML.includes('P1 · No cues'), 'cut editor and finding');
      selectVisual('s3',{shiftKey:true});
      assert(state.visualRange.ids.join(',') === 's1,s2,s3', 'range selection');
      p.picture_runs = [['s0','s1'],['s2'],['s3']];
      selected.kind = 'essay';
      assert(pictureKind(board) === 'essay', 'group lead resolves kind');
      delete p.picture_runs;
      state.visualRange = null;
      const ensureSlideStyles = async () => [];
      const render = async () => paintMedia();
      let dialog;
      document.body = {appendChild: el => {dialog=el;}};
      document.createElement = () => ({
        setAttribute(){}, remove(){this.removed=true;},
        querySelector(){return {focus(){},textContent:''};},
        querySelectorAll(){return this.buttons ||= [...this.innerHTML.matchAll(/data-picture-kind="([^"]*)"/g)]
          .map(m => ({dataset:{pictureKind:m[1]}}));}
      });
      const chooseKind = async kind => {
        await openPictureKind('s1');
        await dialog.buttons.find(b => b.dataset.pictureKind === kind).onclick();
        assert(dialog.removed, 'kind menu completed');
      };
      await chooseKind('board');
      assert(state.project.slides[1].kind === 'board', 'menu persists board');
      await chooseKind('');
      assert(state.project.slides[1].kind === '' && state.project.slides[1].board_lead === 'Keep this board', 'default retains board text');
      state.project.slides[1].cues = {blocks:[{block:'title_card',vars:{title:'Keep'}}]};
      await chooseKind('essay');
      assert(pictureKind(state.project.slides[1]) === 'essay', 'switch leaves active block');
      assert(state.project.slides[1].cues.inactive_blocks[0].vars.title === 'Keep', 'switch retains block variables');
      state.visualRange = {pid:'p1',ids:['s1','s2']};
      await chooseKind('board');
      assert(state.project.slides[1].kind === 'board' && state.project.slides[2].kind === 'board', 'range menu applies both');
      print('visual picker checks passed');
    '''
    script = tmp_path / 'visuals.mjs'
    media = (ROOT / 'static/js/tabs/media.js').read_text()
    script.write_text(bootstrap + media + (ROOT / 'static/js/tabs/visuals.js').read_text() + checks)
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())


def test_library_search_never_queries_archives(project, monkeypatch):
    from app import llm, main
    from app.schema import MediaCandidate
    candidate = MediaCandidate(id='lib1', provider='library', kind='image', title='Map', url='file://fixture')
    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(main.store, 'save', lambda p: None)
    monkeypatch.setattr(main.library, 'search', lambda query, kind: [candidate])
    def forbidden(*args, **kwargs):
        pytest.fail('Archive/network/LLM call forbidden')
    monkeypatch.setattr(main.media, 'search', forbidden)
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    result = main.slide_search(project.id, project.slides[0].id, {'query':'map','source':'library'})
    assert result['added'] == 1
    assert result['results'][0]['id'] == 'lib1'
    assert project.slides[0].candidates[0]['provider'] == 'library'


def test_visual_lock_toggle_preserves_takes(project):
    from app.edits import EditError, patch_slide_fields
    slide = project.slides[0]
    original = slide.to_dict()
    assert patch_slide_fields(slide, {'locked_media': True}) == ['locked_media']
    assert patch_slide_fields(slide, {'locked_media': False}) == ['locked_media']
    assert slide.to_dict() == original
    with pytest.raises(EditError, match='must be a boolean'):
        patch_slide_fields(slide, {'locked_media': 'false'})


def test_kind_switch_retains_content_through_api(project):
    from app import main, store
    from app.kinds import kind_for
    project.id = 'pkindroundtrip'
    store.save(project)
    slide = project.slides[1]
    main.patch_slide(project.id, slide.id, {'kind':'board', 'board_lead':'Keep this board',
        'board_points':['A stored line']})
    main.patch_slide(project.id, slide.id, {'kind':''})
    restored = store.load(project.id)
    assert restored.slides[1].kind == ''
    assert restored.slides[1].board_lead == 'Keep this board'
    assert restored.slides[1].board_points == ['A stored line']
    block = {'block':'title_card','vars':{'title':'Keep this block'}}
    main.patch_slide(project.id, slide.id, {'cues':{'blocks':[block]}})
    active = store.load(project.id).slides[1].cues['blocks']
    main.patch_slide(project.id, slide.id, {'kind':'board',
        'cues':{'blocks':[], 'inactive_blocks':active}})
    restored = store.load(project.id)
    assert kind_for(restored,restored.slides[1]) == 'board'
    assert restored.slides[1].cues['inactive_blocks'] == active
    main.patch_slide(project.id,slide.id, {'cues':{'blocks':active}})
    restored = store.load(project.id)
    assert kind_for(restored,restored.slides[1]) == 'block'
    assert restored.slides[1].board_lead == 'Keep this board'
