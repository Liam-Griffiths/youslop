/* Clip finder: bounded transcript DOM, source-clock selection, no automatic STT. */
async function renderClipFinder(sid, fid) {
  const route = location.hash, base = `/api/footage/shoots/${encodeURIComponent(sid)}`;
  const current = () => location.hash === route && host?.isConnected;
  let host;
  try {
    const [shoot, data] = await Promise.all([api(base), api(`${base}/finder/${encodeURIComponent(fid)}`)]);
    if (location.hash !== route) return;
    const source = shoot.files.find(f => f.id === fid), doc = data.transcript, duration = source.duration;
    let manual = doc.coverage.length !== 1 || doc.coverage[0][0] > 0 || doc.coverage[0][1] < duration;
    let page = 0, anchor = null, reverse;
    const pageSize = 200;
    view.innerHTML = `<section id="clip-finder"><a href="#/footage/${esc(sid)}">Back to shoot</a><h1>Find clips · ${esc(fid)}</h1>
      <p>${manual ? 'Mark a range without transcription. ' : ''}${doc.words.some(w=>['est','stt-seg'].includes(w.src)) ? 'Some word times are approximate. ' : ''}Transcription is optional. <a href="#/settings">Speech-to-text settings</a></p>
      <button class="btn" id="cf-whole">Transcribe the whole recording · estimate first</button><button class="btn" id="cf-mode" aria-pressed="${!manual}">Transcript mode</button><button class="btn" id="cf-refresh">Refresh</button>
      <div id="cf-work"><section id="cf-text" class="panel"><label for="cf-search">Search transcript</label><input id="cf-search" type="search"><button class="btn" id="cf-find">Next match</button><div id="cf-words"></div>
      <button class="btn" id="cf-prev">Previous words</button><button class="btn" id="cf-next">Next words</button></section><div><video id="cf-player" controls preload="metadata" aria-label="Recording"></video>
      <div class="row"><button class="btn" data-key="j">J · Reverse</button><button class="btn" data-key="k">K · Pause</button><button class="btn" data-key="l">L · Forward</button><button class="btn" data-key=" ">Space · Play/pause</button></div></div></div>
      <canvas id="cf-wave" width="1024" height="80" aria-label="Waveform: drag to select a range"></canvas>
      <label for="cf-time">Playhead (s)</label><input id="cf-time" type="range" min="0" max="${duration}" step="0.02" value="0">
      <p id="cf-partial" class="mono"></p><fieldset ${shoot.processing ? 'disabled' : ''}><legend>New clip</legend><div class="row">
      <label for="cf-in">In (s)</label><input id="cf-in" type="number" min="0" step=".01" value="0"><button class="btn" data-key="i">I · Mark in</button>
      <label for="cf-out">Out (s)</label><input id="cf-out" type="number" step=".01" value="${Math.min(30,duration)}"><button class="btn" data-key="o">O · Mark out</button></div>
      <p id="cf-length" class="mono" role="status"></p><div class="row"><label for="cf-title">Title</label><input id="cf-title" type="text" placeholder="Untitled clip"><button class="btn primary" id="cf-save">Save clip</button></div></fieldset>
      <div id="cf-budget" role="status"></div><h2>Clips</h2><div id="cf-clips"></div><h2>Suggested moments</h2><button class="btn" id="cf-rank">Rank with the writing model · estimate first</button><div id="cf-rank-budget"></div><div id="cf-suggestions"></div></section>`;
    host = $('#clip-finder');
    const player = $('#cf-player'), a = $('#cf-in'), b = $('#cf-out');
    player.src = base + (source.kind === 'audio' ? `/media/audio/${fid}` : `/media/proxies/${fid}.mp4`);
    if (source.kind === 'audio') player.poster = `${base}/media/sprites/${fid}.jpg`;
    const selection = (start, end, byWords=false) => { a.value=start; b.value=end; host.byWords=byWords; length(); };
    const length = () => { $('#cf-length').textContent=`${(Number(b.value)-Number(a.value)).toFixed(2)} s · targets 15 / 30 / 60 / 90 s`; };
    a.oninput=b.oninput=()=>{host.byWords=false;length();}; length();
    const paint = () => {
      $('#cf-text').hidden=manual; $('#cf-work').style.gridTemplateColumns=manual?'1fr':''; $('#cf-mode').setAttribute('aria-pressed', String(!manual));
      const first=page*pageSize;
      $('#cf-words').innerHTML=`<p class="mono">${doc.words.length?first+1:0}–${Math.min(first+pageSize,doc.words.length)} of ${doc.words.length} words · drag words or Shift+click</p>` + doc.words.slice(first,first+pageSize).map((w,i)=>`<button class="cf-word" data-word="${first+i}">${esc(w.w)}</button>`).join(' ');
      $('#cf-prev').disabled=page===0; $('#cf-next').disabled=first+pageSize>=doc.words.length;
      $('#cf-words').querySelectorAll('[data-word]').forEach(el=>{
        el.onpointerdown=e=>{if(!e.shiftKey || anchor===null)anchor=Number(el.dataset.word);};
        const choose=()=>{const end=Number(el.dataset.word), x=doc.words[Math.min(anchor,end)], y=doc.words[Math.max(anchor,end)];selection(x.start,y.end,true);player.currentTime=x.start;};
        el.onpointerup=choose; el.onclick=e=>{if(e.detail===0){if(!e.shiftKey || anchor===null)anchor=Number(el.dataset.word);choose();}};
      });
    };
    paint();
    $('#cf-mode').onclick=()=>{manual=!manual;paint();};
    $('#cf-prev').onclick=()=>{page--;paint();}; $('#cf-next').onclick=()=>{page++;paint();};
    let match=-1;
    $('#cf-search').oninput=()=>{match=-1;};
    $('#cf-find').onclick=()=>{
      const query=$('#cf-search').value.trim().toLocaleLowerCase(); if(!query)return;
      const index=doc.words.findIndex((w,i)=>i>match && doc.words.slice(i,i+query.split(/\s+/).length).map(x=>x.w).join(' ').toLocaleLowerCase().includes(query));
      match=index; if(index<0){toast('No more matches');return;} page=Math.floor(index/pageSize);paint();
      player.currentTime=doc.words[index].start; const el=host.querySelector(`[data-word="${index}"]`);el.focus();el.scrollIntoView({block:'nearest'});
    };
    player.ontimeupdate=()=>{
      $('#cf-time').value=player.currentTime;
      $('#cf-partial').textContent=doc.words.filter(w=>w.start>=player.currentTime-2 && w.start<=player.currentTime+4).map(w=>w.w).join(' ');
    };
    $('#cf-time').oninput=e=>{player.currentTime=Number(e.target.value);};
    const wave=$('#cf-wave'), ctx=wave.getContext('2d'); ctx.fillStyle=getComputedStyle(host).getPropertyValue('--cool');
    data.waveform.forEach((v,i)=>{const h=Math.max(1,(v+120)/120*80);ctx.fillRect(i*1024/data.waveform.length,40-h/2,1,h);});
    const time=e=>Math.max(0,Math.min(duration,(e.clientX-wave.getBoundingClientRect().left)/wave.getBoundingClientRect().width*duration));
    let waveStart=0;
    wave.onpointerdown=e=>{waveStart=time(e);wave.setPointerCapture(e.pointerId);};
    wave.onpointerup=e=>{selection(Math.min(waveStart,time(e)),Math.max(waveStart,time(e)));};
    const act = key => {
      clearInterval(reverse);
      if(key==='i')selection(player.currentTime,Number(b.value));
      else if(key==='o')selection(Number(a.value),player.currentTime);
      else if(key==='k')player.pause();
      else if(key==='j'){player.pause();reverse=setInterval(()=>{if(!current()){clearInterval(reverse);return;}player.currentTime=Math.max(0,player.currentTime-.1);},100);}
      else if(key==='l'){player.playbackRate=player.paused?1:Math.min(4,player.playbackRate*2);player.play().catch(e=>toast(e.message,true));}
      else if(key===' '){if(player.paused)player.play().catch(e=>toast(e.message,true));else player.pause();}
    };
    host.querySelectorAll('[data-key]').forEach(el=>el.onclick=()=>act(el.dataset.key));
    host.tabIndex=-1; host.focus();
    host.onkeydown=e=>{
      if(/^(INPUT|TEXTAREA|SELECT|VIDEO)$/.test(e.target.tagName)||e.ctrlKey||e.metaKey||e.altKey||document.querySelector('.modal, dialog[open]'))return;
      if(e.target.tagName==='BUTTON' && e.key===' ')return;
      const key=e.key.toLowerCase();
      if(['i','o','j','k','l',' '].includes(key))act(key);
      else if(['arrowleft','arrowright'].includes(key))player.currentTime=Math.max(0,Math.min(duration,player.currentTime+(key==='arrowleft'?-1:1)*(e.shiftKey?10:1)));
      else return; e.preventDefault();
    };
    const save=async payload=>{await api(`${base}/finder/${fid}`,{method:'POST',body:JSON.stringify(payload)});if(current())await renderClipFinder(sid,fid);};
    $('#cf-save').onclick=async()=>{try{await save({in_s:Number(a.value),out_s:Number(b.value),title:$('#cf-title').value,hook:host.hook || '',words:!!host.byWords});}catch(e){toast(e.message,true);}};
    const transcribe=async clip=>{
      try {
        const options=clip?{start:clip.in_s,end:clip.out_s}:{};
        const estimate=await api(`${base}/transcripts/${fid}/estimate`,{method:'POST',body:JSON.stringify(options)});
        if(!current())return;
        $('#cf-budget').innerHTML=`<p>${estimate.seconds.toFixed(1)} s audio · ${estimate.runtime_seconds==null ? esc(estimate.detail) : `about ${(estimate.runtime_seconds/60).toFixed(1)} min`}</p><button class="btn" id="cf-confirm">Confirm and transcribe</button>`;
        $('#cf-confirm').onclick=async e=>{e.target.disabled=true;try{await api(`${base}/transcripts/${fid}/start`,{method:'POST',body:JSON.stringify({...options,confirm:true})});openJobs();}catch(err){toast(err.message,true);e.target.disabled=false;}};
      }catch(e){toast(e.message,true);}
    };
    $('#cf-whole').onclick=()=>transcribe(null); $('#cf-refresh').onclick=()=>renderClipFinder(sid,fid);
    const clips=shoot.clips.filter(c=>c.file===fid && c.finder);
    $('#cf-clips').innerHTML=clips.map((c,i)=>`<div class="panel"><b>${esc(c.title)}</b><p class="mono">${c.in_s.toFixed(2)}–${c.out_s.toFixed(2)} s · ${(c.out_s-c.in_s).toFixed(2)} s</p><button class="btn" data-play="${i}">Select range</button><button class="btn" data-stt="${i}">Transcribe this clip</button><button class="btn" data-refine="${i}">Refine to words</button></div>`).join('') || '<p>No named clips yet. Mark in and out, then save a clip.</p>';
    host.querySelectorAll('[data-play]').forEach(el=>el.onclick=()=>{const c=clips[el.dataset.play];selection(c.in_s,c.out_s);player.currentTime=c.in_s;});
    host.querySelectorAll('[data-stt]').forEach(el=>el.onclick=()=>transcribe(clips[el.dataset.stt]));
    host.querySelectorAll('[data-refine]').forEach(el=>el.onclick=async()=>{try{const c=clips[el.dataset.refine];await save({in_s:c.in_s,out_s:c.out_s,refine:c.id});}catch(e){toast(e.message,true);}});
    const paintSuggestions=()=>{ $('#cf-suggestions').innerHTML=data.suggestions.map((s,i)=>`<div class="panel"><b>${esc(s.hook || s.title)}</b><p>${esc(s.reason)}</p><button class="btn" data-use="${i}">Use range</button><button class="btn" data-dismiss="${i}">Dismiss</button></div>`).join('') || '<p>Suggestions need a whole transcript with complete sentences of 20–90 s.</p>';
    host.querySelectorAll('[data-use]').forEach(el=>el.onclick=()=>{const s=data.suggestions[el.dataset.use];selection(s.in_s,s.out_s,true);$('#cf-title').value=s.title;host.hook=s.hook || '';player.currentTime=s.in_s;});
    host.querySelectorAll('[data-dismiss]').forEach(el=>el.onclick=()=>el.parentElement.remove()); }; paintSuggestions();
    $('#cf-rank').disabled=!data.suggestions.length;
    $('#cf-rank').onclick=async()=>{
      try {
        const endpoint=`${base}/finder/${fid}/rank`, estimate=await api(endpoint,{method:'POST',body:'{}'});
        if(!current())return;
        $('#cf-rank-budget').innerHTML=`<p class="mono">About ${estimate.input_tokens} input / ${estimate.output_tokens} output tokens · text only · configured model</p><button class="btn" id="cf-rank-confirm">Confirm ranking</button>`;
        $('#cf-rank-confirm').onclick=async e=>{e.target.disabled=true;try{
          // Ranking runs as a job: a local model can take minutes, and the job
          // status carries its live token count.
          const {job}=await api(endpoint,{method:'POST',body:JSON.stringify({confirm:true,estimate})});
          for(;;){
            const j=await api(`/api/jobs/${job}`);
            if(!current())return;
            if(j.state==='error')throw new Error(j.error||'Ranking failed');
            if(j.state==='done'){data.suggestions=j.result;$('#cf-rank-budget').textContent='';paintSuggestions();return;}
            const status=$('#cf-rank-status')||Object.assign(document.createElement('p'),{id:'cf-rank-status',role:'status'});
            status.textContent=j.status||'Waiting for the writing model…';$('#cf-rank-budget').append(status);
            await new Promise(r=>setTimeout(r,1200));
          }
        }catch(err){toast(err.message,true);if(e.target.isConnected)e.target.disabled=false;}};
      }catch(e){toast(e.message,true);}
    };
  } catch(e) { if(location.hash===route)view.innerHTML=`<p>${esc(e.message)}</p><a href="#/footage/${esc(sid)}">Back to shoot</a>`; }
}
