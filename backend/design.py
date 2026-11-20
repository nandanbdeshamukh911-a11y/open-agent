"""Compile a compact editorial brief into one portable, editable page."""
from html import escape
from pathlib import Path
from string import Template

ASSETS = Path(__file__).with_name('design_assets')
PALETTES = {
    'cobalt': ('#233eb5', '#f2f1e9', '#ecad79'),
    'forest': ('#205141', '#f4f1e6', '#d4d989'),
    'plum': ('#562b49', '#faf0e7', '#ffaa82'),
}


def field(data, key, limit):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Supply {key} as text between 1 and {limit} characters.')
    return escape(value.strip())


def render(brief):
    if not isinstance(brief, dict):
        raise ValueError('Supply a design brief object.')
    palette = brief.get('palette', 'cobalt')
    if not isinstance(palette, str) or palette not in PALETTES:
        raise ValueError('Choose cobalt, forest or plum for palette.')
    layout = brief.get('layout', 'programme')
    if layout not in ('programme', 'catalogue'):
        raise ValueError('Choose programme or catalogue for layout.')
    items = brief.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError('Supply 1 to 12 items with label, title and detail.')
    rows = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Each item needs label, title and detail.')
        title = field(item, 'title', 160)
        label = field(item, 'label', 80)
        rows.append(
            f'<details><summary role="button" aria-label="{label} {title}"><span class="label">' + label
            + '</span><strong>' + title
            + '</strong><span class="toggle" aria-hidden="true"></span></summary><p>'
            + field(item, 'detail', 800) + '</p></details>'
        )
    values = {key: field(brief, key, limit) for key, limit in (
        ('brand', 80), ('headline', 140), ('intro', 450), ('section', 80),
    )}
    ink, paper, accent = PALETTES[palette]
    vendor = ASSETS / 'vendor'
    search = ('<label class="search">Search entries<input id="query" type="search" autocomplete="off"></label>'
              '<p class="count" role="status" id="matches"></p>') if layout == 'catalogue' else ''
    return Template((ASSETS / 'page.html').read_text(encoding='utf-8')).substitute(
        **values, ink=ink, paper=paper, accent=accent, layout=layout, search=search, rows='\n'.join(rows),
        library=(vendor / 'anime.umd.min.js').read_text(encoding='utf-8'),
        license=(vendor / 'anime-LICENSE.md').read_text(encoding='utf-8'),
    )
