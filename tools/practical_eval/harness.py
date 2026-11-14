"""Paired retrieval and evidence evaluation with private, local SQLite artifacts.

No agent dispatch, source modifications, external APIs or schema-3 activation.
Task manifests and raw results may contain private code; never commit them.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from pilo_core.bootstrap import initialize
from pilo_core.setup import add_project
from pilo_core.workspace import Workspace

TEXT_SUFFIXES = frozenset(('.py', '.md', '.toml', '.json', '.ts', '.tsx', '.css', '.html'))
EXCLUDED_NAMES = frozenset(('config.toml', 'project.json', 'package-lock.json'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def freeze(source, destination, revision='HEAD'):
    """Copy allowlisted committed files via Git objects, never live data/.env.

    Refuse dirty tracked files; retain source identity and immutable content hashes.
    Excluded files and limited coverage are part of the evaluation, not hidden.
    """
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no']):
        raise ValueError('Dirty tracked source; pin a committed development state first')
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', revision + '^{commit}'], text=True).strip()
    destination.mkdir(mode=0o700)
    manifest = {}
    names = subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-r', '--name-only', commit], text=True).splitlines()
    for name in names:
        path = Path(name)
        if (path.suffix not in TEXT_SUFFIXES or path.name in EXCLUDED_NAMES
                or any(part.startswith('.') for part in path.parts)):
            continue
        raw = subprocess.check_output(['git', '-C', str(source), 'show', commit + ':' + name])
        raw.decode('utf-8')
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest[name] = sha(raw)
    return dict(commit=commit, files=manifest,
                manifest_sha256=sha(json.dumps(manifest, sort_keys=True).encode()))


def validate_tasks(tasks, corpus):
    identifiers = set()
    for task in tasks:
        if (task['id'] in identifiers or not task['query'].strip()
                or not task['question'].strip() or not task['gold']):
            raise ValueError('Unique tasks and nonempty queries/questions required')
        identifiers.add(task['id'])
        for relative, anchor in task['gold'].items():
            path = (corpus / relative).resolve(strict=True)
            if not path.is_relative_to(corpus.resolve()) or anchor not in path.read_text():
                raise ValueError('Gold evidence must match the pinned corpus')


def literal_context(corpus, query, budget):
    """Deterministic literal-search control, not a simulation of Codex behavior."""
    pieces = []; selected = []
    for path in sorted(corpus.rglob('*')):
        if (not path.is_file() or path.suffix not in TEXT_SUFFIXES
                or any(part.startswith('.') or part == '__pycache__'
                       for part in path.relative_to(corpus).parts)): continue
        relative = path.relative_to(corpus).as_posix()
        lines = path.read_text().splitlines()
        for number, line in enumerate(lines, 1):
            if query.casefold() not in line.casefold(): continue
            piece = f'[{relative}:{number}]\n{line}\n'
            if len((''.join(pieces) + piece).encode()) <= budget:
                pieces.append(piece); selected.append(relative)
    return ''.join(pieces), list(dict.fromkeys(selected))


def scores(paths, gold):
    relevant = set(gold)
    selected = list(dict.fromkeys(paths))
    return dict(recall=len(set(selected) & relevant) / len(relevant),
                precision=len(set(selected) & relevant) / len(selected) if selected else 0.0,
                reciprocal_rank=next((1 / rank for rank, path in enumerate(selected, 1) if path in relevant), 0.0))


def init_results(path):
    db = sqlite3.connect(path)
    db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE run(key TEXT PRIMARY KEY,value TEXT NOT NULL) STRICT;
        CREATE TABLE retrieval(task_id TEXT,arm TEXT,query TEXT,paths TEXT,
            recall REAL,precision_score REAL,reciprocal_rank REAL,
            elapsed_seconds REAL,context_bytes INTEGER,snapshot_equal INTEGER,
            evidence_valid INTEGER,context_sha256 TEXT,snapshot_id TEXT,error TEXT,
            PRIMARY KEY(task_id,arm)) STRICT;
        CREATE TABLE repair_validation(arm TEXT,scope TEXT,passed INTEGER,failed INTEGER,
            log_sha256 TEXT,PRIMARY KEY(arm,scope)) STRICT;
        CREATE TABLE agent(arm TEXT PRIMARY KEY,status TEXT,elapsed_seconds REAL,
            input_tokens INTEGER,cached_input_tokens INTEGER,output_tokens INTEGER,
            evidence_successes INTEGER,total INTEGER,artifact_sha256 TEXT,error TEXT) STRICT;
    ''')
    return db


def retrieve_cases(corpus, tasks, output, budget=8192):
    corpus = Path(corpus).resolve(strict=True); output = Path(output).absolute()
    if type(budget) is not int or not 1 <= budget <= 32768:
        raise ValueError('Context budget must be 1–32768 UTF-8 bytes')
    output.mkdir(mode=0o700)  # Existing results are preserved, never overwritten.
    validate_tasks(tasks, corpus)
    start = time.perf_counter(); state = output / 'state'; initialize(state)
    registration = add_project(state / 'database_config.json', 'evaluation', 'Evaluation', corpus)
    core = Workspace(state / 'database_config.json'); project = registration['project_id']
    setup_seconds = time.perf_counter() - start
    with closing(init_results(output / 'results.sqlite3')) as db:
        metadata = dict(setup_seconds=setup_seconds, indexed_files=registration['indexed_files'],
                        corpus_files=sum(p.is_file() and p.suffix in TEXT_SUFFIXES
                            and '__pycache__' not in p.parts
                            and not any(x.startswith('.') for x in p.relative_to(corpus).parts)
                            for p in corpus.rglob('*')),
                        context_budget_bytes=budget, ai_execution_enabled=False,
                        pilo_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
        for key, value in metadata.items(): db.execute('INSERT INTO run VALUES(?,?)', (key, json.dumps(value)))
        contexts = {}
        for task in tasks:
            contexts[task['id']] = {}
            for arm in ('literal', 'pilo'):
                started = time.perf_counter(); error = None; snapshot = None
                try:
                    if arm == 'literal':
                        content, paths = literal_context(corpus, task['query'], budget)
                        replay = None; integrity = True
                    else:
                        result = core.retrieve('pilo-reader', project, task['query'], max_tokens=budget)
                        content = result['content']; snapshot = result['snapshot_id']
                        replay = core.snapshot('pilo-reader', snapshot)['content'] == content
                        with core.connection() as source:
                            rows = source.execute('''SELECT f.logical_path,u.text,u.content_hash
                                FROM ContextSnapshotItem i JOIN ContentUnit u USING(unit_id)
                                JOIN FileRevision r ON r.revision_id=u.revision_id
                                JOIN FileAsset f ON f.file_id=r.file_id
                                WHERE i.snapshot_id=? ORDER BY i.ordinal''', (snapshot,)).fetchall()
                        paths = [row[0] for row in rows]
                        integrity = all(sha(text.encode()) == digest and text in (corpus / path).read_text()
                                        for path, text, digest in rows)
                    metric = scores(paths, task['gold'])
                except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
                    error = type(exc).__name__ + ': ' + str(exc)
                    content = ''; paths = []; replay = False; integrity = False
                    metric = scores([], task['gold'])
                elapsed = time.perf_counter() - started
                contexts[task['id']][arm] = content
                db.execute('INSERT INTO retrieval VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (task['id'], arm, task['query'], json.dumps(paths), metric['recall'],
                     metric['precision'], metric['reciprocal_rank'], elapsed,
                     len(content.encode()), int(replay) if replay is not None else None, int(integrity), sha(content.encode()), snapshot, error))
        db.commit()
        write_json(output / 'contexts.private.json', contexts)
        write_json(output / 'tasks.private.json', tasks)
        metadata['health'] = core.health()['status']
        write_json(output / 'integration.private.json', registration | metadata)
    return metadata


def judge_answers(answers, tasks, corpus):
    """Exact evidence check, not an LLM judge or proof of semantic correctness."""
    gold = {t['id']: t for t in tasks}; seen = set(); results = []
    for answer in answers:
        identifier = answer.get('task_id')
        if identifier in seen or identifier not in gold:
            raise ValueError('Duplicate or unknown agent task ID')
        seen.add(identifier)
        task = gold[identifier]; relative = answer.get('path', ''); quote = answer.get('quote', '')
        path = (Path(corpus) / relative).resolve()
        valid = (path.is_relative_to(Path(corpus).resolve()) and path.is_file()
                 and bool(quote) and quote in path.read_text())
        relevant = relative in task['gold']
        anchor_present = relevant and task['gold'][relative] in quote
        results.append(dict(task_id=identifier, evidence_valid=bool(valid),
                            evidence_success=bool(valid and relevant and anchor_present)))
    return results + [dict(task_id=k, evidence_valid=False, evidence_success=False) for k in gold if k not in seen]


def aggregate(dbpath):
    """Public-safe aggregates: never emit private paths, text, queries or answers."""
    with closing(sqlite3.connect(dbpath)) as db:
        result = {}
        for arm in ('literal', 'pilo'):
            row = db.execute('''SELECT count(*),avg(recall),avg(precision_score),avg(reciprocal_rank),
                avg(elapsed_seconds),sum(context_bytes),sum(snapshot_equal),sum(evidence_valid),
                sum(error IS NOT NULL) FROM retrieval WHERE arm=?''', (arm,)).fetchone()
            result[arm] = dict(zip(('tasks','mean_recall','mean_precision','mrr','mean_seconds',
                'context_bytes','replay_equal','evidence_integrity_valid','failures'), row))
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--tasks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget', type=int, default=8192)
    args = parser.parse_args()
    retrieve_cases(args.corpus, json.loads(args.tasks.read_text()), args.output, args.budget)
    print(json.dumps(aggregate(args.output / 'results.sqlite3'), indent=2))
