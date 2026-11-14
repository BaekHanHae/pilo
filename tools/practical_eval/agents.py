"""Import external Codex evidence and apply proposed patches only to new copies.

This module does not launch agents. Raw sessions remain local and independent of
PILO's AI Gateway. A task-success score is an exact-evidence proxy, not a human
semantic review. Model-generated code must run under the caller's test sandbox.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3

from .harness import judge_answers, sha


def import_session(result_db, *, arm, events_path, answer_path, tasks, corpus):
    events_path = Path(events_path); answer_path = Path(answer_path)
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    usage = next((e['usage'] for e in reversed(events) if e.get('type') == 'turn.completed' and 'usage' in e), None)
    failure = next((e for e in events if e.get('type') in ('turn.failed','error')), None)
    answer_exists = answer_path.exists()
    answer = json.loads(answer_path.read_text()) if answer_exists else dict(answers=[])
    judged = judge_answers(answer.get('answers', []), tasks, corpus)
    # Capture-window wall time is a proxy: starts at log creation and ends at its
    # final write; it excludes report import and is not CPU or per-task duration.
    stat = events_path.stat()
    elapsed = stat.st_mtime - stat.st_birthtime if hasattr(stat, 'st_birthtime') else None
    status = 'completed' if usage is not None and failure is None and answer_exists else 'failed_or_incomplete'
    with closing(sqlite3.connect(result_db)) as db:
        db.execute('INSERT INTO agent VALUES(?,?,?,?,?,?,?,?,?,?)',
            (arm, status, elapsed, usage.get('input_tokens') if usage else None,
             usage.get('cached_input_tokens') if usage else None,
             usage.get('output_tokens') if usage else None,
             sum(r['evidence_success'] for r in judged), len(tasks),
             sha(events_path.read_bytes()), json.dumps(failure) if failure else None))
        db.commit()
    return dict(arm=arm,status=status,capture_window_seconds=elapsed,usage=usage,
                evidence_successes=sum(r['evidence_success'] for r in judged),
                valid_quotes=sum(r['evidence_valid'] for r in judged),tasks=len(tasks))


def apply_patch_copy(source, destination, replacements, allowed_paths):
    """Never edit the learning repository or accept arbitrary file targets."""
    source = Path(source).resolve(strict=True); destination = Path(destination).absolute()
    prepared = {}
    for replacement in replacements:
        relative = replacement['path']
        if relative not in allowed_paths:
            raise ValueError('Patch outside the reviewed source scope')
        target = (source / relative).resolve(strict=True)
        if not target.is_relative_to(source) or target.is_symlink():
            raise ValueError('Patch path escapes the corpus')
        old, new = replacement['old'], replacement['new']
        body = prepared.get(relative, target.read_text())
        if not old or body.count(old) != 1 or len(new.encode()) > 200_000:
            raise ValueError('Ambiguous, missing or excessive replacement')
        prepared[relative] = body.replace(old, new, 1)
    if not prepared:
        raise ValueError('No proposed repair')
    if destination.exists():
        raise FileExistsError('Previous experiment output preserved')
    shutil.copytree(source, destination)
    for relative, body in prepared.items():
        (destination / relative).write_text(body)
    return dict(changed_files=len(prepared),
                patch_sha256=sha(json.dumps(replacements, sort_keys=True).encode()))


def import_test_log(result_db, *, arm, scope, log_path):
    """Import actual pytest summary counts, preserving incomplete/failed results."""
    import re
    data = Path(log_path).read_bytes()
    lines = data.decode().splitlines()
    summaries = [line for line in lines if re.search(r'\b\d+ (?:passed|failed)\b', line)
                 and re.search(r' in \d+(?:\.\d+)?s', line)]
    if not summaries:
        passed = failed = None
    else:
        counts = dict((label, int(count)) for count, label in
                      re.findall(r'(\d+) (passed|failed)', summaries[-1]))
        passed, failed = counts.get('passed', 0), counts.get('failed', 0)
    with closing(sqlite3.connect(result_db)) as db:
        db.execute('INSERT INTO repair_validation VALUES(?,?,?,?,?)',
                   (arm, scope, passed, failed, sha(data)))
        db.commit()
    return dict(passed=passed,failed=failed,complete=bool(summaries))
