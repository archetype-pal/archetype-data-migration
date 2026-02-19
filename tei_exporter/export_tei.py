#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone exporter: pg_dump (.sql) -> TEI XML
"""
import argparse
import os
import re
import textwrap
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
        if len(row) < 3:
            continue
        ret[row[0]] = {
            'type_id': row[1],
            'item_part_id': row[2],
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


def build_meta_from_dump(tcx_id, text_content_id, modified, text_content_types,
                         text_contents, item_parts, current_items, repositories,
                         places):
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
    title = '%s of %s' % (ct_title, label or item_part_id or ('TextContentXML #%s' % tcx_id))

    meta = {
        'title': title,
        'edition_date': modified or '',
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
    title = xml_escape(meta.get('title', 'Exported TEI'))
    edition_date = xml_escape(meta.get('edition_date', ''))
    authority = xml_escape(meta.get('authority', ''))
    ms = meta.get('ms') or {}
    place = xml_escape(ms.get('place', ''))
    repository = xml_escape(ms.get('repository', ''))
    shelfmark = xml_escape(ms.get('shelfmark', ''))

    header = u"""  <xsl:template match="/root">
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title>%s</title>
          </titleStmt>
          <editionStmt>
            <edition>Models of Authority edition, <date>%s</date></edition>
          </editionStmt>
          <publicationStmt>
            <authority>%s</authority>
          </publicationStmt>
          <sourceDesc>
            <msDesc>
              <msIdentifier>
                <settlement>%s</settlement>
                <repository>%s</repository>
                <idno>%s</idno>
              </msIdentifier>
            </msDesc>
          </sourceDesc>
        </fileDesc>
      </teiHeader>
      <text><body><div><xsl:apply-templates /></div></body></text>
    </TEI>
  </xsl:template>
""" % (title, edition_date, authority, place, repository, shelfmark)

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


def transform_xhtml_to_tei(xhtml, xslt_string):
    xhtml = html_unescape(xhtml)
    root = build_root_from_xhtml(xhtml)
    xslt = etree.XSLT(etree.fromstring(xslt_string.encode('utf-8')))
    result = xslt(root)
    tei_root = result.getroot()
    normalize_text_whitespace(tei_root)
    wrap_text_nodes(tei_root)
    tei = etree.tostring(tei_root, encoding='utf-8', pretty_print=True)
    tei_text = tei.decode('utf-8')
    tei_text = tei_text.replace('xmlns=""', '')
    tei_text = normalize_tag_spacing(tei_text)
    tei_text = cleanup_pretty_print(tei_text)
    return tei_text.encode('utf-8')


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

    exported = 0
    errors = 0
    for row in iter_copy_rows(args.sql_dump, 'digipal_text_textcontentxml', debug=args.debug):
        try:
            tcx_id = row[0]
            text_content_id = row[2]
            modified = row[4]
            content = row[5]
        except Exception:
            continue
        if not content:
            continue

        meta = build_meta_from_dump(
            tcx_id=tcx_id,
            text_content_id=text_content_id,
            modified=modified,
            text_content_types=text_content_types,
            text_contents=text_contents,
            item_parts=item_parts,
            current_items=current_items,
            repositories=repositories,
            places=places,
        )
        xslt_string = build_xslt(meta, template_path)
        try:
            tei = transform_xhtml_to_tei(content, xslt_string)
        except Exception as exc:
            errors += 1
            if args.debug:
                print('ERROR: tcx #%s text_content #%s: %s' % (tcx_id, text_content_id, exc))
            if args.skip_errors:
                continue
            raise
        title_slug = title_to_filename(meta.get('title', ''))
        if title_slug:
            filename = '%s.xml' % title_slug
        else:
            filename = 'tcx%s_textcontent%s.xml' % (tcx_id, text_content_id)
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
