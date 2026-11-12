import Shot from '@/components/Shot';
import DownloadButton from '@/components/DownloadButton';
import Trailer from '@/components/Trailer';
import { TRAILER } from '@/lib/media';
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
    text: 'Archive pictures and film, animated blocks, 3D scenes, or a whole scene the agent writes in HTML.',
    alt: 'The Visuals stage: picture groups, a chosen archive envelope and the source panel.' },
  { shot: 'blocks', label: 'Blocks', title: 'Titles, charts and maps you fill in',
    text: 'Animated blocks for titles, numbers and places. You type the words; they render on your machine.',
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

      {/* The trailer, or the Visuals still until site/tools/trailer.py has run. */}
      <section className="wrap trailer" aria-label="The app">
        {TRAILER
          ? <Trailer label={`A silent tour of ${NAME}: the stages, archive film, blocks and 3D scenes.`} />
          : <div className="frame"><Shot name="visuals" priority sizes="(min-width: 1160px) 1108px, 96vw"
              alt={`${NAME}'s Visuals stage with the bundled example, The Tube Mail.`} /></div>}
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
