
// ------------------------------------------------------------------- guide
// The whole flow on one page, for someone who has never made a video here.
// Static on purpose: it names the buttons as they are labelled elsewhere in
// this file, so a renamed button wants its mention here renamed too.
function renderGuide() {
  $('#topbar-right').innerHTML = '';
  const step = (n, title, body) => `
    <div class="guide-step">
      <div class="guide-num">${n}</div>
      <div class="guide-body"><h3>${title}</h3>${body}</div>
    </div>`;

  view.innerHTML = `
    <img src="/static/brand/corkbored-icon-128.png" width="128" height="128" alt="App icon">
    <h1>How it works</h1>
    <p class="sub">Turn an idea or a script into a researched, narrated, illustrated video
      on your own computer. Review each step before rendering.</p>

    <div class="panel guide-before">
      <h3>Before you start</h3>
      <p>Use Claude to research and write scripts. Either have the
        <a href="https://claude.com/claude-code" target="_blank">Claude Code CLI</a> installed
        and signed in, or add an Anthropic API key in
        <a href="#/settings">Settings</a>.</p>
      <p>To have the script read for you instead of recording it yourself, the built-in narrator
        needs two voice files. The Record tab tells you where to put them the first time you
        open it.</p>
    </div>

    <div class="guide-steps">
      ${step(1, 'Start a video', `
        <p>Open <a href="#/">New video</a> and choose how to begin:</p>
        <ul>
          <li><b>Start from an idea</b>: describe the story in a sentence or two. The more
            specific, the better the script.</li>
          <li><b>Paste a script</b>: bring your own words. <i>Faithful</i> keeps them as they
            are; <i>Adapted</i> smooths written prose into something that reads aloud well.</li>
        </ul>
        <p>Pick a target length, a tone and a video style, then press <b>Write the script</b>
          (or <b>Break it into a video</b>). It takes a few minutes: Claude writes the script,
          and the archives are searched for a picture for each paragraph.</p>`)}

      ${step(2, 'Read the script', `
        <p>The <b>Script</b> tab shows the video one paragraph at a time. Each paragraph
          becomes one recording and, by default, one picture.</p>
        <ul>
          <li><b>rewrite</b> a paragraph with an instruction, or <b>split</b> or
            <b>delete</b> it.</li>
          <li><b>check facts</b> checks the script against the research Claude did while
            writing it, and flags anything it doesn't support. Worth running after you
            edit.</li>
          <li><b>rewrite whole script</b> starts the writing over. For a pasted script,
            <b>re-split</b> breaks it into paragraphs again instead.</li>
        </ul>`)}

      ${step(3, 'Choose the pictures', `
        <p>The <b>Media</b> tab shows the picture chosen for each paragraph and the
          alternatives found. Click an alternative to use it instead.</p>
        <ul>
          <li><b>search for a picture…</b> to look for something else, or
            <b>get a map…</b> for a place.</li>
          <li>For a paragraph with no good photograph, have Claude draw a diagram or a
            custom slide instead.</li>
          <li><b>picture every</b> holds each picture across several paragraphs. Useful when
            the archives are thin on a subject.</li>
        </ul>`)}

      ${step(4, 'Record the narration', `
        <p>On the <b>Record</b> tab, choose who reads it:</p>
        <ul>
          <li><b>read it yourself</b>: press <b>● Record</b>, read the paragraph on screen,
            press stop. <kbd>space</kbd> records and stops, <kbd>→</kbd> moves to the next
            paragraph, <kbd>p</kbd> plays the take back, <kbd>r</kbd> retires it. Earlier takes stay available.
            <b>check the microphone</b> first to hear how your room sounds.</li>
          <li><b>Narrator</b>: pick a voice and a pace, then press <b>read the whole
            script</b>, or <b>read this paragraph</b> for just one. The built-in voice runs on your computer. Hosted voices send the text
            to the provider you select.</li>
        </ul>
        <p>The strip of squares at the bottom shows which paragraphs are done.
          <b>jump to next blank</b> takes you to the first one that isn't.</p>`)}

      ${step(5, 'Make a thumbnail', `
        <p>On the <b>Thumbnail</b> tab, <b>choose a picture…</b> for the background and
          type a short headline (a few words, not the title again), or press
          <b>write me some</b> for suggestions.</p>`)}

      ${step(6, 'Review and render', `
        <p>On the <b>Render</b> tab, adjust the look (style, drift, crossfade, colour grade)
          and the sound (music and how loud it sits under the voice).</p>
        <ul>
          <li><b>Preview cut (no voice)</b> is a quick check of the pictures and timing.</li>
          <li>Review the cut on the <b>Timeline</b> and resolve findings in <b>Check</b>.</li>
          <li><b>Render the video</b> makes the finished file.</li>
          <li><b>YouTube description</b> writes the description — hook, chapters with
            timestamps and picture credits — ready to paste into YouTube.</li>
        </ul>
        <p>If the video belongs to a channel connected to YouTube, you can upload it from
          here too.</p>`)}
    </div>

    <h2>Channels</h2>
    <div class="panel guide-before">
      <p>A channel is a series. Every video in it shares the same
        opening slate, colours and defaults, so they look like they belong together.</p>
      <p>Make one with <b>new channel</b> on the New video page or the <b>＋</b> in the
        sidebar, then open it to set up its slate, music and the faces in its opening
        titles. Pick the channel when starting a video and it picks up all of that.</p>
      <p>A video doesn't need a channel. Leave it as a
        <i>standalone video</i> to just make one.</p>
    </div>

    <h2>Taking a video to another computer</h2>
    <div class="panel guide-before">
      <p>On the video's page, <b>save project file…</b> puts the whole video in one
        <span class="mono">.corkbored</span> file: script, chosen pictures, recordings,
        settings, and its channel, music and style if it has them.</p>
      <p>On the other computer, press <b>open project file…</b> at the top of the
        <a href="#/">New video</a> page and pick that file. If the video is already there,
        you can replace it or keep both.</p>
      <p>The finished video isn't included, to keep the file small. Render again on the
        other computer.</p>
    </div>

    <div class="row" style="margin-top:26px">
      <button class="btn primary" onclick="go('#/')">Make a video</button>
    </div>`;
}
