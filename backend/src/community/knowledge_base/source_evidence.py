"""Classify source pages and search body text within an already authorized book."""
from __future__ import annotations

import math
import re
from typing import Any

from src.community.knowledge_base.common import normalize_search_text, tokenize_search_text


def page_text(page: dict[str, Any]) -> str:
    return str(page.get('text') or '').strip() or '\n\n'.join(str(p.get('text') or '').strip() for p in page.get('paragraphs', [])).strip()


def page_kind(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 'blank'
    first = re.sub(r'[\s#*]', '', lines[0]).lower()
    if first in {'目录', '目錄', '目次', '總目', '总目', 'contents', 'tableofcontents'} or re.search(r'(?:目次|目錄|目录)$', first):
        return 'toc'
    # Historical OCR often merges a whole contents column into a few lines,
    # mixes Chinese/Arabic page numbers, and drops the heading on later pages.
    # Count leaders and hierarchy entries independently of OCR line boundaries.
    leaders = len(re.findall(r'[.．·…]{2,}', text))
    headings = len(re.findall(r'第[一二三四五六七八九十百0-9]+[章节節款目]', text))
    sentences = len(re.findall(r'[。；;！？!?]', text))
    if leaders >= 5 and headings >= 5 and sentences <= 2:
        return 'toc'
    entries = sum(bool(re.search(r'(?:[.．·…]{2,}|[（(]?\d+[)）]?$)', line)) and len(line) < 100 for line in lines)
    if len(lines) >= 3 and entries >= 3 and entries / len(lines) >= 0.55:
        return 'toc'
    if first in {'序', '序言', '前言', '凡例', '总序', '總序', 'preface', 'foreword'}:
        return 'front_matter'
    if ('出版社' in text and re.search(r'书号|書號|印刷|发行|發行|定价|定價|ISBN', text, re.I)):
        return 'front_matter'
    if len(text) < 80 and not re.search(r'[。；;]|<table', text, re.I):
        return 'front_matter'
    return 'body'


def search_body_pages(payload: dict[str, Any], queries: list[str], *, pages_per_query: int = 2) -> tuple[list[dict[str, Any]], list[str]]:
    """Rank complete body pages per facet, excluding contents and front matter.

    This scans the already loaded, visibility-checked book, with no external
    service call. Each query has its own result allocation so an overview need
    not rely on the first pages or on a contents page listing every period.
    """
    queries = list(dict.fromkeys(str(q).strip() for q in queries if str(q).strip()))
    if not queries or len(queries) > 8:
        raise ValueError('queries requires 1–8 nonempty topic queries')
    if not 1 <= pages_per_query <= 3:
        raise ValueError('pages_per_query must be between 1 and 3')
    body = []
    chapter = ''
    for page in payload.get('pages', []):
        text = page_text(page)
        if page_kind(text) == 'body':
            heading = re.match(r'^(第[一二三四五六七八九十百0-9]+章[^\n]*)', text)
            if heading:
                chapter = heading.group(1)
            body.append((page, text, normalize_search_text(text), chapter))
    selected: dict[int, dict[str, Any]] = {}
    missing = []
    for query in queries:
        terms = set(tokenize_search_text(query))
        weights = {term: math.log(1 + len(body) / (1 + sum(term in normalized for _, _, normalized, _ in body))) for term in terms}
        ranked = []
        for page, text, normalized, chapter in body:
            matched = [term for term in terms if term in normalized]
            if not matched:
                continue
            score = sum(weights[term] * min(len(term), 6) for term in matched)
            score += 4 * sum(weights[term] * min(len(term), 6) for term in terms if term in chapter)
            score /= 1 + len(text) / 6000
            ranked.append((score, int(page.get('pdf_page_no') or page.get('page_no')), page, text, matched, chapter))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        if not ranked:
            missing.append(query)
        for _, number, page, text, matched, chapter in ranked[:pages_per_query]:
            if number not in selected:
                selected[number] = {**page, 'text': text, 'pdf_page_no': number, 'evidence_kind': 'body', 'source_chapter': chapter, 'matched_queries': [], 'matched_terms': []}
            selected[number]['matched_queries'].append(query)
            selected[number]['matched_terms'] = sorted(set(selected[number]['matched_terms']) | set(matched))
    return list(selected.values()), missing
