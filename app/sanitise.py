"""Fail-closed HTML fragment rebuilder. Model CSS has no allowed properties."""
import html
from html.parser import HTMLParser
import re
from urllib.parse import unquote

TAGS = frozenset('section h1 h2 p ul li img span figure figcaption strong em'.split())
CLASSES = frozenset(('cb-slide cb-row cb-stack cb-card cb-title cb-number '
                     'cb-label cb-accent cb-muted cb-center cb-photo').split())
ATTRS = frozenset('class src alt data-text data-start data-duration data-layer data-motion'.split())
MOTIONS = frozenset('none fade rise fly-left fly-right scale-in wipe words blur-in pop'.split())
_START = re.compile(r'''<[a-z][a-z0-9]*(?:\s+[a-z][a-z0-9-]*\s*=\s*(?:"[^"<]*"|'[^'<]*'))*\s*/?>''', re.I)
_VALUES = re.compile(r'''[a-z][a-z0-9-]*\s*=\s*("[^"<]*"|'[^'<]*')''', re.I)
_IMAGE = re.compile(r'/scene/\{token\}/project/scenes/board-[0-9a-f]{40}\.png')
_DANGEROUS = re.compile(r'url\s*\(|expression\b|@import|javascript\s*:|data\s*:', re.I)


class UnsafeHTML(ValueError):
    pass


class _San(HTMLParser):
    def __init__(self, sources):
        super().__init__(convert_charrefs=False)
        self.sources, self.out, self.stack = set(sources), [], []
        self.layers, self.layer_stack = set(), []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if tag not in TAGS or not _START.fullmatch(raw):
            raise UnsafeHTML('Unsupported or malformed tag')
        seen, kept = set(), []
        for (key, value), original in zip(attrs, _VALUES.findall(raw)):
            if key not in ATTRS or key in seen or value is None:
                raise UnsafeHTML('Unsupported or duplicate attribute')
            seen.add(key)
            decoded = value
            for _ in range(8):
                expanded = html.unescape(unquote(decoded))
                if expanded == decoded:
                    break
                decoded = expanded
            else:
                raise UnsafeHTML('Excessive attribute encoding')
            if (_DANGEROUS.search(decoded) or '\\' in decoded or
                    any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
                raise UnsafeHTML('Unsafe attribute value')
            if key in ('src', 'class', 'data-start', 'data-duration', 'data-layer', 'data-motion'):
                if '&' in original or '%' in original:
                    raise UnsafeHTML('Encoded structural attribute')
            if key == 'class' and (not value.split() or not set(value.split()) <= CLASSES):
                raise UnsafeHTML('Unsupported class')
            if key == 'src' and (tag != 'img' or not _IMAGE.fullmatch(value) or value not in self.sources):
                raise UnsafeHTML('Image must be an already-resolved project image')
            if key in ('data-start', 'data-duration') and not re.fullmatch(r'(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,6})?', value):
                raise UnsafeHTML(f'{key} must be finite nonnegative seconds')
            if key == 'data-duration' and float(value) <= 0:
                raise UnsafeHTML('data-duration must be positive')
            if key == 'data-layer' and not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value):
                raise UnsafeHTML('Invalid layer id')
            if key == 'data-motion' and value not in MOTIONS:
                raise UnsafeHTML('Unsupported motion')
            kept.append(f' {key}="{html.escape(value, quote=True)}"')
        layer = dict(attrs).get('data-layer')
        if layer:
            if layer in self.layers or any(self.layer_stack) or len(self.layers) >= 48:
                raise UnsafeHTML('Duplicate, nested or too many layers')
            self.layers.add(layer)
        elif seen & {'data-duration', 'data-motion'}:
            raise UnsafeHTML('Motion and duration require data-layer')
        if tag == 'img' and 'src' not in seen:
            raise UnsafeHTML('Image needs a resolved source')
        self.out.append('<' + tag + ''.join(kept) + '>')
        if tag != 'img':
            self.stack.append(tag)
            self.layer_stack.append(bool(layer))

    def handle_startendtag(self, tag, attrs):
        if tag != 'img':
            raise UnsafeHTML('Only img can be self-closing')
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise UnsafeHTML('Unbalanced closing tag')
        self.layer_stack.pop()
        self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if '<' in data:
            raise UnsafeHTML('Incomplete or malformed markup')
        self.out.append(html.escape(data))

    def handle_entityref(self, name):
        self.out.append(html.escape(html.unescape('&' + name + ';')))

    def handle_charref(self, name):
        self.out.append(html.escape(html.unescape('&#' + name + ';')))

    def handle_comment(self, data):
        raise UnsafeHTML('Comments are unsupported')

    handle_decl = handle_pi = unknown_decl = handle_comment


def clean(fragment, image_sources=()):
    """Return rebuilt markup, or reject the entire fragment without partial output."""
    if not isinstance(fragment, str) or not fragment.strip() or len(fragment) > 32000:
        raise UnsafeHTML('Expected a nonempty HTML fragment under 32000 characters')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', fragment):
        raise UnsafeHTML('Control characters are unsupported')
    # HTMLParser tolerates malformed end tags; reject before it can repair them.
    if any(not re.fullmatch(r'</[a-z][a-z0-9]*\s*>', m[0], re.I)
           for m in re.finditer(r'</[^>]*(?:>|$)', fragment)):
        raise UnsafeHTML('Malformed closing tag')
    parser = _San(image_sources)
    parser.feed(fragment)
    if '<' in parser.rawdata:
        raise UnsafeHTML('Incomplete markup')
    parser.close()
    if parser.stack:
        raise UnsafeHTML('Unclosed tag')
    return ''.join(parser.out)
