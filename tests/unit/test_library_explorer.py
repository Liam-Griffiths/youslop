"""Explorer contracts without a browser, disk walks, models or renders."""
import ctypes
import ctypes.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import library, main, store
from app.schema import BinItem, Project


def test_index_metadata_and_reveal_preserve_linked_originals(tmp_path, monkeypatch):
    root = tmp_path / 'index'
    root.mkdir()
    for name, value in {'LIBRARY_DIR': root, '_INDEX_FILE': root / 'library.json',
                        '_FILES': root / 'files', '_THUMBS': root / 'thumbs'}.items():
        monkeypatch.setattr(library, name, value)
    original = tmp_path / 'linked' / 'nested' / 'original.png'
    original.parent.mkdir(parents=True)
    original.write_bytes(b'Original bytes must stay unchanged')
    asset = library.LibraryAsset.from_dict(dict(id='linked', kind='image', source_path=str(original),
                                               folder_id='folder', future=True))
    assert asset.size == 0
    library._save_both([asset], [library.LibraryFolder('folder', str(original.parent.parent))])
    before = original.stat().st_mtime_ns
    assert main.library_info('linked')['size'] == len(original.read_bytes())
    library.update('linked', title='New title', tags=['Station', 'Station'], source_path='/ignored')
    assert library.get('linked')['tags'] == ['Station']
    revealed = []
    monkeypatch.setattr(main.playback_mod, 'reveal', lambda path: (revealed.append(path) or (True, False)))
    main.reveal_file({'scope': 'library', 'id': 'linked', 'rel': '/etc/passwd'})
    assert revealed == [original]
    with pytest.raises(HTTPException) as exc:
        main.reveal_file({'scope': 'library', 'id': 'unknown', 'rel': str(original)})
    assert exc.value.status_code == 404
    library.remove_folder('folder')
    assert original.read_bytes() == b'Original bytes must stay unchanged'
    assert original.stat().st_mtime_ns == before
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    store.PROJECTS_DIR.mkdir()
    store.save(Project(id='pexplorer', idea='Explorer', bin=[BinItem(id='n')]))
    assert store.list_projects()[0]['bin_count'] == 1


def evaluate_js(source):
    """Use the installed WebKit JS engine only; no browser or Node dependency."""
    name = ctypes.util.find_library('javascriptcoregtk-4.1')
    if not name:
        pytest.skip('System JavaScriptCore unavailable')
    js = ctypes.CDLL(name)
    ptr = ctypes.c_void_p
    signatures = {'JSGlobalContextCreate': (ptr, [ptr]), 'JSGlobalContextRelease': (None, [ptr]),
        'JSStringCreateWithUTF8CString': (ptr, [ctypes.c_char_p]), 'JSStringRelease': (None, [ptr]),
        'JSEvaluateScript': (ptr, [ptr, ptr, ptr, ptr, ctypes.c_int, ctypes.POINTER(ptr)]),
        'JSValueToStringCopy': (ptr, [ptr, ptr, ptr]),
        'JSStringGetUTF8CString': (ctypes.c_size_t, [ptr, ctypes.c_char_p, ctypes.c_size_t])}
    for key, (result, args) in signatures.items():
        fn = getattr(js, key)
        fn.restype, fn.argtypes = result, args
    context, script, error = js.JSGlobalContextCreate(None), js.JSStringCreateWithUTF8CString(source.encode()), ptr()
    try:
        js.JSEvaluateScript(context, script, None, None, 1, ctypes.byref(error))
        if error.value:
            message = js.JSValueToStringCopy(context, error, None)
            buffer = ctypes.create_string_buffer(4096)
            js.JSStringGetUTF8CString(message, buffer, len(buffer))
            js.JSStringRelease(message)
            pytest.fail(buffer.value.decode())
    finally:
        js.JSStringRelease(script)
        js.JSGlobalContextRelease(context)


def test_tree_search_range_selection_and_keyboard():
    source = Path('static/js/tabs/media.js').read_text() + '\n' + Path('static/js/tabs/library_explorer.js').read_text()
    evaluate_js('''const document={addEventListener(){},querySelectorAll(){return []}};
      const window={addEventListener(){}};
      const tree={querySelectorAll(){return []},focus(){},scrollIntoView(){},addEventListener(){}}, $=()=>tree, esc=String;
      const state={library:{q:'',kind:'',folders:[{id:'f',path:'/photos',label:'Photos'}],items:[]}};
      const assert=(ok,message)=>{if(!ok)throw Error(message)};
    ''' + source + '''
      state.library.items=Array.from({length:1000},(_,i)=>({id:'a'+i,title:'Station '+i,tags:['shared'],
        filename:'upload'+i+'.png',folder_id:i<3?'f':'',kind:i%2?'video':'image',added_at:1000-i,
        source_path:i===0?'/photos/inside/deep/view.png':i===1?'/photos/inside-two/view.png':i===2?'/photos/view.png':''}));
      libTree(); assert(LX.nodes.some(n=>n.label==='deep'),'Nested folder missing');
      LX.node='folder:f/inside'; assert(libVisible().length===1,'Subfolder boundary leaked');
      LX.node='all';state.library.q='upload21.png';assert(libVisible()[0].id==='a21','Filename search failed');
      state.library.q='';LX.visible=libVisible();libSelection=()=>{};
      LX.selected.add('a0');LX.visible[0].infoLoaded=true;libPreview();
      assert(tree.innerHTML.includes('libedit-title'),'Single title editor missing');
      LX.visible[0].readonly=true;libPreview();
      assert(tree.innerHTML.includes('Read-only reference')&&!tree.innerHTML.includes('libmetadata'),'Reference is editable');
      LX.visible[0].readonly=false;LX.selected.clear();
      libSelect(3,{});libSelect(7,{shiftKey:true});assert(LX.selected.size===5,'Range selection failed');
      libSelect(9,{ctrlKey:true});assert(LX.selected.size===6,'Toggle selection failed');
      libSelect(3,{metaKey:true});assert(!LX.selected.has('a3'),'Cmd toggle failed');
      const key={target:{closest:()=>null},preventDefault(){},ctrlKey:true,key:'a'};
      libKey(key);assert(LX.selected.size===1000,'Select all failed');
      assert(libDragRefs({getData:()=>JSON.stringify(['library:a1','library:a2'])}).length===2,'Drag selection lost');
      let rejected=false;try{libDragRefs({getData:()=>JSON.stringify(['library:../../etc/passwd'])})}catch{rejected=true}assert(rejected,'Invalid drag accepted');
      LX.mode='list';LX.focus=3;LX.anchor=3;LX.selected=new Set(['a3']);
      libKey({...key,ctrlKey:false,shiftKey:true,key:'ArrowDown'});
      assert(LX.selected.size===2&&LX.selected.has('a4'),'Shift arrow failed');
    ''')
