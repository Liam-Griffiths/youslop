# Corkbored marketing plan

As of 2026-10-26 · Liam Griffiths

Corkbored is marketed through one channel: Liam's own videos on AI, humanoid
robots and the future of society. Each one is made with Corkbored and says so in
a slate after the intro. The videos prove the tool, and the tool's story feeds
the channel.

## Positioning

Corkbored is for people who know a subject and can write about it, but cannot or
will not spend weeks editing. It turns their thinking into a finished, sourced
episode on their own machine.

- **Tagline:** Idea in. Episode out.
- **Say:** researched, sourced, your own words, your own taste, runs on your
  computer, every frame checked before you publish.
- **Never say:** faceless, passive income, scale to 100 channels, post every
  day. That is the AI-slop crowd, and YouTube's rules on mass-produced content
  penalise them. Being associated with them costs more than the sales they
  bring.
- **The origin story is an asset.** The project began as Youslop, a joke
  about AI slop, and grew into a serious studio. Tell it once in the README and
  once in the launch video, not in the product itself.

## The channel

The channel is about the future of society once AI and humanoid robots arrive,
a subject Liam already writes about often. That makes it the best possible
demo, because the channel practises its own argument: a human doing the
thinking, with AI doing the labour.

- **Start from existing writing.** Corkbored's script import has a faithful mode
  that keeps the author's words and adapts them only for the ear. Every essay
  already written is a near-finished episode.
- **Read it in your own voice.** A channel about humans and machines lands
  harder when a human narrates it. Use mic takes; keep Kokoro for drafts and
  shorts.
- **It shows off every format.** Reflective essays suit the essay cut.
  Arguments with stages suit boards and diagrams. Economic data suits the
  Ticker cut. How a robot actually moves or works suits the 3D explainer.
- **It shows off the research.** These topics are full of hype and contested
  claims. Sourced facts, the fact-check pass and on-screen sources are a
  visible difference from the competition.
- **News and evergreen together.** Robot and AI announcements give timely
  hooks. The questions underneath (work, care, loneliness, ownership) stay
  searchable for years.

## First episodes

Starter topics to choose from or replace with existing essays. Each is matched
to the format that shows Corkbored best.

| # | Working title | Format | What it shows off |
|---|---|---|---|
| 1 | How YouTube's Algorithm Learned to Love Slop | Essay | The launch video. Already researched and recorded; finish it with the new pipeline. |
| 2 | How I made that video (the making-of) | Essay + screen captures | The Timeline, the review catching problems, the Ask agent. |
| 3 | Who looks after us when the carers are robots? | Essay | Research and sources on a human question. |
| 4 | How a humanoid robot keeps its balance | 3D explainer | The 3D camera and shot checks. Needs a robot model with a licence that allows it. |
| 5 | What happens to wages when labour gets cheap? | Ticker cut | Charts and figures, every one sourced. |
| 6 | Five jobs robots will not take, and why | Board | Arguments laid out step by step. |
| 7 | One question about AI, in 90 seconds | Loudmouth short | Kinetic type, made in minutes; a weekly short. |

Use only 3D models whose licence allows it, and avoid branded commercial robots
unless their maker's terms allow it. Credit models in the description; Corkbored
records the licence when a model is added.

## The "Made with Corkbored" slate

The slate comes **after the intro**, which is the right place: the first three
seconds stay for the hook, and the credit arrives once the viewer has decided
to stay.

- **Keep it short:** about 1.5 seconds, still, no sting. A longer slate costs
  retention on every video, including the ones that might go viral.
- **Make it the same every time**, so regular viewers stop noticing it while
  new viewers still read it. Build it as a scene card (T2.6) so it uses the
  channel's colours.
- **Put the link where people can act on it:** the first line of the
  description ("Made with Corkbored: <link>"), and a pinned comment on videos
  that take off.
- **Check the cost:** compare audience retention at the slate's timestamp
  against the seconds either side, across the first five videos. If retention
  drops there, shorten the slate or move the credit to the end card.

## Where to show up

Each place wants a different part of the work.

| Place | What to show | When |
|---|---|---|
| Your YouTube channel | Full episodes; the making-of | From now, every two weeks |
| YouTube Shorts, TikTok, Reels | 30-second clips of the product: the 3D camera solving a shot, the review pinning the weakest shot, before and after | Weekly, starting now |
| X / Bluesky / LinkedIn | Build-in-public posts: one finished ticket and its clip | Weekly |
| Hacker News (Show HN) | Local-first engineering: no Node, Chromium capture with only Python's standard library, a free check layer before any paid AI review | Once, when installing is easy |
| r/LocalLLaMA, r/selfhosted | Runs on your machine; Kokoro voices; Ollama support | Around the HN launch |
| Claude Code users | Driving the whole studio from Claude Code through the skill (T3.5) | When T3.5 ships |
| Product Hunt | The launch video plus the landing page | After HN, once there are real users |

## Weekly rhythm

What one person can sustain alongside building the product:

| How often | What | Time |
|---|---|---|
| Every two weeks | One long episode from an existing essay | About one day |
| Weekly | Two or three short product clips, made with Corkbored | About two hours |
| Weekly | One build-in-public post | Under an hour |
| Monthly | Read retention and comments; pick the next topics from what people ask | An hour |

## Timeline

The launch is gated on the roadmap, not on dates, because the product has to
look as good as the claims.

1. **Now (Phase 0):** finish the rename (T0.1–T0.4) so the name is fixed
   everywhere. Add email capture to `static/landing.html` and host it. Check
   the trademark for "Corkbored" (corkbored.com is already held) and buy
   corkboard domains to redirect where cheap.
2. **Channel soft launch:** publish the slop video and its making-of on the
   current pipeline. No big announcement; this is practice and early proof.
3. **After Phase 1 (doctrine and check):** episodes every two weeks; short
   clips weekly; build-in-public posts begin.
4. **After Phase 2 (scene engine):** the videos look visibly better than
   anything the old Pillow drawing could do. Open the waitlist beta to the
   first users.
5. **After T3.5 (CLI and skill) and an easy installer:** the public launch.
   Show HN, Reddit and the Claude Code angle in the same week, with the best
   episode so far as the headline.
6. **After launch:** Product Hunt; a showcase page of videos other people made
   with Corkbored.

## Business model

Decided 2026-10-26: **free and open now, content packs later.**

- **The app stays free and GPL, with a public promise:** everything free
  today stays free. Paid things are extras, never features taken away.
- **Packs are content, not code:** themes, scene templates (intros, chapter
  cards, end cards, segment looks), music beds, curated 3D models and fonts.
  Because they are not part of the GPL app, selling them does not depend on a
  paywall anyone could fork away. Tickets: `docs/tickets/08-packs/`.
- **The format is open.** Anyone can make and share packs; a free Starter
  pack ships with the app. Free community packs grow the ecosystem the paid
  ones sell into.
- **How it sells, in order:**
  1. Free Starter pack in the app; the format spec published.
  2. The first paid packs as one-off downloads (around $5-15 each) through a
     merchant of record (Lemon Squeezy or Paddle), which handles VAT. No
     licence keys or copy protection; the buyer installs the file.
  3. If packs sell: a "Pack Club" membership at $5/month or $48/year, with
     every pack and a new one each month. Founding members get a lifetime
     price.
- **Pack themes that fit the channel:** an essay pack (the look of your own
  channel), a documentary/archive pack, a 3D explainer pack with cleared
  models (robots and machines suit your topic), and packs per format.
- **Rights:** everything in a paid pack must be your own work or carry a
  licence that allows resale (CC0, or commissioned with the rights). Never
  bundle attribution-only or non-commercial items.
- **Later, if wanted:** cloud services (rendering while the laptop is off,
  scheduled publishing) as a higher tier, because they cost real money to
  run.
- **Now:** GitHub Sponsors or Ko-fi from launch, an email list on the
  landing page, and the trademark check.

## Open decisions and risks

**Decisions**

- [ ] What success means first: income, users, or reputation. This decides the
      business model.
- [x] Business model: the app stays free and GPL; money comes later from
      content packs (see "Business model" below).
- [ ] Contributor agreement (CLA Assistant) before the first outside pull
      request, so relicensing and a paid add-on stay possible.
- [ ] Check the employment contract covers this project (one early commit
      used a work email).
- [x] Domain: corkbored.com (held).
- [ ] Trademark for "Corkbored"; corkboard look-alike domains to redirect.
- [ ] Where the landing page is hosted, and what collects the emails.

**Risks**

- **The AI-slop label.** A channel about AI made with AI invites the
  accusation. The answer is in the work: your own writing, your own voice,
  sources on screen.
- **YouTube policy.** The rules on mass-produced and repetitive content target
  exactly what Corkbored must not be used for. Keep every message about quality,
  never volume.
- **Time.** One person building and publishing. If the rhythm slips, drop the
  social posts before the episodes; the episodes are the proof.
- **Rights.** Pictures, footage, 3D models and music all need licences that
  allow use. Corkbored records credits; keep them in every description.
