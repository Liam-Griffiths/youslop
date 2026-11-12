import Shot from '@/components/Shot';
import DownloadButton from '@/components/DownloadButton';
import { NAME, BUILD_DOC_URL } from '@/lib/brand';
import { PLATFORMS, platformHref } from '@/lib/releases';

// Each row is a shipped feature, shown by a real screenshot of the app.
// The label is the stage as the app names it in its stage bar.
const FEATURES = [
  { shot: 'research', label: '1 · Plan', title: 'Research you can check',
    text: 'It gathers sources before it writes, and shows which source each beat of the outline came from.',
    alt: 'The Plan stage: research sources on the left, the outline as chapter columns of beats.' },
  { shot: 'script', label: '2 · Script', title: 'A script you edit',
    text: 'Narration, picture notes and titles are plain text. Rewrite one paragraph, or let the check point out what reads badly.',
    alt: 'The Script stage: numbered paragraphs with their picture notes, and the check column beside them.' },
  { shot: 'voice', label: '3 · Voice', title: 'Your voice, or a local one',
    text: 'Read each paragraph from a prompter, or draft the narration with a text-to-speech voice on your computer. Every take is kept.',
    alt: 'The Voice stage: a paragraph list, the prompter with a record button, and earlier takes.' },
  { shot: 'visuals', label: '4 · Visuals', title: 'A shot for every paragraph',
    text: 'Each paragraph gets the kind of shot it needs, chosen from fixed menus you can see and change, with the source and licence beside it.',
    alt: 'The Visuals stage: picture groups, a chosen archive envelope and the source panel.' },
  { shot: 'blocks', label: 'Blocks', title: 'Blocks, and blocks it writes',
    text: 'Over 80 animated blocks for titles, numbers, maps and timelines. Describe one that doesn\u2019t exist and the agent writes it, checked before it\u2019s used.',
    alt: 'The Blocks library: title card, archive frame, bar chart and bar race previews.' },
  { shot: 'timeline', label: '5 · Edit', title: 'A timeline you can edit',
    text: 'Move whole sections, trim pictures, add clips and cards, and undo any of it.',
    alt: 'The Edit timeline: pictures, voice, graphics, titles and notes lanes for an eight-minute video.' },
  { shot: 'channels', label: 'Channels', title: 'A look for each series',
    text: 'A channel keeps its colours, opening slate and defaults, so each new video starts from them.',
    alt: 'Channel setup: theme cards such as Archive, Arcade, Kitchen and Broadcast.' },
  { shot: 'models', label: 'Setup', title: 'Your choice of model',
    text: 'Write with Claude, or with a local model through LM Studio or Ollama, with no account and no per-token bill.',
    alt: 'The Writing model setup step, with LM Studio settings.' },
] as const;


// Kinds of shot, each a real frame from the app's output where one exists.
const KINDS = [
  { shot: 'shot-archive', title: 'Archive pictures', text: 'Public-domain photographs, engravings and documents, with slow camera moves and their source credited.' },
  { shot: 'shot-html-scene', title: 'Scenes the agent writes', text: 'When nothing fits, the agent lays out a whole animated scene in HTML, and it renders on your machine.' },
  { shot: 'shot-timeline-block', title: 'Animated blocks', text: 'Timelines, counters, lower thirds and title cards, filled with your words and timed to the voice.' },
  { shot: 'shot-route', title: 'Maps and data', text: 'Routes, regions, charts and races, drawn from numbers in the script rather than searched for.' },
  { shot: 'shot-board', title: 'Boards and diagrams', text: 'Hand-drawn boards and step diagrams that build up beat by beat.' },
  { shot: 'shot-chat', title: 'Drawn formats', text: 'Chat threads, case files and tickers for stories told as messages and documents.' },
  { shot: null, title: '3D scenes', text: 'Load a model and the shot planner frames each camera move, with labels and section cuts.' },
  { shot: null, title: 'Footage and camera', text: 'Archive film, your own shoots and your camera takes, cut on the spoken words.' },
] as const;

export default function Home() {
  return (
    <>
      <section className="wrap hero" aria-labelledby="hero-title">
        <h1 id="hero-title">{NAME}</h1>
        <p className="lede">Turn an idea or a script into a researched, narrated video on your own computer.</p>
        <p className="sub">Every shot is made for the story: archive pictures and film, animated blocks, 3D scenes, and whole animated scenes the agent writes in HTML.</p>
        <div className="actions">
          <DownloadButton />
          <a className="more" href="/download/">Other platforms and older versions</a>
        </div>
      </section>

      {/* Trailer slot: T19.2 swaps this still for the WebM trailer. */}
      <section className="wrap trailer" aria-label="The app">
        <div className="frame">
          <Shot name="visuals" priority sizes="(min-width: 1160px) 1108px, 96vw"
            alt={`${NAME}'s Visuals stage with the bundled example, The Tube Mail: an 1880s envelope chosen for the first paragraph.`} />
        </div>
      </section>


      <section id="shots" className="wrap kinds" aria-labelledby="kinds-title">
        <header>
          <span className="label">Every kind of shot</span>
          <h2 id="kinds-title">Not just pictures</h2>
          <p>The writing model chooses a shot for each paragraph, and code draws it. Everything here is rendered on your own computer.</p>
        </header>
        <ul className="kind-grid">
          {KINDS.map((k) => (
            <li key={k.title} className="kind">
              {k.shot
                ? <div className="frame small"><Shot name={k.shot} alt={`${k.title}: a frame from a ${NAME} video.`} sizes="(min-width: 1100px) 260px, (min-width: 700px) 45vw, 92vw" /></div>
                : <div className="frame small blank" aria-hidden="true"><span>{k.title}</span></div>}
              <h3>{k.title}</h3>
              <p>{k.text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section id="features" className="wrap features" aria-labelledby="features-title">
        <header>
          <span className="label">What it does</span>
          <h2 id="features-title">From idea to finished video</h2>
        </header>
        {FEATURES.map((f) => (
          <article className="feature" key={f.shot}>
            <div className="frame"><Shot name={f.shot} alt={f.alt} /></div>
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
