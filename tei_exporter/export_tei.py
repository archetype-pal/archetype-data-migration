#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone exporter: pg_dump (.sql) -> TEI XML
"""
import argparse
import os
import re
import textwrap
from copy import deepcopy
from html import unescape as html_unescape

from lxml import etree
from lxml import html as lxml_html


def decode_copy_field(field):
    if field == r'\N':
        return None

    def repl(match):
        seq = match.group(1)
        if seq == 'b':
            return '\b'
        if seq == 'f':
            return '\f'
        if seq == 'n':
            return '\n'
        if seq == 'r':
            return '\r'
        if seq == 't':
            return '\t'
        if seq == 'v':
            return '\v'
        if seq.startswith('x'):
            try:
                return chr(int(seq[1:], 16))
            except Exception:
                return match.group(0)
        if seq.isdigit():
            try:
                return chr(int(seq, 8))
            except Exception:
                return match.group(0)
        return seq

    return re.sub(r'\\([0-7]{1,3}|x[0-9A-Fa-f]+|.)', repl, field)


def iter_copy_rows(sql_path, table_name, debug=False):
    # Accept dumps with or without explicit "public." schema prefix.
    table_name = table_name.replace('public.', '')
    copy_re = re.compile(
        r'^COPY\s+(?:public\.)?%s\s+\((.*?)\)\s+FROM\s+stdin;\s*$' % re.escape(table_name)
    )
    in_copy = False
    found_copy = False
    with open(sql_path, 'rb') as fh:
        for raw_line in fh:
            line = raw_line.decode('utf-8', 'replace')
            if not in_copy:
                if copy_re.match(line):
                    in_copy = True
                    found_copy = True
                continue
            if line.strip() == r'\.':
                break
            line = line.rstrip('\n')
            if '\t' in line:
                fields = line.split('\t')
            else:
                # If no tabs are present, we can't reliably parse COPY data.
                if debug:
                    print('WARNING: no tab delimiters found in COPY data line')
                continue
            fields = [decode_copy_field(f) for f in fields]
            yield fields
    if debug and not found_copy:
        print('WARNING: no COPY section found for %s' % table_name)


def load_text_content_types(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_text_textcontenttype', debug=debug):
        if len(row) < 5:
            continue
        ret[row[0]] = {'name': row[1], 'slug': row[4]}
    return ret


def load_text_contents(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_text_textcontent', debug=debug):
        if len(row) < 7:
            continue
        ret[row[0]] = {
            'type_id': row[1],
            'item_part_id': row[2],
            'created': row[3],
            'modified': row[4],
            'text_id': row[5],
            'attribution_id': row[6],
        }
    return ret


def load_item_parts(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_itempart', debug=debug):
        if len(row) < 4:
            continue
        ret[row[0]] = {
            'current_item_id': row[1],
            'locus': row[2],
            'display_label': row[3],
            'custom_label': row[12] if len(row) > 12 else None,
        }
    return ret


def load_current_items(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_currentitem', debug=debug):
        if len(row) < 4:
            continue
        ret[row[0]] = {
            'repository_id': row[2],
            'shelfmark': row[3],
        }
    return ret


def load_repositories(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_repository', debug=debug):
        if len(row) < 5:
            continue
        ret[row[0]] = {
            'name': row[2],
            'place_id': row[4],
        }
    return ret


def load_places(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_place', debug=debug):
        if len(row) < 3:
            continue
        ret[row[0]] = {'name': row[2]}
    return ret


def load_text_content_xml_statuses(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_text_textcontentxmlstatus', debug=debug):
        if len(row) < 6:
            continue
        ret[row[0]] = {
            'name': row[1],
            'slug': row[4],
            'sort_order': row[5],
        }
    return ret


def load_texts(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_text', debug=debug):
        if len(row) < 8:
            continue
        ret[row[0]] = {
            'name': row[1],
            'legacy_id': row[4],
            'date': row[5],
            'url': row[6],
            'date_sort': row[7],
        }
    return ret


def load_content_attributions(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_contentattribution', debug=debug):
        if len(row) < 6:
            continue
        ret[row[0]] = {
            'title': row[1],
            'message': row[2],
            'short_message': row[5],
        }
    return ret


def load_languages(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_language', debug=debug):
        if len(row) < 3:
            continue
        ret[row[0]] = {'name': row[2]}
    return ret


def load_text_content_languages(sql_path, debug=False):
    ret = {}
    for row in iter_copy_rows(sql_path, 'digipal_text_textcontent_languages', debug=debug):
        if len(row) < 3:
            continue
        text_content_id = row[1]
        language_id = row[2]
        if not text_content_id or not language_id:
            continue
        ret.setdefault(text_content_id, []).append(language_id)
    return ret


def uniq(values):
    seen = set()
    out = []
    for value in values:
        value = (value or '').strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def map_to_tei_doc_status(status_slug):
    slug = (status_slug or '').strip().lower()
    mapping = {
        'draft': 'draft',
        'reviewed': 'approved',
        'live': 'published',
        'published': 'published',
        'public': 'published',
        'online': 'published',
    }
    return mapping.get(slug, 'draft')


def coalesce_tei_doc_status(status_values):
    # Conservative: if any section is less mature, keep that document status.
    rank = {'draft': 0, 'approved': 1, 'published': 2}
    vals = [v for v in status_values if v in rank]
    if not vals:
        return 'draft'
    return sorted(vals, key=lambda v: rank[v])[0]


def build_meta_from_dump(moa_id, text_content_id, created, modified, status_id, text_content_types,
                         text_contents, item_parts, current_items, repositories,
                         places, text_content_xml_statuses, texts,
                         content_attributions, languages, text_content_languages):
    content_type_slug = None
    content_type_name = None
    item_part_id = None

    tc = text_contents.get(text_content_id)
    if tc:
        item_part_id = tc.get('item_part_id')
        type_id = tc.get('type_id')
        tct = text_content_types.get(type_id)
        if tct:
            content_type_slug = tct.get('slug')
            content_type_name = tct.get('name')

    label = None
    current_item_id = None
    if item_part_id:
        ip = item_parts.get(item_part_id)
        if ip:
            current_item_id = ip.get('current_item_id')
            label = ip.get('custom_label') or ip.get('display_label') or ip.get('locus')

    shelfmark = None
    repository_name = None
    place_name = None
    if current_item_id:
        ci = current_items.get(current_item_id)
        if ci:
            shelfmark = ci.get('shelfmark')
            repo_id = ci.get('repository_id')
            repo = repositories.get(repo_id)
            if repo:
                repository_name = repo.get('name')
                place = places.get(repo.get('place_id'))
                if place:
                    place_name = place.get('name')

    ct_title = content_type_name or content_type_slug or 'Text'
    if ct_title:
        ct_title = ct_title.replace('_', ' ').title()
    title = '%s of %s' % (ct_title, label or item_part_id or ('TextContentXML #%s' % moa_id))

    status_name = ''
    status_slug = ''
    status = text_content_xml_statuses.get(status_id)
    if status:
        status_name = status.get('name') or ''
        status_slug = status.get('slug') or ''
    status_sort_order = ''
    if status:
        status_sort_order = status.get('sort_order') or ''

    text_name = ''
    text_date = ''
    text_date_sort = ''
    text_url = ''
    text_legacy_id = ''
    attribution_title = ''
    attribution_message = ''
    attribution_short_message = ''
    text_content_created = ''
    text_content_modified = ''
    text_content_text_id = ''
    text_content_attribution_id = ''
    language_names = []

    if tc:
        text_content_created = tc.get('created') or ''
        text_content_modified = tc.get('modified') or ''
        text_content_text_id = tc.get('text_id') or ''
        text_content_attribution_id = tc.get('attribution_id') or ''

        text_row = texts.get(text_content_text_id)
        if text_row:
            text_name = text_row.get('name') or ''
            text_date = text_row.get('date') or ''
            text_date_sort = text_row.get('date_sort') or ''
            text_url = text_row.get('url') or ''
            text_legacy_id = text_row.get('legacy_id') or ''

        attribution_row = content_attributions.get(text_content_attribution_id)
        if attribution_row:
            attribution_title = attribution_row.get('title') or ''
            attribution_message = attribution_row.get('message') or ''
            attribution_short_message = attribution_row.get('short_message') or ''

        for language_id in text_content_languages.get(text_content_id, []):
            lang = languages.get(language_id)
            if lang and lang.get('name'):
                language_names.append(lang['name'])

    meta = {
        'moa_id': moa_id or '',
        'text_content_id': text_content_id or '',
        'item_part_id': item_part_id or '',
        'current_item_id': current_item_id or '',
        'content_type_name': content_type_name or '',
        'content_type_slug': content_type_slug or '',
        'item_part_label': label or '',
        'title': title,
        'moa_created': created or '',
        'edition_date': modified or '',
        'status_id': status_id or '',
        'status_name': status_name,
        'status_slug': status_slug,
        'status_sort_order': status_sort_order,
        'tei_doc_status': map_to_tei_doc_status(status_slug),
        'text_name': text_name,
        'text_date': text_date,
        'text_date_sort': text_date_sort,
        'text_url': text_url,
        'text_legacy_id': text_legacy_id,
        'text_content_created': text_content_created,
        'text_content_modified': text_content_modified,
        'text_content_text_id': text_content_text_id,
        'text_content_attribution_id': text_content_attribution_id,
        'attribution_title': attribution_title,
        'attribution_message': attribution_message,
        'attribution_short_message': attribution_short_message,
        'language_names': uniq(language_names),
        'transcription_moa_id': '',
        'translation_moa_id': '',
        'included_content_types': [],
        'revision_notes': [],
        'ms': None,
    }
    if place_name or repository_name or shelfmark:
        meta['ms'] = {
            'place': place_name or '',
            'repository': repository_name or '',
            'shelfmark': shelfmark or '',
        }
    return meta


def read_template(path):
    with open(path, 'rb') as fh:
        return fh.read().decode('utf-8')


def xml_escape(text):
    if text is None:
        return ''
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))


def normalize_tei_when(value):
    value = (value or '').strip()
    if not value:
        return ''
    # PostgreSQL style: YYYY-MM-DD HH:MM:SS(.ffffff)+HH
    m = re.match(
        r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2})(?::?(\d{2}))?$',
        value,
    )
    if m:
        date_part, time_part, frac, tzh, tzm = m.groups()
        frac = frac or ''
        tzm = tzm or '00'
        return '%sT%s%s%s:%s' % (date_part, time_part, frac, tzh, tzm)
    # Already a valid ISO date or datetime-like value we can keep.
    if re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', value):
        return value
    if re.match(r'^\d{4}-\d{2}-\d{2}T', value):
        return value
    # Last resort: keep date part if present.
    if re.match(r'^\d{4}-\d{2}-\d{2}', value):
        return value[:10]
    return ''


def tei_when_attr(value):
    value = normalize_tei_when(value)
    if not value:
        return ''
    return ' when="%s"' % xml_escape(value)


EXPECTED_XHTML_TAGS = {
    'p', 'span', 'em', 'br', 'div', 'sup', 'sub', 'i', 'b', 'u', 'strong', 'small'
}


def sanitize_xhtml_for_expected_tags(xhtml):
    if not xhtml:
        return xhtml

    # Line-break markers are carried in span text (e.g. "|", "-|") in the source.
    # Preserve only the structural lb marker and drop its textual payload.
    xhtml = re.sub(
        r'(<span\b[^>]*\bdata-dpt=(["\'])lb\2[^>]*>)(.*?)(</span>)',
        r'\1\4',
        xhtml,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def repl(match):
        token = match.group(0)
        m = re.match(r'^</?\s*([A-Za-z][\w:-]*)', token)
        if not m:
            return xml_escape(token)
        name = m.group(1).lower()
        if name in EXPECTED_XHTML_TAGS:
            return token
        # Keep unknown tags as literal text, not markup.
        return xml_escape(token)

    return re.sub(r'<[^>]*>', repl, xhtml)


def xml_id_from_numeric_id(value):
    value = str(value or '').strip()
    if not value:
        return 'moa-unknown'
    # xml:id must be an NCName and cannot start with a digit.
    return 'moa-%s' % re.sub(r'[^A-Za-z0-9_.-]+', '-', value)


def title_to_filename(title):
    if not title:
        return ''
    cleaned = re.sub(r'\s+', ' ', title).strip()
    match = re.match(r'^(?P<kind>\w+)\s+of\s+(?P<rest>.+)$', cleaned, re.IGNORECASE)
    if match:
        cleaned = '%s %s' % (match.group('rest'), match.group('kind').title())
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    return cleaned


def build_xslt(meta, template_path):
    template = read_template(template_path)
    tei_xml_id = xml_escape(xml_id_from_numeric_id(meta.get('moa_id', '')))
    title = xml_escape(meta.get('title', 'Exported TEI'))
    edition_date = xml_escape(meta.get('edition_date', ''))
    moa_id = xml_escape(str(meta.get('moa_id', '') or ''))
    text_content_id = xml_escape(str(meta.get('text_content_id', '') or ''))
    transcription_moa_id = xml_escape(str(meta.get('transcription_moa_id', '') or ''))
    translation_moa_id = xml_escape(str(meta.get('translation_moa_id', '') or ''))
    item_part_id = xml_escape(str(meta.get('item_part_id', '') or ''))
    current_item_id = xml_escape(str(meta.get('current_item_id', '') or ''))
    content_type_name = xml_escape(meta.get('content_type_name', '') or '')
    content_type_slug = xml_escape(meta.get('content_type_slug', '') or '')
    item_part_label = xml_escape(meta.get('item_part_label', '') or '')
    status_name = xml_escape(meta.get('status_name', '') or '')
    status_slug = xml_escape(meta.get('status_slug', '') or '')
    tei_doc_status = xml_escape(meta.get('tei_doc_status', 'draft') or 'draft')
    status_id = xml_escape(str(meta.get('status_id', '') or ''))
    status_sort_order = xml_escape(str(meta.get('status_sort_order', '') or ''))
    text_name = xml_escape(meta.get('text_name', '') or '')
    text_date = xml_escape(meta.get('text_date', '') or '')
    text_date_sort = xml_escape(meta.get('text_date_sort', '') or '')
    text_url = xml_escape(meta.get('text_url', '') or '')
    text_legacy_id = xml_escape(str(meta.get('text_legacy_id', '') or ''))
    attribution_title = xml_escape(meta.get('attribution_title', '') or '')
    attribution_message = xml_escape(meta.get('attribution_message', '') or '')
    attribution_short_message = xml_escape(meta.get('attribution_short_message', '') or '')
    moa_created = xml_escape(meta.get('moa_created', '') or '')
    text_content_created = xml_escape(meta.get('text_content_created', '') or '')
    text_content_modified = xml_escape(meta.get('text_content_modified', '') or '')
    text_content_text_id = xml_escape(str(meta.get('text_content_text_id', '') or ''))
    text_content_attribution_id = xml_escape(str(meta.get('text_content_attribution_id', '') or ''))
    language_names = xml_escape(', '.join(meta.get('language_names', []) or []))
    included_content_types = xml_escape(', '.join(meta.get('included_content_types', []) or []))
    revision_notes = xml_escape(' | '.join(meta.get('revision_notes', []) or []))
    revision_when_attr = tei_when_attr(meta.get('edition_date', ''))
    ms = meta.get('ms') or {}
    place = xml_escape(ms.get('place', ''))
    repository = xml_escape(ms.get('repository', ''))
    shelfmark = xml_escape(ms.get('shelfmark', ''))

    header = u"""  <xsl:template match="/root">
    <TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="%s">
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title>%s</title>
            <respStmt>
              <resp>Exported from Models of Authority data</resp>
              <name>tei_exporter</name>
            </respStmt>
          </titleStmt>
          <editionStmt>
            <edition>Models of Authority edition, <date>%s</date></edition>
          </editionStmt>
          <publicationStmt>
            <publisher>Models of Authority</publisher>
            <idno type="textcontentxml">%s</idno>
            <idno type="textcontent">%s</idno>
            <idno type="transcription_textcontentxml">%s</idno>
            <idno type="translation_textcontentxml">%s</idno>
            <availability>
              <p>Status unknown. Exported for research and migration workflows.</p>
            </availability>
          </publicationStmt>
          <sourceDesc>
            <msDesc>
              <msIdentifier>
                <settlement>%s</settlement>
                <repository>%s</repository>
                <idno>%s</idno>
              </msIdentifier>
              <msContents>
                <summary>%s</summary>
              </msContents>
            </msDesc>
          </sourceDesc>
        </fileDesc>
        <revisionDesc status="%s">
          <change%s status="%s">Exported by standalone tei_exporter.</change>
          <change%s status="%s">%s</change>
        </revisionDesc>
      </teiHeader>
      <text><body><div><xsl:apply-templates /></div></body></text>
    </TEI>
  </xsl:template>
""" % (
        tei_xml_id,
        title,
        edition_date,
        moa_id,
        text_content_id,
        transcription_moa_id,
        translation_moa_id,
        place,
        repository,
        shelfmark,
        item_part_label or title,
        tei_doc_status,
        revision_when_attr,
        tei_doc_status,
        revision_when_attr,
        tei_doc_status,
        revision_notes,
    )

    return template.replace('<!--__HEADER__-->', header)


def build_root_from_xhtml(xhtml):
    # Use HTML parser to tolerate invalid XML (e.g., valueless attributes).
    fragments = lxml_html.fragments_fromstring(xhtml)
    root = etree.Element('root')
    for frag in fragments:
        if isinstance(frag, str):
            if len(root):
                last = root[-1]
                last.tail = (last.tail or '') + frag
            else:
                root.text = (root.text or '') + frag
        else:
            root.append(frag)
    return root


def normalize_text_whitespace(elem):
    for node in elem.iter():
        if node.text:
            node.text = _normalize_text_value(node.text)
        if node.tail:
            node.tail = _normalize_text_value(node.tail)


def _normalize_text_value(text):
    if text is None:
        return None
    leading = ' ' if text[:1].isspace() else ''
    trailing = ' ' if text[-1:].isspace() else ''
    core = text.replace('\xa0', ' ')
    core = re.sub(r'\s+', ' ', core).strip()
    if not core:
        return leading or trailing or ''
    return leading + core + trailing


def normalize_tag_spacing(xml_text):
    # Remove stray spaces before closing angle brackets, e.g. "<p >" -> "<p>"
    return re.sub(r'<([A-Za-z_:][\w:.-]*)([^<>]*?)\s+>', r'<\1\2>', xml_text)


def wrap_text_nodes(elem, width=80, indent_unit='   '):
    for node in elem.iter():
        if _is_in_tei_header(node):
            continue
        # Compute indentation based on depth for wrapped lines.
        depth = 0
        parent = node.getparent()
        while parent is not None:
            depth += 1
            parent = parent.getparent()
        indent = indent_unit * (depth + 1)

        if node.text and '\n' not in node.text and len(node.text) > width:
            node.text = _wrap_text_preserving_edges(node.text, width, indent)
        if node.tail and '\n' not in node.tail and len(node.tail) > width:
            node.tail = _wrap_text_preserving_edges(node.tail, width, indent)


def _wrap_text_preserving_edges(text, width, indent):
    if text is None:
        return None
    leading = ' ' if text[:1].isspace() else ''
    trailing = ' ' if text[-1:].isspace() else ''
    core = text.strip()
    if not core:
        return leading or trailing or ''
    filled = textwrap.fill(
        core,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
        subsequent_indent='\n' + indent,
    )
    return leading + filled + trailing


def _is_in_tei_header(node):
    cur = node
    while cur is not None:
        if cur.tag.endswith('teiHeader'):
            return True
        cur = cur.getparent()
    return False


def cleanup_pretty_print(xml_text):
    lines = [line.rstrip() for line in xml_text.splitlines()]
    cleaned = [line for line in lines if line.strip()]
    return '\n'.join(cleaned)


def serialize_tei_root(tei_root):
    tei = etree.tostring(tei_root, encoding='utf-8', pretty_print=True)
    tei_text = tei.decode('utf-8')
    tei_text = tei_text.replace('xmlns=""', '')
    tei_text = normalize_tag_spacing(tei_text)
    tei_text = cleanup_pretty_print(tei_text)
    return tei_text.encode('utf-8')


def transform_xhtml_to_tei_root(xhtml, xslt_string):
    xhtml = html_unescape(xhtml)
    xhtml = sanitize_xhtml_for_expected_tags(xhtml)
    root = build_root_from_xhtml(xhtml)
    xslt = etree.XSLT(etree.fromstring(xslt_string.encode('utf-8')))
    result = xslt(root)
    tei_root = result.getroot()
    normalize_text_whitespace(tei_root)
    wrap_text_nodes(tei_root)
    return tei_root


def transform_xhtml_to_tei(xhtml, xslt_string):
    tei_root = transform_xhtml_to_tei_root(xhtml, xslt_string)
    return serialize_tei_root(tei_root)


def build_combined_tei(section_contents, xslt_string):
    ns = 'http://www.tei-c.org/ns/1.0'
    xml_ns = 'http://www.w3.org/XML/1998/namespace'
    sample_type = next(iter(section_contents.keys()))
    sample_root = transform_xhtml_to_tei_root(section_contents[sample_type], xslt_string)

    root = etree.Element('{%s}TEI' % ns, nsmap={None: ns})
    xml_id = sample_root.get('{%s}id' % xml_ns)
    if xml_id:
        root.set('{%s}id' % xml_ns, xml_id)

    header = sample_root.find('{%s}teiHeader' % ns)
    if header is not None:
        root.append(deepcopy(header))

    text_el = etree.SubElement(root, '{%s}text' % ns)
    body_el = etree.SubElement(text_el, '{%s}body' % ns)

    for section_type in ['transcription', 'translation']:
        content = section_contents.get(section_type)
        if not content:
            continue
        section_root = transform_xhtml_to_tei_root(content, xslt_string)
        src_div = section_root.find('./{%s}text/{%s}body/{%s}div' % (ns, ns, ns))
        out_div = etree.SubElement(body_el, '{%s}div' % ns)
        out_div.set('type', section_type)
        if src_div is not None:
            out_div.text = src_div.text
            for child in src_div:
                out_div.append(deepcopy(child))

    return serialize_tei_root(root)


def main():
    parser = argparse.ArgumentParser(description='Export TEI from a pg_dump .sql file.')
    parser.add_argument('--sql-dump', required=True, help='Path to a pg_dump .sql file.')
    parser.add_argument('--output-dir', default='tei_exports', help='Directory to write TEI files into.')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of records exported.')
    parser.add_argument('--template', default=None, help='Path to tei_templates.xslt (optional).')
    parser.add_argument('--debug', action='store_true', default=False, help='Print parsing diagnostics.')
    parser.add_argument('--skip-errors', action='store_true', default=False, help='Skip rows that fail to parse.')
    args = parser.parse_args()

    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.getcwd(), output_dir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    here = os.path.dirname(os.path.abspath(__file__))
    template_path = args.template or os.path.join(here, 'tei_templates.xslt')

    text_content_types = load_text_content_types(args.sql_dump, debug=args.debug)
    text_contents = load_text_contents(args.sql_dump, debug=args.debug)
    item_parts = load_item_parts(args.sql_dump, debug=args.debug)
    current_items = load_current_items(args.sql_dump, debug=args.debug)
    repositories = load_repositories(args.sql_dump, debug=args.debug)
    places = load_places(args.sql_dump, debug=args.debug)
    text_content_xml_statuses = load_text_content_xml_statuses(args.sql_dump, debug=args.debug)
    texts = load_texts(args.sql_dump, debug=args.debug)
    content_attributions = load_content_attributions(args.sql_dump, debug=args.debug)
    languages = load_languages(args.sql_dump, debug=args.debug)
    text_content_languages = load_text_content_languages(args.sql_dump, debug=args.debug)

    exported = 0
    errors = 0
    grouped = {}
    for row in iter_copy_rows(args.sql_dump, 'digipal_text_textcontentxml', debug=args.debug):
        try:
            moa_id = row[0]
            status_id = row[1]
            text_content_id = row[2]
            created = row[3]
            modified = row[4]
            content = row[5]
        except Exception:
            continue
        if not content:
            continue

        text_content = text_contents.get(text_content_id) or {}
        item_part_id = text_content.get('item_part_id')
        type_id = text_content.get('type_id')
        type_row = text_content_types.get(type_id) or {}
        content_type_slug = (type_row.get('slug') or '').lower().strip()
        if content_type_slug not in ('transcription', 'translation'):
            continue

        meta = build_meta_from_dump(
            moa_id=moa_id,
            text_content_id=text_content_id,
            created=created,
            modified=modified,
            status_id=status_id,
            text_content_types=text_content_types,
            text_contents=text_contents,
            item_parts=item_parts,
            current_items=current_items,
            repositories=repositories,
            places=places,
            text_content_xml_statuses=text_content_xml_statuses,
            texts=texts,
            content_attributions=content_attributions,
            languages=languages,
            text_content_languages=text_content_languages,
        )
        grouped.setdefault(item_part_id or ('text_content_%s' % text_content_id), {})[content_type_slug] = {
            'id': moa_id,
            'text_content_id': text_content_id,
            'content': content,
            'meta': meta,
        }

    for _, records in grouped.items():
        transcription = records.get('transcription')
        translation = records.get('translation')
        if not transcription and not translation:
            continue

        primary = transcription or translation
        meta = dict(primary['meta'])
        label = meta.get('item_part_label') or meta.get('item_part_id') or ('TextContentXML #%s' % primary['id'])
        if transcription and translation:
            meta['title'] = 'Transcription and Translation of %s' % label
        elif transcription:
            meta['title'] = 'Transcription of %s' % label
        else:
            meta['title'] = 'Translation of %s' % label

        meta['moa_id'] = primary['id']
        meta['text_content_id'] = primary['text_content_id']
        meta['transcription_moa_id'] = transcription['id'] if transcription else ''
        meta['translation_moa_id'] = translation['id'] if translation else ''
        meta['included_content_types'] = [k for k in ['transcription', 'translation'] if records.get(k)]
        meta['content_type_name'] = 'Transcription and Translation' if transcription and translation else (
            'Transcription' if transcription else 'Translation'
        )
        meta['content_type_slug'] = 'transcription-translation' if transcription and translation else (
            'transcription' if transcription else 'translation'
        )

        languages_union = []
        revision_notes = []
        for section_type in ['transcription', 'translation']:
            entry = records.get(section_type)
            if not entry:
                continue
            entry_meta = entry['meta']
            languages_union.extend(entry_meta.get('language_names', []))
            revision_notes.append(
                '%s moa=%s status=%s modified=%s' % (
                    section_type,
                    entry['id'],
                    entry_meta.get('status_slug', ''),
                    entry_meta.get('edition_date', ''),
                )
            )

        meta['language_names'] = uniq(languages_union)
        meta['revision_notes'] = revision_notes
        meta['tei_doc_status'] = coalesce_tei_doc_status([
            records[k]['meta'].get('tei_doc_status')
            for k in ['transcription', 'translation']
            if records.get(k)
        ])

        dates = [
            records[k]['meta'].get('edition_date')
            for k in ['transcription', 'translation']
            if records.get(k) and records[k]['meta'].get('edition_date')
        ]
        if dates:
            meta['edition_date'] = max(dates)

        xslt_string = build_xslt(meta, template_path)
        section_contents = {}
        if transcription:
            section_contents['transcription'] = transcription['content']
        if translation:
            section_contents['translation'] = translation['content']

        try:
            tei = build_combined_tei(section_contents, xslt_string)
        except Exception as exc:
            errors += 1
            if args.debug:
                print('ERROR: item_part #%s primary moa #%s: %s' % (meta.get('item_part_id', ''), primary['id'], exc))
            if args.skip_errors:
                continue
            raise

        filename = '%s.xml' % primary['id']
        path = os.path.join(output_dir, filename)
        with open(path, 'wb') as fh:
            fh.write(tei)

        exported += 1
        if args.limit and exported >= args.limit:
            break

    if errors and args.skip_errors:
        print('Exported %s file(s) to %s (%s error(s) skipped)' % (exported, output_dir, errors))
    else:
        print('Exported %s file(s) to %s' % (exported, output_dir))


if __name__ == '__main__':
    main()
