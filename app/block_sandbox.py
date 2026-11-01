"""Small, fail-closed template and resource vocabulary for untrusted user blocks."""
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote

import jinja2
from jinja2 import nodes
from jinja2.sandbox import SandboxedEnvironment

from . import scenes


def environment():
    return SandboxedEnvironment(loader=jinja2.FileSystemLoader(scenes.SCENE_DIR),
                                autoescape=True, undefined=jinja2.StrictUndefined)


def parse(source):
    tree = environment().parse(source)
    allowed = (nodes.Template, nodes.Extends, nodes.Block, nodes.Output, nodes.TemplateData,
               nodes.Name, nodes.Const, nodes.Getattr, nodes.Getitem, nodes.If, nodes.For,
               nodes.Compare, nodes.Operand, nodes.And, nodes.Or, nodes.Not, nodes.Add,
               nodes.Sub, nodes.Mul, nodes.Div, nodes.Neg, nodes.Pos, nodes.CondExpr,
               nodes.List, nodes.Tuple)
    aliases = {n.target.name for n in tree.find_all(nodes.For) if isinstance(n.target, nodes.Name)}
    for node in [tree, *tree.find_all(nodes.Node)]:
        if not isinstance(node, allowed):
            raise ValueError(f'unsafe Jinja: {type(node).__name__}')
        if isinstance(node, nodes.Name) and (node.name.startswith('_') or
                node.name not in {'vars', 'width', 'height', 'duration', 'data', *aliases}):
            raise ValueError(f'unsafe Jinja name: {node.name}')
        if isinstance(node, nodes.Getattr) and (node.attr.startswith('_') or
                not isinstance(node.node, nodes.Name) or node.node.name not in {'vars', 'data'}):
            raise ValueError('unsafe Jinja attribute access')
        if isinstance(node, nodes.Getitem) and (not isinstance(node.arg, nodes.Const) or
                isinstance(node.arg.value, str) and node.arg.value.startswith('_')):
            raise ValueError('Jinja subscripts must be literal keys')
        if isinstance(node, nodes.Block) and node.name not in {'head', 'body'}:
            raise ValueError('only head and body blocks are allowed')
    parents = list(tree.find_all(nodes.Extends))
    if len(parents) != 1 or not isinstance(parents[0].template, nodes.Const) or parents[0].template.value != '_base.html':
        raise ValueError('user blocks must extend _base.html')
    return tree


class Resources(HTMLParser):
    def __init__(self, root):
        super().__init__(convert_charrefs=True)
        self.root = Path(root).resolve()
        self.media_tags = {}
        self.in_style = False

    def url(self, value):
        value = unquote(unescape(value)).strip()
        if re.fullmatch(r'data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+', value):
            return
        if re.fullmatch(r'/fonts/[\w-]+\.(?:ttf|otf|woff2?)', value):
            return
        prefix = '/scene/{token}/assets/'
        name = value[len(prefix):] if value.startswith(prefix) else value
        target = (self.root / name).resolve()
        if (not name or name.startswith('/') or '\\' in name or ':' in name or
                not target.is_relative_to(self.root) or not target.is_file() or
                target.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.ttf', '.otf', '.woff', '.woff2'}):
            raise ValueError(f'unsafe block resource: {value}')
        return target

    def css(self, value):
        # Remove comments before inspecting tokens; refuse CSS escape obfuscation.
        value = re.sub(r'/\*.*?\*/', '', value, flags=re.S)
        if '\\' in value or '/*' in value or re.search(r'@(?!(?:media|font-face)\b)|image-set\s*\(|expression\s*\(|https?:|(?:animation|transition)\s*:', value, re.I):
            raise ValueError('unsafe block CSS/resource')
        for match in re.finditer(r'url\(\s*([\'"]?)(.*?)\1\s*\)', value, re.I | re.S):
            self.url(match[2].strip())
        if len(re.findall(r'url\s*\(', value, re.I)) != len(list(re.finditer(r'url\(\s*([\'"]?)(.*?)\1\s*\)', value, re.I | re.S))):
            raise ValueError('malformed resource URL')

    def handle_starttag(self, tag, attrs):
        if tag not in {'style', 'div', 'section', 'article', 'header', 'footer', 'main',
                       'h1', 'h2', 'h3', 'h4', 'p', 'span', 'strong', 'em', 'b', 'i',
                       'ul', 'ol', 'li', 'br', 'img', 'table', 'tr', 'td', 'th', 'thead', 'tbody'}:
            raise ValueError(f'unsafe block tag: {tag}')
        if tag == 'style':
            self.in_style = True
        normalized = dict(attrs)
        for key, value in attrs:
            # Builder attributes are data the compiler interprets; none load resources.
            builder = re.fullmatch(r'data-(?:motion|media)-[a-z-]+|data-(?:capture|steps|path|clip|'
                                   r'ground|screen|world|budget)', key)
            if not builder and key not in {'class', 'id', 'style', 'title', 'alt', 'src', 'data-layer',
                           'data-motion', 'data-start', 'data-duration', 'data-var-text',
                           'data-fit', 'data-media'}:
                raise ValueError(f'unsafe block attribute: {key}')
            if key in {'src', 'data-media'}:
                target = self.url(value or '')
                if key == 'data-media':
                    if target is None:
                        raise ValueError('data-media requires a file in the block assets')
                    normalized[key] = str(target)
            if key == 'data-motion' and value not in scenes.env.globals['motion_presets']:
                raise ValueError(f'unknown motion preset: {value}')
            if key == 'style':
                self.css(value or '')
        if 'data-media' in normalized:
            self.media_tags[self.get_starttag_text()] = '<' + tag + ' ' + ' '.join(
                k + '="' + escape(v or '', quote=True) + '"' for k, v in normalized.items()) + '>'

    def handle_startendtag(self, tag, attrs):
        if tag == 'style':
            raise ValueError('self-closing style is unsafe: browser/parser disagreement')
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, value):
        # Text content is inert; only stylesheet text can load resources.
        if self.in_style:
            self.css(value)


def render(source, ctx):
    tree = parse(source)
    sandbox = environment()
    # Validate the rendered contribution before adding the trusted runtime/base.
    tree.body = [n for n in tree.body if not isinstance(n, nodes.Extends)]
    fragment = sandbox.from_string(tree).render(**ctx)
    resources = Resources(ctx['block_assets_root'])
    resources.feed(fragment)
    # Runtime also writes vars to CSS custom properties; validate those values.
    for value in ctx.get('vars', {}).values():
        if isinstance(value, str) and re.search(r'url\s*\(|image-set\s*\(|expression\s*\(|@import|\\', value, re.I):
            raise ValueError('unsafe block variable: CSS resource syntax')
    sandbox.globals['motion_presets'] = scenes.env.globals['motion_presets']
    html = sandbox.from_string(source).render(**ctx)
    # Native media is consumed by ffmpeg, which needs a validated local path.
    for original, normalized in resources.media_tags.items():
        html = html.replace(original, normalized)
    return html.replace('</body>', '<script src="/static/scene/user_fit.js"></script></body>')
