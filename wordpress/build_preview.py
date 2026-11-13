"""Assemble a local visual review, without WordPress access or publication."""
import argparse
from pathlib import Path


def build(output):
    root = Path(__file__).resolve().parent
    header, body, footer = [(root / name).read_text(encoding='utf-8') for name in
                            ('header-block.html', 'introduction-block.html', 'footer-block.html')]
    # Landing-only root anchors work when this review is opened as a local file or subpath.
    header = header.replace('href="/#zi-how-it-works"', 'href="#zi-how-it-works"')
    html = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow">'
            '<title>ZERO · 소개 페이지 검토</title>'
            '<style>body{margin:0} main{display:block}</style></head><body>'
            + header + '<main>' + body + '</main>' + footer + '</body></html>')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='Local preview HTML path; does not publish.')
    build(parser.parse_args().output)
