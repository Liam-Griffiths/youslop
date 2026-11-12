"""Local subject anchors for archive searches; no model or provider calls."""
from collections import Counter
import re
import unicodedata


def normal(text):
    text = unicodedata.normalize('NFKD', text or '')
    return ' '.join(re.findall(r'[^\W_]+', ''.join(
        c for c in text.lower() if not unicodedata.combining(c))))


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, v in value.items():
            if key not in {'url', 'source', 'confidence'}:
                yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


_STOP = set('the a an of in on at and or to for with from by how why was were is '
            'are this that its their about history story de du des la le les et un une der die das und'.split())
_ABSTRACT = set('theory theories energy hypothesis hypotheses analysis estimate '
                'estimates scientific release megatons tnt explanation concept '
                'impact significance effect effects'.split())
_GENERIC = _STOP | _ABSTRACT | set(
    's history story event events building buildings crew post city river built '
    'explosion expedition imperial trans construction life world years year '
    'people time first last new old mail dam'.split())
# Common words carry too little subject information, even when capitalised or
# repeated. Keep this local and compact rather than requiring a language model.
_COMMON = set('''
    able above across action actually after again against ago air all almost
    along already also although always am among amount another any anyone
    anything appear area around as ask away back bad be became because become
    been before began begin behind being below best better between big book
    both box boy bring brought bus business but buy call called came can cannot
    car card cards care carry case cause certain change children close come
    common company complete could country course cut day days decide decided
    did different do does doing done down during each early earth east easy
    either else end enough even ever every everyone everything example face
    fact far feel felt few find fine fire five follow food form found four
    free friend full further gave general get give given go going gone good
    got government great group grow had hand hard has have having he head hear
    heard help her here high him himself his home hope hour house however
    human hundred i if important include information inside instead interest
    into it itself jams job just keep kind knew know known large later learn
    least leave left less let letter letters level light like likely line
    little live local long look lot low made main make man many may me mean
    men might million mind miss money month months more morning most mother
    move much must my name named national natural near need never next night
    no nobody non none nor north nothing now number often off office once
    one only open order other others our out outside over own part particular
    past perhaps person piece place plan point possible power present problem
    public put question quite rather reach read ready real really reason
    receive record red remain remember report result right room round run
    said same saw say school second see seem seen send sent service set
    several she short should show side since six small so social some someone
    something sometimes son soon sort sound south space special start state
    stay still stop street strong such sure system take taken talk tell ten
    than thank them themselves then there these they thing things think third
    those though thought thousand three through throughout thus today together
    too took top toward town tree tried true try tube tubes turn two under
    understand until up upon us use used using usually value various very want
    war water way we week well went west what when where whether which while
    white who whole whom whose will wish within without woman women word words
    work worked working would write written wrong yes yet you young your
'''.split())
# A deliberately small gazetteer; dossier/outline context adds local names below.
_PLACES = set(normal(
    'France Germany Britain England Scotland Wales Ireland Italy Spain Portugal '
    'Greece Netherlands Belgium Switzerland Austria Poland Russia China Japan '
    'India Pakistan Bangladesh Korea Vietnam Indonesia Australia Canada Mexico '
    'Brazil Argentina Chile Peru Egypt Kenya Nigeria Ethiopia South Africa '
    'United States America United Kingdom USA UK Europe Asia Africa Antarctica '
    'Antarctic Arctic Siberia Siberian Pacific Atlantic Mediterranean '
    'Paris Berlin London Rome Madrid Lisbon Vienna Prague Warsaw Moscow Beijing '
    'Shanghai Tokyo Delhi Mumbai Cairo Istanbul Athens Amsterdam Brussels '
    'Stockholm Oslo Copenhagen Helsinki Dublin Edinburgh Toronto Vancouver '
    'Montreal Ottawa Washington New York Los Angeles San Francisco Chicago '
    'Boston Seattle Sydney Melbourne Seoul Singapore Hong Kong Bangkok '
    'Nairobi Lagos Johannesburg Buenos Aires Rio de Janeiro Turin Torino '
    'Colorado California Texas Alaska Greenland').split())


def _place_words(project):
    """Recognise explicit location fields and capitalised names in place contexts.

    Capitalisation alone is insufficient: people and named objects are anchors.
    These local heuristics supplement the gazetteer without a model/geocoder.
    """
    places = set(_PLACES)

    def fields(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'location', 'locations', 'place', 'places', 'country',
                           'countries', 'city', 'cities', 'region', 'regions'}:
                    for text in _strings(child):
                        places.update(normal(text).split())
                else:
                    fields(child)
        elif isinstance(value, list):
            for child in value:
                fields(child)

    context = [project.outline, project.research]
    fields(context)
    texts = list(_strings(context))
    # str.isupper handles Unicode initials too, unlike an ASCII [A-Z] range.
    initials = ''.join(sorted({c for text in texts for c in text if c.isupper()}))
    if not initials:
        return places
    name = rf"[{re.escape(initials)}][^\W\d_]*(?:[-’'][^\W\d_]+)*"
    place_name = rf'{name}(?:\s+(?:(?:and|de|of)\s+)?{name}){{0,3}}'
    patterns = [
        rf'\b(?i:in|at|near|from|across|around|throughout|city of|region of|'
        rf'province of|country of|located in)\s+(?i:the\s+)?({place_name})',
        rf'\b({place_name})\s+(?i:river|city|province|region|island|valley|'
        rf'mountains|sea|ocean)\b',
    ]
    for text in texts:
        for pattern in patterns:
            for place in re.findall(pattern, text):
                places.update(normal(place).split())
    return places


def subject_terms(project):
    """Use subject phrases, distinctive title/subject words and dossier aliases.

    Single words need evidence from naming, distinctiveness or multiple sources.
    For older dossiers, repeated phrases sharing the primary anchor add variants.
    Place names on their own never become anchors just by being capitalised.
    """
    texts = list(_strings([project.title, project.outline, project.research]))
    corpus = [normal(t) for t in texts]
    places = _place_words(project)
    excluded = _GENERIC | places
    sources = [set(normal(project.title).split()),
               set(normal(project.outline.get('subject', '')).split()),
               set(normal(' '.join(_strings(project.research))).split())]
    proper = set()
    for text in [project.title, project.outline.get('subject', ''),
                 *list(_strings(project.research))]:
        for sentence in re.split(r'[.!?\n]', text):
            words = re.findall(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*", sentence)
            for word in words[1:]:
                if word[0].isupper():
                    proper.update(normal(word).split())

    def single_anchor(word):
        return (len(word) > 2 and word not in excluded | _COMMON
                and not word.isdigit()
                and (word in proper or sum(word in s for s in sources) >= 2
                     or len(word) >= 8))

    def distinctive(term):
        return any(len(w) > 2 and w not in excluded | _COMMON and not w.isdigit()
                   for w in normal(term).split())

    def valid_term(term):
        words = normal(term).split()
        if len(words) == 1:
            return single_anchor(words[0])
        return (1 < len(words) <= 5 and distinctive(term)
                and not any(w in places | _STOP for w in words))

    seed = normal(project.outline.get('subject') or project.title or project.idea)
    words = seed.split()
    phrases = [' '.join(words[i:i+n]) for n in (2, 3)
               for i in range(len(words)-n+1)
               if not any(w in _STOP | places or w.isdigit() for w in words[i:i+n])
               and distinctive(' '.join(words[i:i+n]))]
    primary = max(phrases, key=lambda p: (sum(p in t for t in corpus), -len(p.split())),
                  default=seed if len(words) == 1 else '')
    terms = list(_strings(project.outline.get('subject_terms', [])))
    terms += list(_strings(project.research.get('subject_terms', [])))
    if primary:
        terms.append(primary)
    subject_words = set(normal(project.outline.get("subject", "")).split())
    for text in texts:
        # Extract names, not arbitrary quotations from narration or sources.
        for sentence in re.split(r'[.!?\n]', text):
            if re.search(r'\b(called|known as|name|native terms?|French|German|cards? were)\b',
                         sentence, re.I):
                aliases = re.findall(r'["“]([^"”]{3,60})["”]', sentence)
                aliases += re.findall(r"(?<!\w)'([^']{3,60})'(?!\w)", sentence)
                terms += [a for a in aliases if len(normal(a).split()) >= 2
                          or normal(a) in subject_words
                          or re.search(r"\bnative terms?\b", sentence, re.I)]
        terms += re.findall(r'\b(?:called|known as)\s+([A-ZÀ-ÖØ-Þ][\w-]+)', text)
    # The outline often gives translations in parentheses: (the Rohrpost and the pneus).
    for group in re.findall(r'\(([^)]+)\)', project.outline.get('subject', '')):
        terms += [' '.join(w for w in normal(t).split() if w not in _STOP)
                  for t in re.split(r'\band\b|[,;/]', group)]
    terms += [w for w in normal(project.title + ' ' + seed).split() if single_anchor(w)]
    if primary:
        # Keep the distinguishing head, not generic tails such as "post office".
        head = primary.split()[0]
        prefix = head[:6] if len(head) >= 6 else head
        counts = Counter(' '.join(ws[i:i+2]) for t in corpus for ws in [t.split()]
                         for i in range(len(ws)-1))
        terms += [p for p, count in counts.items()
                  if (count >= 2 or any(w.startswith(prefix) and w != head for w in p.split()))
                  and any(w.startswith(prefix) for w in p.split())
                  and all(len(w) >= 3 and w not in _STOP for w in p.split())]
    return list(dict.fromkeys(normal(t) for t in terms
                             if t.strip() and valid_term(t)))[:12]


def concrete_queries(queries):
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    def abstract(q):
        words = set(normal(q).split()) - _STOP
        return bool(words) and len(words & _ABSTRACT) >= len(words) / 2
    concrete = [q for q in queries if not abstract(q)]
    return concrete or queries  # Do not drop the only available search.


def paragraph_queries(queries, terms):
    queries = concrete_queries(queries)
    if not terms or all(normal(q) in terms for q in queries):
        return queries
    anchored = [q if any(t in normal(q) for t in terms) else f'{q} {terms[0]}'
                for q in queries[:2]]
    fallbacks = [q for q in queries if len(normal(q).split()) >= 3]
    return list(dict.fromkeys(anchored + fallbacks))[:3]


def gate(candidate, terms, paragraph=''):
    """Mutate caller-owned metadata, never the provider cache. Require an anchor."""
    if terms is None or candidate.get('provider') in {'maps', 'diagram', 'custom', 'local', 'footage'}:
        return
    text = normal(' '.join([candidate.get('title', ''), candidate.get('description', ''),
                            *candidate.get('categories', []), *candidate.get('labels', [])]))
    prefixes = {w[:6] for w in text.split()}
    matched = any(f' {term} ' in f' {text} '
                  or (' ' not in term and len(term) >= 7 and term[:6] in prefixes)
                  for term in terms)
    nouns = set(normal(paragraph).split()) - _STOP
    candidate['weak_match'] = not matched
    candidate['relevance_score'] = round(1 + len(nouns & set(text.split())) / max(1, len(nouns)), 4) if matched else 0


def rank(candidate, prefer_public_domain=False):
    licence = normal(candidate.get('license', ''))
    pd = bool(re.search(r'\b(public domain|cc0|cc 0|pdm)\b', licence))
    return (not candidate.get('weak_match', False), candidate.get('relevance_score', 0),
            pd if prefer_public_domain else False, candidate.get('score', 0))


def identity(candidate):
    return (candidate.get('source_page') or candidate.get('url') or candidate.get('id', '')).split('?')[0]
