import Shot from '@/components/Shot';
import Zoom from '@/components/Zoom';
import DownloadButton from '@/components/DownloadButton';
import Trailer from '@/components/Trailer';
import { TRAILER } from '@/lib/media';
import { NAME, BUILD_DOC_URL } from '@/lib/brand';
import { PLATFORMS, platformHref } from '@/lib/releases';

// Each row is a shipped feature, shown by a real screenshot of the app.
// The label is the stage as the app names it in its stage bar.
const FEATURES = [
  { shot: 'home', label: '1 · Home', title: 'Your research in one place',
    text: 'Drop in PDFs, pasted notes and web pages. The agent reads them for facts with page references, and keeps track of what is still unanswered.',
    more: 'Home holds what you gather: pictures, clips and notes with what each shows and its licence, and research documents read for facts, each linked to the passage it came from. The agent beside them answers from your sources, and can search the web and save what it finds as documents you can check.',
    alt: 'Home: the research agent, the materials, a saved web page with its pages, and the brief.' },
  { shot: 'script', label: '2 · Script', title: 'A script you write, with an agent beside it',
    text: 'The page is just your words. Ask the agent to tighten a passage or check it against your facts; nothing changes until you apply an edit.',
    more: 'Write as you would in a word processor, with your facts a click away. The agent suggests edits as before and after, flags claims your facts do not support, and every change it makes can be undone. A check runs on your computer for things like stacked short sentences.',
    alt: 'The Script stage: the agent and check panel beside a page of narration.' },
  { shot: 'shots', label: '2 · Script › Shots', title: 'Design every shot',
    text: 'Describe what each shot should show, then lay photos, clips, maps, 3D, diagrams or designed scenes against the words.',
    more: 'Each shot has a description, the narration it plays under, and the visuals that carry it. Start a new visual on any paragraph, choose its kind, and use the search, map, diagram and 3D tools for it. A shot agent can suggest a plan for you to apply.',
    alt: 'Script › Shots: the shot list, a shot description, and its narration with the visuals under it.' },
  { shot: 'create', label: '3 · Create', title: 'Graphics made with an agent',
    text: 'Describe a number landing, a comparison or a title card. The agent builds it in your channel\u2019s style, and you place it in a shot.',
    more: 'Graphics are small HTML scenes with timed reveals, drawn in your channel\u2019s fonts and colours. Each change the agent makes is a new version you can go back to, and you can see the build at a few moments before placing it. The graphic shown is an example.',
    alt: 'Create: an example graphic comparing Paris and Berlin, its moments, and the agent.' },
  { shot: 'voice', label: '4 · Voice', title: 'Your voice, or a local one',
    text: 'Read each paragraph from a prompter, or draft the narration with a text-to-speech voice on your computer. Every take is kept.',
    more: 'The prompter shows one paragraph at a time with a level meter. Replaced takes move to history and stay on disk, so nothing you record is lost.',
    alt: 'The Voice stage: a paragraph list, the prompter with a record button, and earlier takes.' },
  { shot: 'timeline', label: '5 · Edit', title: 'A timeline in layers',
    text: 'Move whole sections, trim pictures, add clips and cards on named layers you can lock or hide, and undo any of it.',
    more: 'Layers are yours to name and order, and the agent can suggest a set for your script. Lock a layer to protect it, or hide it from the preview. Select a section and drag it, trim items by their edges, and lay graphics over the pictures. Every edit can be undone.',
    alt: 'The Edit timeline: pictures, voice, graphics, titles and notes lanes for an eight-minute video.' },
  { shot: 'blocks', label: 'Blocks', title: 'Titles, charts and maps you fill in',
    text: 'Animated blocks for titles, numbers and places. You type the words; they render on your machine.',
    more: 'Blocks are local templates with named fields: titles, charts, maps, timelines and lower thirds. Preview one with your own text before you use it, or describe a new one and the agent writes it.',
    alt: 'The Blocks library: title card, archive frame, bar chart and bar race previews.' },
  { shot: 'channels', label: 'Channels', title: 'A look for each series',
    text: 'A channel keeps its colours, opening slate and defaults, so each new video starts from them.',
    more: 'A channel sets the colours, the block fonts, the opening slate and the end screen. Each new video in the channel starts from those settings.',
    alt: 'Channel setup: theme cards such as Archive, Arcade, Kitchen and Broadcast.' },
  { shot: 'models', label: 'Setup', title: 'Your choice of model',
    text: 'Write with Claude, or with a local model through LM Studio or Ollama, with no account and no per-token bill.',
    more: 'Use Claude through the Claude Code CLI or an API key, or a local model through LM Studio or Ollama. Research and archive searches still use the network.',
    alt: 'The Writing model setup step, with LM Studio settings.' },
] as const;

export default function Home() {
  return (
    <>
      <section className="wrap hero" aria-labelledby="hero-title">
        <h1 id="hero-title">{NAME}</h1>
        <p className="lede">Turn an idea or a script into a researched, narrated, illustrated video on your own computer.</p>
        <div className="actions">
          <DownloadButton />
          <a className="more" href="/download/">Other platforms and older versions</a>
        </div>
      </section>

      {/* The trailer, or the Shots still until site/tools/trailer.py has run. */}
      <section className="wrap trailer" aria-label="The app">
        {TRAILER
          ? <Trailer label={`A silent tour of ${NAME}: the stages, archive film, blocks and 3D scenes.`} />
          : <div className="frame"><Shot name="shots" mobile="shots--m" priority sizes="(min-width: 1160px) 1108px, 96vw"
              alt={`${NAME}'s Script › Shots view with the bundled example, The Tube Mail.`} /></div>}
      </section>

      <section id="features" className="wrap features" aria-labelledby="features-title">
        <header>
          <span className="label">What it does</span>
          <h2 id="features-title">From idea to finished video</h2>
        </header>
        {FEATURES.map((f) => (
          <article className="feature" key={f.shot}>
            <Zoom label={f.label} title={f.title} text={f.text} more={f.more}
              thumb={<div className="frame"><Shot name={f.shot} mobile={`${f.shot}--m`} alt={f.alt} /></div>}
              large={<Shot name={f.shot} alt={f.alt} sizes="(min-width: 1300px) 1224px, 96vw" />} />
            <div className="copy">
              <span className="label">{f.label}</span>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
            </div>
          </article>
        ))}
      </section>

      <section id="download" className="wrap start" aria-labelledby="start-title">
        <div className="card">
          <div className="head">
            <h2 id="start-title">Get started</h2>
            <span className="label">Builds on GitHub Releases</span>
          </div>
          <ul className="builds">
            {PLATFORMS.map((p) => (
              <li key={p.id}>
                <a href={platformHref(p)}>
                  <strong>{p.label}</strong>
                  <span>{p.detail}</span>
                </a>
              </li>
            ))}
          </ul>
          <p className="source">Or <a href={BUILD_DOC_URL}>build it from source</a>.</p>
        </div>
      </section>
    </>
  );
}
