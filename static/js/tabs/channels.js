
function setCastFocal(i) {
  const c = state.channel;
  const img = (c.intro.images || [])[i];
  if (!img) return toast('Fetch the portraits first.', true);
  const current = (c.intro.focals || [])[i] || [];
  openFocal(`/api/channels/${c.id}/file/${img}?v=${c.updated_at}`, current, (focal) => {
    const focals = [...(c.intro.focals || [])];
    while (focals.length < c.intro.images.length) focals.push([]);
    focals[i] = focal;
    saveIntro({ focals });
  });
}

// ----------------------------------------------------------------- channel
async function refreshChannel() {
  state.channel = await api(`/api/channels/${state.channel.id}`);
  await paintChannel();
}

// A 140×78 sketch of the three ways a picture can sit on screen — "I need to
// be able to select templates for videos, with a basic preview" — matching
// the same illustrative-icon pattern tplArt/thumbArt already use elsewhere,
// so this is one more instance of a pattern rather than a new one.
function formatArt(key, accent) {
  const a = esc(accent);
  const svg = {
    kenburns: `<rect width="140" height="78" fill="#1c222c"/>
      <rect x="-6" y="-4" width="152" height="90" fill="#2a3444"/>
      <circle cx="96" cy="26" r="30" fill="#374254" opacity=".6"/>
      <rect x="0" y="54" width="140" height="24" fill="#000" opacity=".38"/>
      <rect x="10" y="60" width="5" height="12" fill="${a}"/>
      <rect x="20" y="61" width="52" height="4" fill="#fff"/>
      <rect x="20" y="68" width="34" height="3" fill="#9aa0b0"/>`,
    essay: `<rect width="140" height="78" fill="#15171c"/>
      <rect x="0" y="0" width="140" height="78" fill="#1e222b"/>
      <rect x="30" y="8" width="80" height="46" fill="#2a3444"/>
      <rect x="30" y="8" width="80" height="46" fill="none" stroke="${a}" stroke-width="3"/>
      <rect x="18" y="60" width="104" height="7" fill="#fff" opacity=".92"/>
      <rect x="30" y="70" width="80" height="5" fill="#fff" opacity=".55"/>`,
    board: `<rect width="140" height="78" fill="#3A4552"/>
      <path d="M12 20h46" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M12 24h30" stroke="${a}" stroke-width="2" stroke-linecap="round"/>
      <path d="M14 38h10M14 50h10M14 62h10" stroke="#aab0bc" stroke-width="2" stroke-linecap="round"/>
      <path d="M30 38h58M30 50h46M30 62h50" stroke="#fff" stroke-width="2.6" stroke-linecap="round" opacity=".9"/>`,
    flameboat: `<rect width="140" height="78" fill="#0E1014"/>
      <rect x="22" y="14" width="96" height="50" rx="4" fill="#151922" stroke="#2A3140"/>
      <circle cx="29" cy="20" r="2" fill="#FF5F57"/><circle cx="35" cy="20" r="2" fill="#FEBC2E"/>
      <circle cx="41" cy="20" r="2" fill="#28C840"/>
      <rect x="28" y="30" width="22" height="4" fill="#FF7AB6"/><rect x="53" y="30" width="30" height="4" fill="#5FD4FF"/>
      <rect x="24" y="39" width="92" height="7" fill="${a}" opacity=".3"/>
      <rect x="34" y="40" width="44" height="4" fill="#E8EAF0"/>
      <rect x="28" y="51" width="36" height="4" fill="#A8E07A"/>`,
    casefile: `<defs><radialGradient id="cfv"><stop offset=".55" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000" stop-opacity=".7"/></radialGradient></defs>
      <rect width="140" height="78" fill="#5a3a20"/>
      <rect x="18" y="12" width="34" height="40" fill="#efe9dc" transform="rotate(-5 35 32)"/>
      <rect x="22" y="15" width="26" height="25" fill="#3b4a5c" transform="rotate(-5 35 32)"/>
      <rect x="78" y="30" width="44" height="28" fill="#f6f2e6" transform="rotate(4 100 44)"/>
      <rect x="80" y="38" width="38" height="1.5" fill="#d65c5c" transform="rotate(4 100 44)"/>
      <circle cx="35" cy="16" r="2.6" fill="#b21c22"/><circle cx="99" cy="31" r="2.6" fill="#b21c22"/>
      <rect width="140" height="78" fill="url(#cfv)"/>`,
    loudmouth: `<rect width="140" height="78" fill="#0B0B0D"/>
      <text x="16" y="24" font-family="sans-serif" font-size="9" font-weight="700" fill="#8D8A84">you are not</text>
      <text x="14" y="50" font-family="sans-serif" font-size="27" font-weight="900" fill="${a}">behind.</text>
      <text x="122" y="16" font-family="sans-serif" font-size="13" font-weight="900" fill="#F4F1EA"
        transform="rotate(90 122 16)">too late</text>
      <text x="16" y="68" font-family="sans-serif" font-size="13" font-weight="900" fill="#F4F1EA">decide.</text>`,
    groupchat: `<rect width="140" height="78" fill="#1d2433"/>
      <rect x="34" y="4" width="72" height="70" rx="8" fill="#0B0B0F"/>
      <rect x="34" y="4" width="72" height="12" rx="6" fill="#16161C"/>
      <rect x="40" y="22" width="34" height="9" rx="4.5" fill="#26262E"/>
      <rect x="62" y="35" width="38" height="9" rx="4.5" fill="#2E7CF6"/>
      <rect x="40" y="48" width="28" height="9" rx="4.5" fill="#26262E"/>
      <circle cx="46" cy="64" r="1.6" fill="#8C8C99"/><circle cx="51" cy="64" r="1.6" fill="#8C8C99"/>
      <circle cx="56" cy="64" r="1.6" fill="#8C8C99"/>`,
    ticker: `<rect width="140" height="78" fill="#060A12"/>
      <rect width="140" height="8" fill="#0C1220"/>
      <path d="M14 56 L34 48 L52 52 L72 34 L92 38 L112 20 L126 24" stroke="#1FD686" stroke-width="2.4" fill="none"/>
      <path d="M14 56 L34 48 L52 52 L72 34 L92 38 L112 20 L126 24 L126 66 L14 66Z" fill="#1FD686" opacity=".14"/>
      <circle cx="126" cy="24" r="3" fill="#1FD686"/>
      <rect x="14" y="12" width="34" height="3" fill="${a}"/>`,
    stage: `<rect width="140" height="78" fill="#1d232a"/>
      <ellipse cx="70" cy="60" rx="50" ry="9" fill="#313943"/>
      <path d="M22 36 A50 15 0 0 1 118 36" fill="none" stroke="${a}" stroke-width="1.5"
            stroke-dasharray="4 4" opacity=".75"/>
      <circle cx="118" cy="36" r="3" fill="${a}"/>
      <path d="M38 52 L100 45 L105 48 L42 56 Z" fill="#d9dde6"/>
      <path d="M64 50 L54 38 L61 38 L76 49 Z" fill="#b9c0cc"/>
      <path d="M70 52 L84 63 L91 63 L80 51 Z" fill="#c6ccd8"/>
      <path d="M97 46 L103 35 L107 35 L104 47 Z" fill="${a}"/>`,
  }[key] || '<rect width="140" height="78" fill="#14151a"/>';
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">${svg}</svg>`;
}

// A 140×78 sketch of each slate, so the picker shows the shape of the thing
// rather than seven lines of prose. Accent-coloured parts mirror the channel's.
function tplArt(key, accent) {
  const a = esc(accent), ink = '#8d93a2', dim = '#2b2f3a';
  const svg = {
    columns: `<rect width="140" height="78" fill="#0c0d11"/>
      ${[0, 1, 2, 3, 4].map((i) => `<rect x="${2 + i * 27.6}" y="2" width="25" height="74"
        fill="${i % 2 ? '#232732' : '#161a22'}"/>`).join('')}
      <rect x="34" y="36" width="72" height="3" fill="${a}"/>`,
    signal: `<rect width="140" height="78" fill="#0a0b0f"/>
      ${[18, 38, 58].map((y) => `<line x1="0" y1="${y}" x2="140" y2="${y}" stroke="#181c24"/>`).join('')}
      <rect x="16" y="26" width="70" height="12" fill="${ink}"/>
      <rect x="88" y="26" width="6" height="12" fill="${a}"/>
      <rect x="16" y="44" width="44" height="12" fill="${dim}"/>
      <rect x="10" y="20" width="3" height="42" fill="${a}"/>`,
    dossier: `<rect width="140" height="78" fill="#111114"/>
      <rect x="6" y="5" width="128" height="68" fill="none" stroke="${a}" stroke-width="1.5"/>
      <rect x="18" y="18" width="52" height="10" fill="${ink}"/>
      <rect x="70" y="18" width="42" height="10" fill="#17171b" stroke="${a}" stroke-width="1"/>
      ${[40, 48, 56].map((y) => `<rect x="18" y="${y}" width="${58 - (y - 40)}" height="3" fill="${dim}"/>`).join('')}
      <g transform="rotate(-9 104 56)"><rect x="86" y="46" width="36" height="18" fill="none"
        stroke="${a}" stroke-width="2"/></g>`,
    filmstrip: `<rect width="140" height="78" fill="#0a0a0c"/>
      <rect x="0" y="16" width="140" height="46" fill="#12141a"/>
      ${[6, 40, 74, 108].map((x) => `<rect x="${x}" y="19" width="28" height="40" fill="#232732"/>`).join('')}
      ${[4, 24, 44, 64, 84, 104, 124].map((x) => `<rect x="${x}" y="4" width="10" height="6" rx="1.5" fill="#2c303a"/>
        <rect x="${x}" y="68" width="10" height="6" rx="1.5" fill="#2c303a"/>`).join('')}
      <rect x="0" y="14" width="140" height="1.5" fill="${a}"/>`,
    mosaic: `<rect width="140" height="78" fill="#0c0d11"/>
      ${[0, 1, 2].map((r) => [0, 1, 2, 3].map((cc) => `<rect x="${cc * 35 + 1}" y="${r * 26 + 1}"
        width="33" height="24" fill="${(r + cc) % 3 ? '#1c2029' : '#262b36'}"/>`).join('')).join('')}
      <rect x="0" y="30" width="140" height="18" fill="#0a0b0f" opacity=".92"/>
      <rect x="0" y="30" width="140" height="1.5" fill="${a}"/>
      <rect x="0" y="46.5" width="140" height="1.5" fill="${a}"/>
      <rect x="46" y="36" width="48" height="6" fill="${ink}"/>`,
    pulse: `<rect width="140" height="78" fill="#0b0c10"/>
      <rect x="24" y="20" width="92" height="7" fill="${ink}"/>
      <line x1="0" y1="56" x2="140" y2="56" stroke="${a}" stroke-width="1.5"/>
      ${Array.from({ length: 22 }, (_, i) => {
        const h = 3 + 13 * Math.abs(Math.sin(i * 1.1)) * Math.sin(Math.PI * (i + 0.5) / 22);
        return `<rect x="${i * 6.4 + 1}" y="${56 - h}" width="4" height="${h * 2}" fill="${a}" opacity=".62"/>`;
      }).join('')}`,
    atlas: `<rect width="140" height="78" fill="#080a0c"/>
      ${[0, 1, 2].map((i) => `<ellipse cx="46" cy="44" rx="${14 + i * 11}" ry="${10 + i * 8}"
        fill="none" stroke="${i === 2 ? a : '#22262e'}" stroke-width="1"/>`).join('')}
      <line x1="0" y1="34" x2="140" y2="34" stroke="${a}" stroke-width=".8" opacity=".45"/>
      <line x1="92" y1="0" x2="92" y2="78" stroke="${a}" stroke-width=".8" opacity=".45"/>
      <g stroke="${a}" stroke-width="2" fill="none">
        <path d="M78 20h-6v6M106 20h6v6M78 48h-6v-6M106 48h6v-6"/></g>
      <circle cx="92" cy="34" r="3" fill="none" stroke="${a}" stroke-width="1.5"/>`,
    dial: `<rect width="140" height="78" fill="#0a0b0f"/>
      <circle cx="70" cy="39" r="33" fill="#15181f" stroke="${a}" stroke-width="1.4"/>
      ${[0,1,2,3,4,5,6,7,8,9,10,11].map((h) => {
        const r = h * 30 * Math.PI / 180;
        const s = Math.sin(r), c = -Math.cos(r);
        return `<line x1="${70 + s * 29}" y1="${39 + c * 29}"
                      x2="${70 + s * 24}" y2="${39 + c * 24}"
                      stroke="${a}" stroke-width="${h % 3 ? 1.4 : 2.2}"/>`;
      }).join('')}
      <line x1="70" y1="39" x2="${70 - 14}" y2="${39 - 10}" stroke="${a}" stroke-width="2.4"/>
      <line x1="70" y1="39" x2="${70 + 18}" y2="${39 - 11}" stroke="${a}" stroke-width="1.8"/>
      <circle cx="70" cy="39" r="2.2" fill="${a}"/>
      <rect x="57" y="20" width="26" height="3" rx="1" fill="${ink}"/>
      <rect x="52" y="54" width="36" height="2.4" rx="1" fill="${dim}"/>`,
    arcade: `<rect width="140" height="78" fill="#1b0f3a"/>
      ${[0, 1, 2, 3].map((r) => [0, 1, 2, 3, 4].map((c) => `<rect
        x="${c * 30 + (r % 2 ? 6 : -9)}" y="${r * 20 + 4}" width="9" height="7" rx="2"
        fill="${c % 2 ? a : ink}" opacity=".26"/>`).join('')).join('')}
      <rect x="26" y="24" width="86" height="15" fill="${a}" opacity=".9"/>
      <rect x="30" y="27" width="86" height="15" fill="#fff"/>
      <rect x="38" y="46" width="70" height="15" fill="${a}" opacity=".9"/>
      <rect x="42" y="49" width="70" height="15" fill="#fff"/>
      <rect x="46" y="70" width="48" height="3" fill="${a}"/>`,
    gloss: `<rect width="140" height="78" fill="#f6dce6"/>
      <ellipse cx="70" cy="34" rx="58" ry="34" fill="#fdeef4"/>
      ${[[18, 14], [116, 20], [30, 62], [110, 58], [64, 10]].map(([x, y]) =>
        `<path d="M${x} ${y - 5}l1.6 3.4 3.4 1.6-3.4 1.6-1.6 3.4-1.6-3.4-3.4-1.6 3.4-1.6z"
          fill="#fff"/>`).join('')}
      <rect x="34" y="34" width="72" height="10" fill="#3a2a31"/>
      <rect x="46" y="26" width="48" height="2.4" fill="${a}"/>
      <rect x="42" y="50" width="56" height="1.6" fill="${a}"/>`,
    kickoff: `<rect width="140" height="78" fill="#0b2545"/>
      ${[0, 1, 2, 3, 4, 5].map((i) => `<path d="M${i * 26 - 14} 78L${i * 26 + 8} 0h11L${i * 26 - 3} 78z"
        fill="${a}" opacity=".85"/>`).join('')}
      <path d="M0 26l140-16v46L0 66z" fill="#0d1c2e" opacity=".96"/>
      <rect x="0" y="24" width="140" height="2.6" fill="${a}"
        transform="rotate(-6.5 70 39)"/>
      <g transform="rotate(-6.5 70 39)"><rect x="34" y="32" width="58" height="13" fill="#fff"/>
        <rect x="46" y="20" width="34" height="7" fill="${a}"/></g>`,
    stack: `<rect width="140" height="78" fill="#160810"/>
      ${[0, 1, 2, 3].map((r) => `<text x="${-14 + r * 9}" y="${16 + r * 20}"
        font-family="Helvetica" font-weight="bold" font-size="17"
        fill="${r % 2 ? 'none' : a}" stroke="${r % 2 ? a : 'none'}" stroke-width="1"
        opacity=".55" transform="rotate(-9 70 39)">NAME NAME NAME</text>`).join('')}
      <rect x="0" y="28" width="140" height="24" fill="#160810" opacity=".95"/>
      <rect x="0" y="27" width="140" height="1.8" fill="${a}"/>
      <rect x="0" y="52" width="140" height="1.8" fill="${a}"/>
      <rect x="40" y="35" width="60" height="10" fill="#fff"/>`,
    tiles: `<rect width="140" height="78" fill="#efe3cf"/>
      ${[0, 1, 2].map((r) => [0, 1, 2, 3, 4].map((c) => `<rect x="${c * 28 + 1}"
        y="${r * 26 + 1}" width="26" height="24"
        fill="${(r + c) % 2 ? '#e8b7a4' : '#c8d3ac'}"/>`).join('')).join('')}
      <rect x="24" y="20" width="92" height="38" rx="3" fill="#fdfbf6"
        stroke="${a}" stroke-width="1.6"/>
      <rect x="44" y="26" width="52" height="3" fill="${a}"/>
      <rect x="36" y="34" width="68" height="9" fill="#2e241c"/>
      <rect x="48" y="46" width="44" height="7" fill="#2e241c"/>`,
    folio: `<rect width="140" height="78" fill="#cec7b8"/>
      <rect x="9" y="0" width="131" height="78" fill="#eee9de"/>
      <rect x="9" y="0" width="2" height="78" fill="#b4ab98"/>
      <rect x="40" y="14" width="70" height="1.6" fill="${a}"/>
      <rect x="48" y="18" width="54" height="1" fill="${a}" opacity=".7"/>
      <rect x="52" y="26" width="46" height="3" fill="#8d8676"/>
      <rect x="38" y="35" width="74" height="9" fill="#26231f"/>
      <rect x="50" y="48" width="50" height="9" fill="#26231f"/>
      <rect x="52" y="63" width="14" height="1.4" fill="${a}"/>
      <rect x="84" y="63" width="14" height="1.4" fill="${a}"/>
      <path d="M75 60l4 3.7-4 3.7-4-3.7z" fill="${a}"/>`,
  }[key] || '<rect width="140" height="78" fill="#14151a"/>';
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">${svg}</svg>`;
}

// The same 140×78 treatment for the end screens. What each sketch has to show
// is where the plates are, because that is the whole difference between them.
function endArt(key, accent) {
  const a = esc(accent), ink = '#8d93a2', panel = '#1a1e26';
  const plate = (x, y, w, h, r = 2) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${panel}"
       stroke="${a}" stroke-width=".8" stroke-opacity=".55"/>`;
  const svg = {
    twoup: `<rect width="140" height="78" fill="#0c0d11"/>
      <circle cx="26" cy="42" r="11" fill="none" stroke="${a}" stroke-width="1.4"/>
      <rect x="42" y="38" width="24" height="8" rx="4" fill="${a}" opacity=".8"/>
      <rect x="15" y="18" width="46" height="6" fill="${ink}"/>
      ${plate(74, 26, 28, 28)}${plate(106, 26, 28, 28)}
      <rect x="74" y="19" width="60" height="3" fill="${ink}" opacity=".7"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    marquee: `<rect width="140" height="78" fill="#0b0c10"/>
      <rect x="28" y="8" width="84" height="10" fill="${ink}"/>
      <rect x="50" y="23" width="40" height="1.6" fill="${a}"/>
      ${plate(20, 30, 46, 26)}${plate(74, 30, 46, 26)}
      <circle cx="58" cy="66" r="7" fill="none" stroke="${a}" stroke-width="1.2"/>
      <rect x="70" y="62" width="22" height="8" rx="4" fill="${a}" opacity=".8"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    afterglow: `<rect width="140" height="78" fill="#1b1d22"/>
      <ellipse cx="44" cy="26" rx="34" ry="24" fill="#2b2f38"/>
      <ellipse cx="104" cy="46" rx="30" ry="26" fill="#23262e"/>
      <rect y="34" width="140" height="44" fill="#07080b" opacity=".72"/>
      <circle cx="24" cy="34" r="9" fill="none" stroke="${a}" stroke-width="1.3"/>
      <rect x="13" y="52" width="40" height="6" fill="${ink}"/>
      ${plate(74, 30, 28, 28)}${plate(106, 30, 28, 28)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    console: `<rect width="140" height="78" fill="#0a0b0f"/>
      ${[0, 1, 2, 3].map((i) => `<line x1="0" y1="${i * 20 + 9}" x2="140" y2="${i * 20 + 9}"
        stroke="#171b22"/><line x1="${i * 36 + 10}" y1="0" x2="${i * 36 + 10}" y2="78"
        stroke="#171b22"/>`).join('')}
      <rect x="8" y="12" width="4" height="18" fill="${a}"/>
      <rect x="17" y="14" width="52" height="9" fill="${ink}"/>
      <circle cx="122" cy="20" r="10" fill="none" stroke="${a}" stroke-width="1.3"/>
      ${[16, 54, 92].map((x) => plate(x, 40, 32, 28)).join('')}
      ${[16, 54, 92].map((x) => `<path fill="none" stroke="${a}" stroke-width="1.4"
        d="M${x} 46V40h6 M${x + 32} 40h-6 M${x + 32} 40v6
           M${x} 62v6h6 M${x + 32} 68h-6 M${x + 32} 68v-6"/>`).join('')}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    ledger: `<rect width="140" height="78" fill="#eee9de"/>
      <rect x="42" y="7" width="56" height="1.8" fill="${a}" opacity=".8"/>
      <rect x="48" y="13" width="44" height="4" fill="#8d8676"/>
      <rect x="38" y="21" width="64" height="7" fill="#26231f"/>
      <rect x="26" y="34" width="38" height="28" rx="1" fill="#faf7f0" stroke="#c8c0ae"/>
      <rect x="76" y="34" width="38" height="28" rx="1" fill="#faf7f0" stroke="#c8c0ae"/>
      <circle cx="58" cy="70" r="6" fill="#faf7f0" stroke="#a49a86"/>
      <rect x="70" y="68" width="26" height="3" fill="#8d8676"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}" opacity=".75"/>`,
    arcade: `<rect width="140" height="78" fill="#1b0f3a"/>
      ${[0, 1, 2, 3].map((r) => [0, 1, 2, 3, 4].map((c) => `<rect
        x="${c * 30 + (r % 2 ? 6 : -9)}" y="${r * 20 + 4}" width="8" height="6" rx="2"
        fill="${c % 2 ? a : ink}" opacity=".24"/>`).join('')).join('')}
      <rect x="10" y="16" width="46" height="9" fill="${a}" opacity=".9"/>
      <rect x="12" y="14" width="46" height="9" fill="#fff"/>
      <circle cx="22" cy="44" r="10" fill="#241650" stroke="${a}" stroke-width="1.4"/>
      <rect x="36" y="40" width="24" height="8" rx="4" fill="${a}"/>
      ${plate(74, 26, 28, 28)}${plate(106, 26, 28, 28)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    gloss: `<rect width="140" height="78" fill="#f6dce6"/>
      <ellipse cx="70" cy="30" rx="60" ry="32" fill="#fdeef4"/>
      <rect x="46" y="9" width="48" height="7" fill="#3a2a31"/>
      <rect x="54" y="20" width="32" height="2" fill="${a}"/>
      <rect x="30" y="28" width="34" height="30" rx="2" fill="#fffdf9" stroke="${a}"/>
      <rect x="76" y="28" width="34" height="30" rx="2" fill="#fffdf9" stroke="${a}"/>
      <circle cx="62" cy="68" r="7" fill="#fffdf9" stroke="${a}"/>
      <rect x="74" y="66" width="26" height="3" fill="#8a6b76"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}" opacity=".8"/>`,
    sideline: `<rect width="140" height="78" fill="#0b2545"/>
      ${[0, 1, 2, 3, 4, 5].map((i) => `<path d="M${i * 26 - 14} 78L${i * 26 + 8} 0h10L${i * 26 - 4} 78z"
        fill="${a}" opacity=".8"/>`).join('')}
      <path d="M0 22l140-16v48L0 70z" fill="#0d1c2e" opacity=".96"/>
      <rect x="10" y="30" width="42" height="8" fill="#fff"/>
      <circle cx="20" cy="52" r="8" fill="#12263d" stroke="${a}" stroke-width="1.3"/>
      ${plate(74, 24, 28, 28)}${plate(106, 24, 28, 28)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    wordmark: `<rect width="140" height="78" fill="#160810"/>
      ${[0, 1, 2, 3].map((r) => `<text x="${-16 + r * 11}" y="${15 + r * 21}"
        font-family="Helvetica" font-weight="bold" font-size="16"
        fill="${r % 2 ? 'none' : a}" stroke="${r % 2 ? a : 'none'}" stroke-width="1"
        opacity=".28" transform="rotate(-9 70 39)">NAME NAME NAME</text>`).join('')}
      <rect x="0" y="6" width="140" height="20" fill="#160810" opacity=".95"/>
      <rect x="0" y="5" width="140" height="1.6" fill="${a}"/>
      <rect x="0" y="26" width="140" height="1.6" fill="${a}"/>
      <rect x="44" y="11" width="52" height="9" fill="#fff"/>
      ${plate(20, 34, 30, 26)}${plate(55, 34, 30, 26)}${plate(90, 34, 30, 26)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    quiet: `<rect width="140" height="78" fill="#090a0d"/>
      <rect x="60" y="14" width="20" height="1.4" fill="${a}"/>
      <rect x="46" y="21" width="48" height="5" fill="${ink}"/>
      ${plate(38, 34, 28, 26)}${plate(74, 34, 28, 26)}
      <circle cx="70" cy="68" r="6" fill="none" stroke="${a}" stroke-width="1.2"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
  }[key] || '<rect width="140" height="78" fill="#14151a"/>';
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">${svg}</svg>`;
}

// The preview area, in whichever of its three states applies.
//
// `kind` is the job kind the server uses, so a running render can be matched to
// the panel that asked for it: previewing the slate must not put the end
// screen's panel into a spinner. The cache-buster is the rendered file's own
// mtime rather than the channel's updated_at, because rendering a preview does
// not touch the channel record — busting on updated_at hands the browser back
// the file it already has, and a second preview looks identical to the first
// however different the settings were.
function previewStage(c, kind, file, stamp) {
  const job = state.job;
  const running = job && !job.done && job.kind === kind;
  if (running) {
    const line = (job.lines || []).slice(-1)[0] || job.tagline || 'Preparing the preview…';
    return `
      <h3 style="margin-top:24px">Preview</h3>
      <div class="rendering">
        <div class="rendering-art">
          <span class="rendering-bar"></span><span class="rendering-bar"></span>
          <span class="rendering-bar"></span>
        </div>
        <div class="rendering-say">
          <strong>Rendering…</strong>
          <span class="mono" id="renderline">${esc(line)}</span>
        </div>
      </div>`;
  }
  if (!stamp) return '';
  return `
    <h3 style="margin-top:24px">Preview</h3>
    <p class="mono">Preview engine: ${(file.includes('outro') ? c.outro.template : c.intro.template).startsWith('scene:') ? 'Chromium scenes' : 'Pillow'}</p>
    ${videoTag(`/api/channels/${c.id}/file/${file}?v=${stamp}`,
               { scope: 'channel', id: c.id, rel: file })}`;
}

// A theme swatch: the two colours it writes into the channel, its ground, and a
// few of the icons its patterns are tiled from. That is the whole decision.
function themeArt(t) {
  const glyph = (x, y, c) => `<circle cx="${x}" cy="${y}" r="5.5" fill="${c}"
    opacity=".55"/>`;
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">
    <rect width="140" height="78" fill="${esc(t.ground)}"/>
    ${[18, 46, 74, 102, 126].map((x, i) =>
      glyph(x, 20 + (i % 2) * 12, i % 2 ? esc(t.accent2) : esc(t.accent))).join('')}
    <rect x="0" y="44" width="140" height="34" fill="${esc(t.ground)}" opacity=".55"/>
    <rect x="12" y="52" width="58" height="8" rx="4" fill="${esc(t.accent)}"/>
    <rect x="76" y="52" width="52" height="8" rx="4" fill="${esc(t.accent2)}"/>
    <rect x="12" y="66" width="116" height="4" rx="2" fill="${esc(t.ink)}" opacity=".5"/>
  </svg>`;
}

// Casting a channel in a theme. Two buttons rather than one, because a channel
// that has settled on a slate should be able to take the colours without
// losing it — which is the only question this panel actually has to ask.
function themePanel(c) {
  const list = state.themes || [];
  const cur = c.style.theme || 'archive';
  const t = list.find((x) => x.key === cur) || {};
  const slate = (state.templates || []).find((x) => x.key === c.intro.template);
  const end = (state.endTemplates || []).find((x) => x.key === c.outro.template);
  const thumb = (state.thumbStyles || []).find((x) => x.key === c.thumb_template);
  return `
    <h2>Theme</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:14px">
        <span class="mono" style="color:var(--ink-faint);flex:1;min-width:240px">
          ${esc(t.blurb || 'What kind of channel this is: two colours, a ground, and the icons the patterns are tiled from.')}</span>
      </div>
      <div class="tpl-strip">
        ${list.map((x) => `
          <div class="tpl ${x.key === cur ? 'sel' : ''}"
               onclick="pickTheme('${x.key}')" title="${esc(x.blurb)}">
            ${themeArt(x)}
            <div class="tpl-name">${esc(x.label)}</div>
            <div class="tpl-cast">${esc(x.for)}</div>
          </div>`).join('')}
      </div>
      <div class="mono" style="color:var(--ink-faint);margin:2px 0 14px">
        This channel is currently set in <b>${esc(t.label || cur)}</b> —
        ${esc(slate ? slate.label : c.intro.template)} slate,
        ${esc(thumb ? thumb.label : c.thumb_template)} thumbnail,
        ${c.outro.enabled ? esc(end ? end.label : c.outro.template) + ' end screen'
                          : 'no end screen'}.
        Colours can be edited under House look afterwards; they are the channel's
        from the moment a theme is applied.
      </div>
      <label class="field"><span>Thumbnail style new videos start on</span>
        <select onchange="saveChannel({thumb_template:this.value})">
          ${(state.thumbStyles || []).map((x) =>
            `<option value="${x.key}" ${x.key === c.thumb_template ? 'selected' : ''}
              >${esc(x.label)}</option>`).join('')}
        </select></label>
    </div>`;
}

// The end screen panel. Everything in it is off when the screen is off, because
// a knob that changes nothing is worse than a knob that is not there.
function endScreenPanel(c) {
  const o = c.outro || {};
  const list = state.endTemplates || [];
  const tpl = list.find((t) => t.key === o.template) || list[0] || {};
  const st = c.style;
  if (!o.enabled) {
    return `<h2>End screen</h2>
      <div class="panel">
        <div class="row">
          <div style="flex:1;min-width:240px">
            <strong>No end screen</strong>
            <div class="mono" style="color:var(--ink-faint);margin-top:5px">
              The last 5 to 20 seconds, held for YouTube's own cards and the
              subscribe badge to sit on. Every video in the channel gets it.</div>
          </div>
          <button class="btn sm" onclick="saveOutro({enabled:true})">add one</button>
        </div>
      </div>`;
  }
  return `<h2>End screen</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:16px">
        <span class="mono" style="color:var(--ink-faint);flex:1;min-width:220px">
          ${esc(tpl.blurb || '')}</span>
        <div class="spacer"></div>
        <button class="btn sm" onclick="previewOutro()">preview</button>
        <button class="btn sm ghost" onclick="saveOutro({enabled:false})">turn off</button>
      </div>

      <div class="tpl-strip">
        ${list.map((t) => `
          <div class="tpl ${t.key === o.template ? 'sel' : ''}"
               onclick="saveOutro({template:'${t.key}'})">
            ${endArt(t.key, st.accent)}
            <div class="tpl-name">${esc(t.label)}</div>
            <div class="tpl-cast">${t.max_slots} plate${t.max_slots > 1 ? 's' : ''}${
              t.wants_backdrop ? ' · last shot' : t.themed ? ' · themed' : ''}</div>
          </div>`).join('')}
      </div>

      <div class="grid-3">
        <label class="field"><span>Length — <b>${o.duration.toFixed(0)}s</b></span>
          <input type="range" min="5" max="20" step="1" value="${o.duration}"
            onchange="saveOutro({duration:+this.value})"></label>
        <label class="field"><span>${esc(tpl.slots_label || 'Plates')} — <b>${o.slots}</b></span>
          <input type="range" min="0" max="${tpl.max_slots || 2}" step="1" value="${o.slots}"
            onchange="saveOutro({slots:+this.value})"></label>
        <label class="field"><span>Settling time — <b>${o.settle.toFixed(2)}s</b></span>
          <input type="range" min="0.25" max="1.6" step="0.05" value="${o.settle}"
            onchange="saveOutro({settle:+this.value})"></label>
        <label class="field"><span>Music fades out over — <b>${o.music_fade.toFixed(0)}s</b></span>
          <input type="range" min="0" max="18" step="1" value="${o.music_fade}"
            onchange="saveOutro({music_fade:+this.value})"></label>
      </div>
      <div class="mono" style="color:var(--ink-faint);margin:-8px 0 16px">
        YouTube will not show an end screen shorter than 5 seconds or longer than
        20. Place the real cards over the plates in Studio.</div>

      <div class="grid-2">
        <label class="field"><span>Closing line</span>
          <input type="text" value="${esc(o.cta)}" placeholder="${esc(tpl.cta || '')}"
            onchange="saveOutro({cta:this.value})"></label>
        <label class="field"><span>Handle — set under the channel name</span>
          <input type="text" value="${esc(o.handle)}" placeholder="@yourchannel"
            onchange="saveOutro({handle:this.value})"></label>
      </div>
      <label class="field"><span>The video's last picture behind it — <b>${
        o.backdrop < 0.02 ? 'off' : Math.round(o.backdrop * 100) + '%'}</b></span>
        <input type="range" min="0" max="1" step="0.05" value="${o.backdrop}"
          onchange="saveOutro({backdrop:+this.value})"></label>
      <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
        ${tpl.wants_backdrop
          ? 'Afterglow holds the last picture whatever this says; the slider only decides how far it comes through.'
          : 'Blurred and knocked well back, so the plates still read over it.'}</div>

      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${o.subscribe ? 'checked' : ''} style="width:auto"
          onchange="saveOutro({subscribe:this.checked})">
        <span>Leave a round plate for the subscribe badge</span>
      </label>
      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${o.countdown ? 'checked' : ''} style="width:auto"
          onchange="saveOutro({countdown:this.checked})">
        <span>Hairline showing how long the card is up</span>
      </label>
      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${o.show_video_title ? 'checked' : ''} style="width:auto"
          onchange="saveOutro({show_video_title:this.checked})">
        <span>Name the video that is ending</span>
      </label>

      ${previewStage(c, 'end screen preview', 'cache/outro_preview.webm', c.outro_preview_at)}
    </div>`;
}

// The host image the essay format pins in a corner. Only worth drawing the
// panel when this channel actually renders in that format — on a documentary
// channel it is a control for something that never appears.
function avatarPanel(c) {
  const a = c.avatar || {};
  if ((c.style.format || 'kenburns') !== 'essay') return '';
  return `<h2>Host</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:${a.path ? '16px' : '0'}">
        <div style="flex:1;min-width:240px">
          <strong>${a.path ? esc(a.filename || 'avatar') : 'No host image'}</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:5px">
            A still — a drawing, a mascot, a cut-out — pinned in one corner of
            every video in this channel. Transparent PNGs sit best.</div>
        </div>
        ${a.path ? `
          <img src="/api/channels/${c.id}/file/${a.path}?v=${c.updated_at}"
               style="height:86px;border-radius:8px;background:#0f1116">
          <button class="btn sm ghost danger" onclick="removeAvatar()">remove</button>`
        : `<label class="btn sm" style="cursor:pointer">choose an image
             <input type="file" accept="image/*" hidden onchange="uploadAvatar(this.files[0])">
           </label>`}
      </div>
      ${!a.path ? '' : `
        <label class="row" style="gap:8px;margin-bottom:12px;cursor:pointer">
          <input type="checkbox" ${a.enabled ? 'checked' : ''} style="width:auto"
            onchange="saveAvatar({enabled:this.checked})">
          <span>Show it on this channel's videos</span>
        </label>
        <div class="grid-2">
          <label class="field" style="margin:0"><span>Corner</span>
            <select onchange="saveAvatar({position:this.value})">
              <option value="bottom_right" ${a.position !== 'bottom_left' ? 'selected' : ''}>bottom right</option>
              <option value="bottom_left" ${a.position === 'bottom_left' ? 'selected' : ''}>bottom left</option>
            </select></label>
          <label class="field" style="margin:0"><span>Size — <b>${Math.round((a.scale || 0.24) * 100)}%</b> of frame height</span>
            <input type="range" min="0.1" max="0.4" step="0.01" value="${a.scale || 0.24}"
              onchange="saveAvatar({scale:+this.value})"></label>
        </div>`}
    </div>`;
}

async function uploadAvatar(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    await api(`/api/channels/${state.channel.id}/avatar`, { method: 'POST', body: fd });
    await refreshChannel();
    toast('host image added');
  } catch (e) { toast(e.message, true); }
}

async function removeAvatar() {
  await api(`/api/channels/${state.channel.id}/avatar`, { method: 'DELETE' });
  await refreshChannel();
}

// Publishing lives one level up from a single video: you connect a channel to
// a real YouTube channel once here, then upload from each video's render tab
// (see uploadPanel() in paintRender()).
function youtubePanel(c) {
  if (!c.youtube_available) {
    return `<h2>YouTube</h2>
      <div class="panel">
        <div class="mono" style="color:var(--ink-faint)">
          Not set up. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env to
          publish straight from here — see the README's "Research and
          accuracy" section for the two-minute Cloud Console setup.
          Rendered videos still work fine without it; upload through
          YouTube Studio instead.</div>
      </div>`;
  }
  const yt = c.youtube || {};
  return `<h2>YouTube</h2>
    <div class="panel">
      <div class="row">
        <div style="flex:1;min-width:240px">
          <strong>${yt.connected ? esc(yt.channel_title || 'Connected') : 'Not connected'}</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:5px">
            ${yt.connected
              ? 'New videos in this channel can be uploaded straight from the render tab.'
              : 'Connect the YouTube channel this series publishes to.'}</div>
        </div>
        ${yt.connected
          ? `${yt.channel_thumb ? `<img src="${esc(yt.channel_thumb)}" style="width:40px;height:40px;border-radius:50%">` : ''}
             <button class="btn sm ghost danger" onclick="disconnectYoutube()">disconnect</button>`
          : `<a class="btn sm" href="/api/youtube/oauth/start?channel_id=${c.id}">connect YouTube</a>`}
      </div>
    </div>`;
}

async function disconnectYoutube() {
  if (!confirm('Disconnect this channel from YouTube? Uploading a video will ask you to reconnect.')) return;
  await api(`/api/channels/${state.channel.id}/youtube/disconnect`, { method: 'POST' });
  await refreshChannel();
}

function paintChannel() {
  const c = state.channel;
  if (!c) return;
  if (state.channelTab === 'setup') paintChannelSetup();
  else return paintChannelOverview();
}

// The landing page for a channel — what it's hard to find today, buried
// under the whole setup form. Just the videos, front and centre; setup is
// one click away rather than something you scroll past every time.
function paintChannelOverview() {
  const c = state.channel;
  const st = c.style;
  $('#topbar-right').innerHTML =
    `<span class="swatch" style="background:${esc(st.accent)}"></span>`;

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <div style="flex:1;min-width:0">
        <h1>${esc(c.name)}</h1>
        <p class="sub">${esc(c.tagline || c.concept || 'A series.')}</p>
      </div>
      <button class="btn ghost sm" onclick="go('#/c/${c.id}/setup')">channel setup</button>
      <button class="btn ghost sm" onclick="go('#/')">all channels</button>
    </div>
    ${jobPanel()}
    <section class="panel" id="channel-sponsors" aria-label="Sponsors"></section>
    <section class="channel-blocks card" aria-label="Channel blocks" id="channel-blocks"></section>

    <div class="row" style="margin:20px 0 14px;align-items:baseline">
      <h2 style="margin:0">Videos in this channel</h2>
      <div class="spacer"></div>
      <button class="btn sm primary" onclick="newVideoInChannel('${c.id}')">+ new video</button>
    </div>
    ${(c.videos || []).length === 0
      ? '<div class="empty-note">No music yet. Add a track above.</div>'
      : c.videos.map(projRow).join('')}
  `;
  paintJob();
  paintChannelSponsors(c);
  return paintChannelBlocks(c);
}

function newVideoInChannel(chanId) {
  state.presetChannel = chanId;
  go('#/');
}

function paintChannelSetup() {
  const c = state.channel;
  const st = c.style, intro = c.intro;
  const cast = intro.subjects || [];
  const templates = state.templates || [];
  const tpl = templates.find((t) => t.key === intro.template) || templates[0] || {};
  // Only the cast-led slates wait on portraits; the type-led ones are ready now.
  const castLed = !!tpl.needs_images;
  const ready = !castLed || (intro.images || []).length >= 2;
  $('#topbar-right').innerHTML =
    `<span class="swatch" style="background:${esc(st.accent)}"></span>
     <span class="pill ${ready ? 'on' : 'warn'}">${ready ? 'slate ready' : 'slate incomplete'}</span>`;

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <div style="flex:1;min-width:0">
        <h1>${esc(c.name)} <span class="sub">— setup</span></h1>
        <p class="sub">${esc(c.tagline || c.concept || 'A series.')}</p>
      </div>
      <button class="btn ghost sm" onclick="go('#/c/${c.id}')">← videos</button>
    </div>
    ${jobPanel()}
    ${themePanel(c)}

    <div class="grid-2">
      <div class="panel">
        <h3>Identity</h3>
        <label class="field"><span>Channel name — appears on every slate</span>
          <input type="text" value="${esc(c.name)}" onchange="saveChannel({name:this.value})"></label>
        <label class="field"><span>Tagline — small line above the name</span>
          <input type="text" value="${esc(c.tagline)}" placeholder="optional"
            onchange="saveChannel({tagline:this.value})"></label>
        <label class="field"><span>What this channel covers</span>
          <textarea rows="3" onchange="saveChannel({concept:this.value})"
            placeholder="Steers the scripts and who gets cast in the opening titles."
            >${esc(c.concept)}</textarea></label>
        <label class="field"><span>Default tone for new videos</span>
          <select onchange="saveChannel({tone:this.value})">
            ${['warm documentary', 'cool and analytical', 'plain and understated',
               'tense and propulsive', 'wry and literary'].map((t) =>
              `<option ${t === c.tone ? 'selected' : ''}>${t}</option>`).join('')}
          </select></label>
        <label class="field"><span>Default length — <b>${c.default_minutes}</b> min</span>
          <input type="range" min="7" max="22" value="${c.default_minutes}"
            onchange="saveChannel({default_minutes:+this.value})"></label>
      </div>

      <div class="panel">
        <h3>House look</h3>
        <p class="mono" style="color:var(--ink-faint);margin-top:-4px">
          New videos in this channel start from these.</p>
        <label class="field"><span>Video style</span></label>
        ${formatPicker(st.format || 'kenburns', st.accent, 'pickChannelFormat')}
        ${st.format === 'board' ? boardKnobs(st, 'saveChannelStyle') : ''}
        ${isCut(st.format) ? cutKnobs(st, 'saveChannelStyle') : ''}
        <label class="field"><span>Accent — rules, separators, titles</span>
          <input type="text" value="${esc(st.accent)}" onchange="saveChannelStyle({accent:this.value})"></label>
        <label class="field"><span>Second colour — patterns, shadows, the loud half</span>
          <input type="text" value="${esc(st.accent2 || '')}" placeholder="#7FA6B8"
            onchange="saveChannelStyle({accent2:this.value})"></label>
        <label class="field"><span>Grade</span>
          <select onchange="saveChannelStyle({grade:this.value})">
            ${['warm', 'neutral', 'cool', 'mono'].map((g) =>
              `<option ${g === st.grade ? 'selected' : ''}>${g}</option>`).join('')}
          </select></label>
        <label class="field"><span>Vignette — <b>${st.vignette.toFixed(2)}</b></span>
          <input type="range" min="0" max="0.8" step="0.02" value="${st.vignette}"
            onchange="saveChannelStyle({vignette:+this.value})"></label>
        <label class="field"><span>Crossfade — <b>${st.transition.toFixed(2)}s</b></span>
          <input type="range" min="0" max="1.6" step="0.05" value="${st.transition}"
            onchange="saveChannelStyle({transition:+this.value})"></label>
        <label class="field"><span>Music under voice — <b>${st.music_db.toFixed(0)} dB</b></span>
          <input type="range" min="-40" max="-10" step="1" value="${st.music_db}"
            onchange="saveChannelStyle({music_db:+this.value})"></label>
      </div>
    </div>

    <h2>Opening slate</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:16px">
        <span class="mono" style="color:var(--ink-faint);flex:1;min-width:220px">
          ${esc(tpl.blurb || '')}</span>
        <div class="spacer"></div>
        ${castLed ? `
          <button class="btn sm" onclick="castChannel()">${cast.length ? 're-cast' : 'cast it for me'}</button>
          <button class="btn sm" onclick="fetchPortraits()" ${cast.length ? '' : 'disabled'}>fetch portraits</button>` : ''}
        <button class="btn sm" onclick="previewIntro()"
          ${ready ? '' : 'disabled'}>preview</button>
      </div>

      <div class="tpl-strip">
        ${templates.map((t) => `
          <div class="tpl ${t.key === intro.template ? 'sel' : ''}"
               onclick="saveIntro({template:'${t.key}'})">
            ${tplArt(t.key, st.accent)}
            <div class="tpl-name">${esc(t.label)}</div>
            <div class="tpl-cast">${t.needs_images ? 'needs a cast'
              : t.themed ? 'themed' : 'type only'}</div>
          </div>`).join('')}
      </div>

      <div class="grid-3">
        ${tpl.columns_label ? `
          <label class="field"><span>${esc(tpl.columns_label)} — <b>${intro.columns}</b></span>
            <input type="range" min="3" max="8" value="${intro.columns}"
              onchange="saveIntro({columns:+this.value})"></label>` : ''}
        ${tpl.stagger_label ? `
          <label class="field"><span>${esc(tpl.stagger_label)} — <b>${intro.stagger.toFixed(2)}</b></span>
            <input type="range" min="0.03" max="0.28" step="0.005" value="${intro.stagger}"
              onchange="saveIntro({stagger:+this.value})"></label>` : ''}
        <label class="field"><span>Length — <b>${intro.duration.toFixed(1)}s</b></span>
          <input type="range" min="3" max="9" step="0.5" value="${intro.duration}"
            onchange="saveIntro({duration:+this.value})"></label>
        <label class="field"><span>${esc(tpl.fly_label || 'Fly-in time')} — <b>${intro.fly_duration.toFixed(2)}s</b></span>
          <input type="range" min="0.15" max="1.4" step="0.05" value="${intro.fly_duration}"
            onchange="saveIntro({fly_duration:+this.value})"></label>
      </div>

      <div class="panel" style="background:#0f1116;margin:4px 0 18px">
        <div class="row" style="margin-bottom:${intro.music ? '14px' : '0'}">
          <div style="flex:1;min-width:200px">
            <strong>Slate sting</strong>
            <div class="mono" style="color:var(--ink-faint);margin-top:4px">
              ${intro.music
                ? esc(intro.music_filename || 'sting')
                : `Its own music for the ${intro.duration.toFixed(1)} seconds. The main bed waits until the slate is over.`}</div>
          </div>
          ${intro.music ? `
            <audio id="stingaudio" controls style="max-width:280px"
              src="/api/channels/${c.id}/file/${intro.music}?v=${c.updated_at}"></audio>
            <button class="btn sm ghost danger" onclick="removeSting()">remove</button>`
          : `<label class="btn sm" style="cursor:pointer">choose a sting
               <input type="file" accept="audio/*" hidden onchange="uploadSting(this.files[0])">
             </label>`}
        </div>
        ${intro.music ? `
          <div class="row" style="gap:10px;margin-bottom:12px">
            <div class="mono" style="flex:1;min-width:200px;color:var(--ink-faint)">
              ${stingWindowNote(intro)}</div>
            <button class="btn sm ghost" onclick="auditionSting()">hear the window</button>
          </div>
          <label class="field" style="margin:0 0 12px"><span>Start it — <b>${fmtTime(intro.music_start)}${
              intro.music_start > 0 ? ' into the track' : ' — the very top'}</b></span>
            <input type="range" min="0" max="${stingMaxStart(intro).toFixed(1)}" step="0.1"
              value="${Math.min(intro.music_start, stingMaxStart(intro)).toFixed(1)}"
              oninput="scrubSting(+this.value)"
              onchange="saveIntro({music_start:+this.value})"></label>
          <div class="grid-3">
            <label class="field" style="margin:0"><span>Level vs the narration — <b>${intro.music_db.toFixed(0)} dB</b></span>
              <input type="range" min="-20" max="4" step="1" value="${intro.music_db}"
                onchange="saveIntro({music_db:+this.value})"></label>
            <label class="field" style="margin:0"><span>Rings on past the slate — <b>${intro.music_tail.toFixed(1)}s</b></span>
              <input type="range" min="0" max="3" step="0.1" value="${intro.music_tail}"
                onchange="saveIntro({music_tail:+this.value})"></label>
            <label class="field" style="margin:0"><span>Fade out — <b>${
                intro.music_fade < 0.1 ? 'straight cut' : intro.music_fade.toFixed(1) + 's'}</b></span>
              <input type="range" min="0" max="4" step="0.1" value="${intro.music_fade}"
                onchange="saveIntro({music_fade:+this.value})"></label>
          </div>` : ''}
      </div>

      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${intro.show_video_title ? 'checked' : ''}
          onchange="saveIntro({show_video_title:this.checked})" style="width:auto">
        <span>Show the video's title under the channel name</span>
      </label>

      ${!castLed ? '' : `<h3>Cast — ${intro.template === 'columns' ? 'one face per column'
                                     : intro.template === 'mosaic' ? 'the wall of faces'
                                     : 'the faces on the strip'}</h3>
      <div class="cast">
        ${cast.length === 0
          ? `<div class="empty-note" style="grid-column:1/-1">
               Nobody cast yet. “Cast it for me” asks Claude for faces that fit this channel,
               or type your own below.</div>`
          : cast.map((s, i) => {
              const img = (intro.images || [])[i];
              const f = (intro.focals || [])[i] || [];
              const pos = f.length === 2 ? `${f[0] * 100}% ${f[1] * 100}%` : '50% 28%';
              return `<div class="cast-card">
                ${img ? `<div class="cast-shot" onclick="setCastFocal(${i})"
                              title="click to set the focus point">
                           <img src="/api/channels/${c.id}/file/${img}?v=${c.updated_at}"
                                style="object-position:${pos}">
                           <span class="cast-focus">${f.length === 2 ? '✛ focus' : 'set focus'}</span>
                         </div>`
                      : `<div class="cast-empty" onclick="changeCastImage(${i})"
                              style="cursor:pointer">no portrait — find one</div>`}
                <input type="text" value="${esc(s)}" onchange="editCast(${i}, this.value)">
                <div class="cast-acts">
                  <button class="btn xs ghost" onclick="changeCastImage(${i})"
                    title="choose a different portrait">change</button>
                  <label class="btn xs ghost" style="cursor:pointer"
                    title="use your own image">upload
                    <input type="file" accept="image/*" hidden
                      onchange="uploadCastImage(${i}, this.files[0])"></label>
                  <div class="spacer"></div>
                  <button class="btn xs ghost danger" onclick="removeCast(${i})"
                    title="remove ${esc(s)} from the cast">remove</button>
                </div>
              </div>`;
            }).join('')}
      </div>
      <div class="row" style="margin-top:12px">
        <input type="text" id="newcast" placeholder="add someone — e.g. “Ada Lovelace portrait”"
          style="flex:1" onkeydown="if(event.key==='Enter')addCast(this)">
        <button class="btn sm" onclick="addCast(document.getElementById('newcast'))">add</button>
      </div>`}

      ${previewStage(c, 'intro preview', 'cache/intro_preview.webm', c.preview_at)}
    </div>

    ${endScreenPanel(c)}

    ${avatarPanel(c)}

    ${youtubePanel(c)}

    <div class="row" style="margin-top:30px">
      <div class="spacer"></div>
      <button class="btn sm ghost danger" onclick="delChannel()">delete channel</button>
    </div>
  `;
  paintJob();
}

// A channel response carries no video list and no preview flags — those are
// assembled per request — so they are carried over rather than dropped.
function applyChannel(fresh) {
  state.channel = { ...fresh, videos: state.channel.videos,
    has_preview: state.channel.has_preview,
    has_outro_preview: state.channel.has_outro_preview };
  paintChannel();
}

async function saveChannel(patch, {id = state.channel?.id, quiet = false} = {}) {
  const fresh = await api(`/api/channels/${id}`, {method: 'PATCH', body: JSON.stringify(patch)});
  if (!quiet) { applyChannel(fresh); toast('saved'); }
  return fresh;
}

const saveChannelStyle = (patch) => saveChannel({ style: patch });
const pickChannelFormat = (key) => saveChannelStyle({ format: key });
const saveIntro = (patch) => saveChannel({ intro: patch });
const saveOutro = (patch) => saveChannel({ outro: patch });
const saveAvatar = (patch) => saveChannel({ avatar: patch });

// Renaming only. Emptying the box used to splice `subjects` on its own, which
// left every portrait after it sitting under the wrong name — removal goes
// through the server now, where all four cast arrays move together.
function editCast(i, value) {
  const v = value.trim();
  if (!v) { paintChannel(); return toast('Use “remove” to drop someone.', true); }
  const subjects = [...state.channel.intro.subjects];
  subjects[i] = v;
  saveIntro({ subjects });
}

async function removeCast(i) {
  const who = state.channel.intro.subjects[i] || 'this cast member';
  if (!confirm(`Remove ${who} from the slate?`)) return;
  const r = await api(`/api/channels/${state.channel.id}/cast/${i}`, { method: 'DELETE' });
  applyChannel(r.channel);
  toast('removed');
}

async function uploadCastImage(i, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    applyChannel(await api(`/api/channels/${state.channel.id}/cast/${i}/upload`,
      { method: 'POST', body: fd }));
    toast('portrait replaced');
  } catch (e) { toast(e.message, true); }
}

// Swap one face without re-casting the whole slate. The search runs against the
// cast member's own name by default, but the box is there because "Paderewski
// portrait photograph" and "Ignacy Jan Paderewski 1900" find different pictures.
async function changeCastImage(i) {
  const c = state.channel;
  const subject = c.intro.subjects[i] || '';
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>A portrait for ${esc(subject)}</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="pclose">close</button>
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="pq" value="${esc(subject)}" style="flex:1"
          placeholder="search for something else">
        <button class="btn sm" id="pgo">search</button>
      </div>
      <div id="presults" class="pick-grid portraits">
        <div class="empty-note" style="grid-column:1/-1">Searching for portraits…</div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector('#pclose').onclick = close;
  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });

  const results = wrap.querySelector('#presults');
  const run = async (q) => {
    results.innerHTML = '<div class="empty-note" style="grid-column:1/-1">Searching for portraits…</div>';
    let found = [];
    try {
      const r = await api(`/api/channels/${c.id}/cast/${i}/options`
        + `?q=${encodeURIComponent(q || '')}`);
      found = r.results || [];
    } catch (e) {
      results.innerHTML = `<div class="empty-note" style="grid-column:1/-1">${esc(e.message)}</div>`;
      return;
    }
    if (!found.length) {
      results.innerHTML = '<div class="empty-note" style="grid-column:1/-1">'
        + 'Nobody answered the casting call. Try a different wording.</div>';
      return;
    }
    results.innerHTML = found.map((cand, n) => `
      <div class="pick" data-n="${n}" title="${esc(cand.title || '')}">
        <img src="${esc(cand.thumb || cand.url)}" loading="lazy">
        <div class="pick-meta mono">${esc(cand.provider || '')}${
          cand.width ? ` · ${cand.width}×${cand.height}` : ''}</div>
      </div>`).join('');
    results.querySelectorAll('.pick').forEach((el) => {
      el.onclick = async () => {
        el.classList.add('busy');
        try {
          applyChannel(await api(`/api/channels/${c.id}/cast/${i}/portrait`, {
            method: 'POST',
            body: JSON.stringify({ candidate: found[+el.dataset.n] }),
          }));
          close();
          toast('portrait replaced');
        } catch (e) { el.classList.remove('busy'); toast(e.message, true); }
      };
    });
  };
  wrap.querySelector('#pgo').onclick = () => run(wrap.querySelector('#pq').value);
  wrap.querySelector('#pq').onkeydown = (e) => {
    if (e.key === 'Enter') run(wrap.querySelector('#pq').value);
  };
  run(subject);
}

function addCast(input) {
  const v = input.value.trim();
  if (!v) return;
  input.value = '';
  saveIntro({ subjects: [...state.channel.intro.subjects, v] });
}

async function pickTheme(key) {
  const t = (state.themes || []).find((x) => x.key === key) || {};
  const takeTemplates = confirm(
    `Cast this channel in ${t.label || key}?\n\n`
    + `OK — take its colours and its templates `
    + `(${t.intro} slate, ${t.thumb} thumbnail, ${t.outro} end screen).\n`
    + `Cancel — take the colours only and keep the templates you have.`);
  state.channel = { ...await api(`/api/channels/${state.channel.id}/theme`, {
    method: 'POST', body: JSON.stringify({ key, templates: takeTemplates }),
  }), videos: state.channel.videos, has_preview: state.channel.has_preview,
    has_outro_preview: state.channel.has_outro_preview };
  paintChannel();
  toast(takeTemplates ? `cast in ${t.label || key}` : `${t.label || key} colours applied`);
}

async function castChannel() {
  const r = await api(`/api/channels/${state.channel.id}/cast`,
    { method: 'POST', body: JSON.stringify({ count: state.channel.intro.columns }) });
  watchJob(r.job, 'cast');
  paintChannel();
}

async function fetchPortraits() {
  const r = await api(`/api/channels/${state.channel.id}/portraits`, { method: 'POST' });
  watchJob(r.job, 'portraits');
  paintChannel();
}

async function previewIntro() {
  const sample = (state.channel.videos || [])[0];
  const r = await api(`/api/channels/${state.channel.id}/preview`, {
    method: 'POST',
    body: JSON.stringify({ title: sample ? sample.title : '' }),
  });
  watchJob(r.job, 'intro preview');
  paintChannel();
  scrollToPreview();
}

async function previewOutro() {
  const sample = (state.channel.videos || [])[0];
  const r = await api(`/api/channels/${state.channel.id}/outro-preview`, {
    method: 'POST',
    body: JSON.stringify({ title: sample ? sample.title : '' }),
  });
  watchJob(r.job, 'end screen preview');
  paintChannel();
  scrollToPreview();
}

// Put the placeholder where it can be seen. A preview started from the top of a
// long channel page otherwise renders somewhere below the fold.
function scrollToPreview() {
  requestAnimationFrame(() => {
    const el = document.querySelector('.rendering');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

async function uploadSting(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    await api(`/api/channels/${state.channel.id}/music`, { method: 'POST', body: fd });
    await refreshChannel();
    toast('sting added');
  } catch (e) { toast(e.message, true); }
}

async function removeSting() {
  await api(`/api/channels/${state.channel.id}/music`, { method: 'DELETE' });
  await refreshChannel();
}

// How much of the sting the slate actually uses: the slate's own length plus
// the beat it rings on for over the first slide.
const stingSpan = (intro) => intro.duration + intro.music_tail;

// The last place a window may start. Mirrors the server's clamp, which keeps a
// second of the file in play whatever the slate's length.
const stingMaxStart = (intro) => Math.max(0, (intro.music_duration || 0) - 1);

function stingWindowNote(intro) {
  const span = stingSpan(intro);
  if (!intro.music_duration) return `The slate takes ${span.toFixed(1)}s of it.`;
  const from = Math.min(intro.music_start, stingMaxStart(intro));
  const over = from + span > intro.music_duration + 0.05;
  return `${fmtTime(intro.music_duration)} long — the slate takes ${span.toFixed(1)}s, `
    + `${fmtTime(from)} to ${fmtTime(from + span)}`
    + (over ? '. That runs off the end of the track.' : '.');
}

// Dragging the start slider scrubs the player to that point, so the window can
// be found by ear rather than by arithmetic.
function scrubSting(seconds) {
  const el = document.getElementById('stingaudio');
  if (el) { try { el.currentTime = seconds; } catch (e) { /* not loaded yet */ } }
}

// Play exactly what the slate will use, and stop where it stops.
function auditionSting() {
  const el = document.getElementById('stingaudio');
  const intro = state.channel && state.channel.intro;
  if (!el || !intro) return;
  clearTimeout(window._stingStop);
  const from = Math.min(intro.music_start, stingMaxStart(intro));
  el.currentTime = from;
  el.play().catch(() => {});
  window._stingStop = setTimeout(() => { el.pause(); el.currentTime = from; },
                                 stingSpan(intro) * 1000);
}

async function delChannel() {
  if (!confirm('Delete this channel? Its videos are kept, just unlinked.')) return;
  await api(`/api/channels/${state.channel.id}`, { method: 'DELETE' });
  go('#/');
}


async function saveProjectFormat() {
  const name = prompt('Format name');
  if (!name) return;
  try {
    await api(`/api/channels/${state.project.channel_id}/formats`, {
      method: 'POST', body: JSON.stringify({pid: state.project.id, name}) });
    state.channels = await api('/api/channels');
    toast('Format saved');
  } catch (e) { toast(e.message, true); }
}


async function paintChannelBlocks(c) {
  const host = $('#channel-blocks');
  if (!host) return;
  host.innerHTML = '<h2>Blocks</h2><p>Loading channel blocks…</p>';
  try {
    const items = await api('/api/blocks');
    if (!host.isConnected || state.channel.id !== c.id) return;
    const rows = (values, kind) => values.map((value,i) => {
      const preset = kind === 'block_presets', ref = preset ? value.block : value;
      const block = items.find(b => b.ref === ref);
      return `<div class="channel-block-row" data-kind="${kind}" data-index="${i}">
        <div><strong>${esc(preset ? value.name : block?.name || ref)}</strong>
        <small>${preset ? 'Preset · ' : 'Pinned · '}${esc(ref)}${block ? '' : ' · Block missing'}</small>
        ${preset && !block ? `<pre>${esc(JSON.stringify(value.values,null,2))}</pre>` : ''}</div>
        <div class="row">
        <button type="button" class="btn sm" data-action="open" ${block ? '' : 'disabled'}>${preset ? 'Edit values…' : 'Open'}</button>
        ${preset ? '<button type="button" class="btn sm" data-action="rename">Rename</button>' : ''}
        <button type="button" class="btn sm" data-action="up" aria-label="Move ${esc(preset ? value.name : block?.name || ref)} up" ${i ? '' : 'disabled'}>Move up</button>
        <button type="button" class="btn sm" data-action="down" aria-label="Move ${esc(preset ? value.name : block?.name || ref)} down" ${i < values.length-1 ? '' : 'disabled'}>Move down</button>
        <button type="button" class="btn sm ghost" data-action="remove">${preset ? 'Delete preset' : 'Unpin'}</button></div></div>`;
    }).join('');
    host.innerHTML = `<h2>Blocks</h2><p>Channel pins and presets appear first in this channel’s projects.</p>
      <button type="button" class="btn sm" id="channel-add-block">Add blocks</button>
      ${rows(c.blocks || [],'blocks')}${rows(c.block_presets || [],'block_presets')}
      ${c.blocks?.length || c.block_presets?.length ? '' : '<p>No blocks pinned or presets saved yet.</p>'}
      <p class="mono">Presets keep your values on top of a block; the block itself stays shared. Built-in blocks can’t be copied as your own yet.</p>`;
    host.querySelector('#channel-add-block').onclick = () => openChannelBlockBrowser(c.id);
    host.querySelectorAll('[data-action]').forEach(button => { button.onclick = async () => {
      const row = button.closest('[data-kind]'), kind = row.dataset.kind, index = Number(row.dataset.index);
      const value = c[kind][index], preset = kind === 'block_presets';
      const url = `/api/channels/${c.id}/block-presets/${value.id}`;
      try {
        if (button.dataset.action === 'open') {
          await openChannelBlockBrowser(c.id, preset ? value.block : value);
          if (preset) {
            chooseBlockPreset(blocksBrowser.presets.find(p => p.id === value.id));
            const block = blocksBrowser.items.find(b => b.ref === value.block);
            await blockPresetTarget(block, value.aspect || block.aspects[0], () => readBlockTrial(block,$('#inspector .block-detail')));
          }
          return;
        }
        if (button.dataset.action === 'rename') {
          const name = prompt('Preset name',value.name);
          if (name === null) return;
          await api(url,{method:'PATCH',body:JSON.stringify({name})});
        } else if (button.dataset.action === 'remove') {
          if (preset) {
            const count = await api(url+'/slides');
            if (!confirm(`Delete ${value.name}? ${count.slides} slides use this preset. Slides keep their values.`)) return;
          }
          await api(preset ? url : `/api/channels/${c.id}/blocks/${value}`,{method:'DELETE'});
        } else {
          const order = c[kind].map(v => preset ? v.id : v), other = index + (button.dataset.action === 'up' ? -1 : 1);
          [order[index],order[other]] = [order[other],order[index]];
          await api(`/api/channels/${c.id}/block-order`,{method:'PUT',body:JSON.stringify({[kind]:order})});
        }
        await refreshChannel();
        if (['up','down'].includes(button.dataset.action)) {
          const moved = index + (button.dataset.action === 'up' ? -1 : 1);
          const target = document.querySelector(`#channel-blocks [data-kind="${kind}"][data-index="${moved}"] [data-action="${button.dataset.action}"]`);
          // At the end of the list the same direction is disabled: stay on the
          // row's other move button so keyboard moves can continue.
          const other = target?.parentElement.querySelector(`[data-action="${button.dataset.action === 'up' ? 'down' : 'up'}"]`);
          (target?.disabled ? other : target)?.focus();
        }
      } catch (e) { toast(e.message,true); }
    }; });
  } catch (e) { if (host.isConnected) host.textContent = e.message; }
}


async function paintChannelSponsors(c) {
  const host = $('#channel-sponsors');
  try {
    const items = await api(`/api/channels/${c.id}/sponsors`);
    if (!host.isConnected) return;
    host.innerHTML = `<h2>Sponsors</h2><p class="sub" style="margin-bottom:26px">Choose sponsors in each video's Edit stage. House reads are opt-in. Saved reads keep their copied values.</p>
      <div id="sponsor-list">${items.map((s) => `<div class="row">
        ${s.logo ? `<img width="40" height="40" alt="" src="/api/channels/${encodeURIComponent(c.id)}/file/${esc(s.logo)}">` : ''}
        <span>${esc(s.name)} · ${s.paid ? 'paid' : 'unpaid'}</span>
        ${s.id === 'house' ? '<span class="dim">Built in</span>' : `<button class="btn sm" data-sponsor-edit="${esc(s.id)}">Edit</button><button class="btn sm ghost" data-sponsor-delete="${esc(s.id)}">Delete</button>`}
      </div>`).join('')}</div>
      <button class="btn sm" id="sponsor-new">Add sponsor</button><div id="sponsor-form"></div>`;
    const edit = (s = {}) => {
      const form = $('#sponsor-form');
      const fields = {name: 'Name', url: 'Link', code: 'Promo code', accent: 'Accent colour', ink: 'Ink colour', disclosure: 'Disclosure line'};
      form.innerHTML = `<form id="sponsor-editor">
        ${Object.entries(fields).map(([key, label]) => `<label class="field" for="lib-sp-${key}"><span>${label}</span><input type="text" id="lib-sp-${key}" name="${key}" value="${esc(s[key] ?? ({accent:'#FF5A1F', ink:'#1B1B1F', disclosure:'Paid promotion'}[key] || ''))}"></label>`).join('')}
        ${['short', 'long'].map((v) => `<label class="field" for="lib-sp-${v}"><span>${v} copy</span><textarea id="lib-sp-${v}" name="${v}_copy" maxlength="10000">${esc(s[v + '_copy'] || '')}</textarea></label>`).join('')}
        <label><input type="checkbox" name="paid" ${s.paid !== false ? 'checked' : ''}> Paid promotion</label>
        <label class="field" for="lib-sp-logo"><span>Logo · PNG, JPEG or WebP, up to 2 MiB and 4096 px</span><input type="file" id="lib-sp-logo" accept="image/png,image/jpeg,image/webp"></label>
        <button class="btn sm" type="submit">Save sponsor</button>
        <button class="btn sm ghost" type="button" id="sponsor-cancel">Cancel</button></form>`;
      $('#sponsor-cancel').onclick = () => form.replaceChildren();
      $('#sponsor-editor').onsubmit = async (event) => {
        event.preventDefault();
        const el = event.target, payload = {};
        for (const key of [...Object.keys(fields), 'short_copy', 'long_copy']) payload[key] = el.elements[key].value;
        payload.paid = el.elements.paid.checked;
        try {
          const saved = await api(`/api/channels/${c.id}/sponsors${s.id ? '/' + s.id : ''}`, {method:s.id ? 'PATCH' : 'POST', body:JSON.stringify(payload)});
          const file = $('#lib-sp-logo').files[0];
          // Retain the created id if the upload fails, so retry edits this record.
          s = saved;
          if (file) {
            const data = new FormData(); data.append('file', file);
            await api(`/api/channels/${c.id}/sponsors/${saved.id}/logo`, {method:'POST', body:data});
          }
          await paintChannelSponsors(c);
        } catch (e) { toast(e.message, true); }
      };
    };
    $('#sponsor-new').onclick = () => edit();
    host.querySelectorAll('[data-sponsor-edit]').forEach((button) => button.onclick = () => edit(items.find((s) => s.id === button.dataset.sponsorEdit)));
    host.querySelectorAll('[data-sponsor-delete]').forEach((button) => button.onclick = async () => {
      try {
        await api(`/api/channels/${c.id}/sponsors/${button.dataset.sponsorDelete}`, {method:'DELETE'});
        await paintChannelSponsors(c);
      } catch (e) { toast(e.message, true); }
    });
  } catch (e) { if (host.isConnected) host.textContent = e.message; }
}
