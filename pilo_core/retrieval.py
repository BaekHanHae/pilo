"""Small deterministic lexical search and bounded evidence selection.

Ranking hints are not authorization or truth labels. No path/query allowlist,
model, vector dependency, or schema migration is required.
"""
from pathlib import PurePosixPath
import re
import unicodedata

RANKER_VERSION = 'lexical-evidence-v2'
STOP_WORDS = frozenset('a an and are as at be by for from how in is it of on or the to where with'.split())


def normalized(text):
    return unicodedata.normalize('NFKC', text).casefold()


def terms(text):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    words = list(dict.fromkeys(re.findall(r'[^\W_]+', normalized(text))))
    return (tuple(w for w in words if w not in STOP_WORDS) or tuple(words))[:16]


def source_role(source):
    """Prefer durable reference docs over generated reports on relevance ties."""
    path = PurePosixPath(source or '')
    words = set(terms(path.stem))
    if any(p in ('reports', 'evaluations', 'logs', 'generated') for p in path.parts):
        return 3
    if path.name.startswith('test_') or 'tests' in path.parts:
        return 2
    if path.suffix.lower() == '.md' and words & {
        'readme', 'specification', 'architecture', 'reference', 'contributing', 'security'}:
        return 0
    return 1


def rank_rows(rows, query):
    """Stable order: mandatory, explicit path, term coverage, phrase, role, density.

    UUIDs never break relevance ties: source, ordinal and content hash do. Each
    nonmandatory candidate must contain at least one meaningful query term.
    """
    query_terms = terms(query); phrase = normalized(query).strip()
    ranked = []
    for row in rows:
        source = row[4] or ''; path = normalized(source); text = normalized(row[2])
        mandatory = row[5] in ('RULE', 'DECISION')
        coverage = sum(word in text or word in path for word in query_terms)
        explicit_path = phrase in path
        if not mandatory and not coverage and not explicit_path:
            continue
        density = sum(min(text.count(word), 3) for word in query_terms)
        key = (not mandatory, not explicit_path, -coverage, phrase not in text,
               source_role(source), -density, source, row[6], row[3])
        ranked.append((key, row[0]))
    return [unit for _, unit in sorted(ranked)]


def diversified(candidates, byid):
    """One unit per source first, then remaining units in stable rank order.

    All mandatory units precede optional context and never face a source cap.
    No arbitrary top-100 truncation may discard mandatory evidence.
    """
    mandatory = []; first = []; deferred = []; seen = set()
    for unit in candidates:
        row = byid[unit]
        if row[5] in ('RULE', 'DECISION'):
            mandatory.append(unit)
        elif (row[1],row[4],row[5] is not None) not in seen:
            first.append(unit); seen.add((row[1],row[4],row[5] is not None))
        else:
            deferred.append(unit)
    return mandatory + first + deferred


def excerpt(text, query, max_bytes):
    """Return a contiguous UTF-8 bounded source slice with character offsets."""
    if len(text.encode()) <= max_bytes:
        return text, 0, len(text)
    # Match positions in original text so normalization never invents offsets.
    starts={0}
    for word in terms(query):
        for match in list(re.finditer(re.escape(word),text,re.IGNORECASE))[:8]:
            line=max(0,text.rfind('\n',0,match.start())+1)
            starts.add(line)
            starts.add(max(0,match.start()-max_bytes//4))
    best=None
    for start in sorted(starts):
        piece=text[start:].encode()[:max_bytes].decode('utf-8',errors='ignore')
        folded=normalized(piece)
        coverage=sum(word in folded for word in terms(query))
        density=sum(min(folded.count(word),3) for word in terms(query))
        key=(-coverage,normalized(query).strip() not in folded,-density,start)
        if best is None or key<best[0]:best=(key,piece,start,start+len(piece))
    return best[1:]
