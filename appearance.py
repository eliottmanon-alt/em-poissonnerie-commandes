"""Render saved photo URLs directly in HTML, preserving existing editor IDs."""
import html
import json
import re
from html.parser import HTMLParser

MEDIA = re.compile(r'^/api/appearance/media/[a-f0-9]{64}$')


def display_url(url):
    return url + '/display.webp' if MEDIA.fullmatch(url or '') else url


class ImageTags(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.tags = []
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img' or 'banner-bg' in attrs.get('class', '').split():
            line, column = self.getpos()
            self.tags.append((tag, attrs, self.offsets[line - 1] + column, self.get_starttag_text()))

    handle_startendtag = handle_starttag


def set_attr(raw, key, value):
    attribute = key + '="' + html.escape(str(value), quote=True) + '"'
    pattern = r'(?i)\s+' + re.escape(key) + r'\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s>]+)'
    if re.search(pattern, raw):
        return re.sub(pattern, lambda _: ' ' + attribute, raw, count=1)
    end = -2 if raw.endswith('/>') else -1
    return raw[:end] + ' ' + attribute + raw[end:]


def render_images(source, page, state):
    tags = ImageTags(source).tags
    images = [t for t in tags if t[0] == 'img']
    replacements = []
    banner = None
    for index, (_, attrs, start, raw) in enumerate(images):
        classes = [c for c in attrs.get('class', '').split() if not c.startswith('em-admin')][:2]
        peers_before = sum(1 for _, other, _, _ in images[:index] if set(classes).issubset(other.get('class', '').split()))
        key = attrs.get('data-em-admin-id') or ('id:' + attrs['id'] if attrs.get('id') else f"{page}:img:{'.'.join(classes) or 'x'}:{peers_before}")
        model = state.get('images', {}).get(key, {})
        url = model.get('url') or model.get('src')
        rewritten = set_attr(raw, 'data-em-admin-id', key)
        if url:
            rewritten = set_attr(rewritten, 'src', display_url(url))
            rewritten = set_attr(rewritten, 'data-em-original-src', attrs.get('src', ''))
            rewritten = set_attr(rewritten, 'data-em-server-image', 'true')
            if 'banner-full' in classes:
                banner = display_url(url)
        style = attrs.get('style', '')
        pos, filters = model.get('pos'), model.get('filter')
        if isinstance(pos, str) and re.fullmatch(r'[-\d.%\s]+', pos):
            style += ';object-position:' + pos
        if isinstance(filters, str) and re.fullmatch(r'(?:(?:brightness|contrast|saturate)\([0-9.]+%\)\s*)+', filters):
            style += ';filter:' + filters
        if style != attrs.get('style', ''):
            rewritten = set_attr(rewritten, 'style', style)
        first_hero = page == 'accueil' and index == 1
        if first_hero or 'banner-full' in classes:
            rewritten = set_attr(rewritten, 'fetchpriority', 'high')
            rewritten = set_attr(rewritten, 'loading', 'eager')
        elif 'loading' not in attrs and ((page == 'accueil' and index >= 7) or (page == 'commandes' and index >= 4)):
            rewritten = set_attr(rewritten, 'loading', 'lazy')
        replacements.append((start, len(raw), rewritten))
    if banner:
        for tag, attrs, start, raw in tags:
            if tag != 'img':
                # URLs here are server media IDs or validated original asset paths.
                safe_url = banner.replace('\\', '%5C').replace('"', '%22').replace('\n', '%0A').replace('\r', '%0D')
                style = attrs.get('style', '') + ';background-image:url(' + json.dumps(safe_url) + ')'
                replacements.append((start, len(raw), set_attr(raw, 'style', style)))
    for start, size, value in sorted(replacements, reverse=True):
        source = source[:start] + value + source[start + size:]
    return source
