"""Bounded, deterministic query expansion driven by the active domain profile."""

import re

from src.config.domain_config import DomainProfile, get_domain_profile


def normalize_query(query: str) -> str:
    return " ".join(query.split()).strip()


def alias_queries(query: str, profile: DomainProfile | None = None) -> list[str]:
    profile = profile if profile is not None else get_domain_profile()
    result: list[str] = []
    matched_spans: list[tuple[int, int]] = []
    # Prefer the longest alias at overlapping positions (民国时期 before 民国).
    for term in sorted(profile.query_aliases, key=len, reverse=True):
        pattern = re.escape(term)
        if term.isascii() and term[0].isalnum() and term[-1].isalnum():
            pattern = rf"(?<!\w){pattern}(?!\w)"
        match = re.search(pattern, query, re.IGNORECASE)
        if match is None or any(match.start() < end and match.end() > start for start, end in matched_spans):
            continue
        matched_spans.append(match.span())
        for replacement in profile.query_aliases[term]:
            candidate = normalize_query(query[: match.start()] + replacement + query[match.end() :])
            if candidate and candidate != query and candidate not in result:
                result.append(candidate)
    return result


def focused_queries(query: str, profile: DomainProfile | None = None) -> list[str]:
    profile = profile if profile is not None else get_domain_profile()
    result: list[str] = []
    for rule in profile.rewrite_rules:
        if rule.when_contains and not any(hint.casefold() in query.casefold() for hint in rule.when_contains):
            continue
        if not re.search(rule.pattern, query):
            continue
        for replacement in rule.replacements:
            candidate = normalize_query(re.sub(rule.pattern, lambda _: replacement, query, count=1))
            if candidate and candidate != query and candidate not in result:
                result.append(candidate)
    return result


def retry_queries(query: str, *, limit: int = 4) -> list[str]:
    normalized = normalize_query(query)
    if not normalized or limit <= 0:
        return []
    aliases = alias_queries(normalized)
    candidates = aliases + focused_queries(aliases[0] if aliases else normalized)
    return list(dict.fromkeys(candidates))[:limit]


def build_query_variants(query: str, *, scoped: bool = False, broad: bool = True, limit: int = 8) -> list[dict[str, str | float]]:
    """Keep the original query and never cross the caller's document scope."""
    normalized = normalize_query(query)
    variants: list[dict[str, str | float]] = [{"query": normalized or query, "label": "原始问题", "weight": 1.0}]
    if not normalized:
        return variants
    profile = get_domain_profile()
    if scoped:
        candidates = [(text, "领域别名", 0.99) for text in alias_queries(normalized, profile)]
        candidates += [(text, "领域聚焦", 0.98) for text in focused_queries(normalized, profile)]
    elif broad:
        candidates = [(f"{normalized} {suffix}", "领域扩展", 0.97) for suffix in profile.query_suffixes]
        candidates += [(f"{facet} {normalized}", "领域分面", 0.91) for term, facets in profile.query_facets.items() if term in normalized for facet in facets]
        candidates += [(text, "领域别名", 0.99) for text in alias_queries(normalized, profile)]
    else:
        candidates = []
    seen = {normalized}
    for text, label, weight in candidates:
        if len(variants) >= max(1, limit):
            break
        text = normalize_query(text)
        if text and text not in seen:
            seen.add(text)
            variants.append({"query": text, "label": label, "weight": weight})
    return variants
