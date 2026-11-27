"""Small, escaped Markdown subset for an original article's WordPress draft.

Raw HTML is always text. No images, embedded HTML, scripts or remote fetches.
Unsupported Markdown is kept as visible text rather than silently discarded.
"""
import html
import re
from urllib.parse import urlsplit
from fastapi import HTTPException


def inline(value):
    # One pass over source; generated tags are never processed as Markdown again.
    pattern = r'`([^`\n]+)`|(?<!!)\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*'
    out, start = [], 0
    for match in re.finditer(pattern, value):
        out.append(html.escape(value[start:match.start()]))
        code, label, url, bold = match.groups()
        if code is not None:
            out.append('<code>' + html.escape(code) + '</code>')
        elif bold is not None:
            out.append('<strong>' + html.escape(bold) + '</strong>')
        else:
            try:
                parsed = urlsplit(url)
                safe = parsed.scheme in ('https', 'http') and bool(parsed.hostname) and not parsed.username and not parsed.password and not any(ord(c) < 33 for c in url)
            except ValueError:
                safe = False
            out.append(('<a href="' + html.escape(url, quote=True) + '" rel="noopener noreferrer">' + html.escape(label) + '</a>') if safe else html.escape(match.group()))
        start = match.end()
    out.append(html.escape(value[start:]))
    return ''.join(out)


def render_markdown(body):
    if not isinstance(body, str) or len(body) > 50000:
        raise HTTPException(400, '본문은 50000자 이하 문자열이어야 합니다.')
    lines, output, paragraph = body.replace('\r\n', '\n').replace('\r', '\n').split('\n'), [], []
    def flush():
        if paragraph:
            output.append('<p>' + '<br>\n'.join(inline(v) for v in paragraph) + '</p>')
            paragraph.clear()
    def cells(line):
        return [v.strip() for v in line.strip().strip('|').split('|')]
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush(); i += 1; continue
        if line.startswith('```'):
            flush(); code = []; i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i]); i += 1
            output.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
            if i < len(lines): i += 1
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading:
            flush(); level = len(heading[1]); output.append(f'<h{level}>' + inline(heading[2]) + f'</h{level}>'); i += 1; continue
        if '|' in line and i + 1 < len(lines) and all(re.fullmatch(r':?-{3,}:?', v) for v in cells(lines[i+1])) and len(cells(lines[i+1])) == len(cells(line)):
            flush(); headers = cells(line); i += 2
            table = '<table><thead><tr>' + ''.join('<th>' + inline(v) + '</th>' for v in headers) + '</tr></thead><tbody>'
            while i < len(lines) and '|' in lines[i] and len(cells(lines[i])) == len(headers):
                table += '<tr>' + ''.join('<td>' + inline(v) + '</td>' for v in cells(lines[i])) + '</tr>'; i += 1
            output.append(table + '</tbody></table>'); continue
        item = re.match(r'^\s*(?:([-+*])|([0-9]+)[.)])\s+(.+)$', line)
        if item:
            flush(); ordered = item[2] is not None; tag = 'ol' if ordered else 'ul'; items = []
            while i < len(lines):
                item = re.match(r'^\s*(?:([-+*])|([0-9]+)[.)])\s+(.+)$', lines[i])
                if not item or (item[2] is not None) != ordered: break
                items.append('<li>' + inline(item[3]) + '</li>'); i += 1
            output.append('<' + tag + '>' + ''.join(items) + '</' + tag + '>'); continue
        if line.startswith('> '):
            flush(); quotes = []
            while i < len(lines) and lines[i].startswith('> '):
                quotes.append(inline(lines[i][2:])); i += 1
            output.append('<blockquote><p>' + '<br>'.join(quotes) + '</p></blockquote>'); continue
        paragraph.append(line); i += 1
    flush()
    return '\n'.join(output)


def preview(document):
    title, body = document['draft']['title'], document['draft']['body']
    return {'documentId': document['id'], 'revision': document['revision'], 'siteUrl': document['siteUrl'],
            'title': title, 'contentHtml': render_markdown(body), 'status': 'draft',
            'externalExecuted': False, 'renderer': 'escaped-markdown-subset-v1',
            'note': '서버 저장본의 HTML 미리보기입니다. 원시 HTML·이미지·임베드는 실행하지 않습니다. 실제 WP 전송은 미실행입니다.'}
