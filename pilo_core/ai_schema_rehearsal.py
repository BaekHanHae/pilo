"""Offline schema-3 rehearsal; never upgrades an installation or its config.

Only creates a new, explicitly selected artifact directory. The result is not
accepted by production Core or wired into the CLI/migrator.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .core import Core, ConfigurationError, canonical, now, schema_shape
from .migrations import statements

CANDIDATE = Path(__file__).parent / 'sql/0003_ai_attempt_candidate.sql'


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    with path.open('x') as out:
        out.write(canonical(value)); out.flush(); os.fsync(out.fileno())


def _publish(root, report):
    staged = root / 'report.staged.json'
    # An existing staged report is never authoritative: validate DB first.
    staged.unlink(missing_ok=True)
    _write(staged, report)
    os.replace(staged, root / 'report.json')
    fd = os.open(root, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _validate(core, path, candidate_hash):
    with closing(sqlite3.connect(':memory:')) as expected:
        for _, _, migration, _ in core.migrations:
            expected.executescript(migration.read_text())
        expected.executescript(CANDIDATE.read_text())
        shape = schema_shape(expected)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA user_version').fetchone() != (3,) or schema_shape(db) != shape:
            raise ConfigurationError('Invalid rehearsal schema')
        history = db.execute('SELECT migration_id,version,name,checksum FROM SchemaMigration ORDER BY version').fetchall()
        wanted = [(mid, v, p.name, digest) for mid, v, p, digest in core.migrations]
        wanted.append(('0003-candidate', 3, CANDIDATE.name, candidate_hash))
        if history != wanted:
            raise ConfigurationError('Rehearsal migration checksum/history mismatch')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ConfigurationError('Rehearsal integrity failure')
        core._verify_audit(db)


def rehearse(config_path, directory, *, resume=False):
    core = Core(config_path)
    if core.version != 2:
        raise ConfigurationError('Rehearsal requires schema 2; use existing explicit 1→2 upgrade')
    core.health()
    root = Path(directory).absolute()
    identity = dict(source_config=str(core.config_path), config_sha256=checksum(core.config_path),
                    candidate_sha256=checksum(CANDIDATE), format='pilo.ai-rehearsal.v1')
    backup = root / 'schema2.backup.sqlite3'
    target = root / 'schema3.candidate.sqlite3'
    if resume:
        saved = json.loads((root / 'journal.json').read_text())
        if any(saved.get(k) != v for k, v in identity.items()) or checksum(backup) != saved['backup_sha256']:
            raise ConfigurationError('Rehearsal identity/backup checksum mismatch')
    else:
        root.mkdir(mode=0o700)  # Refuse all existing destinations.
        result = core.backup(backup)
        _write(root / 'journal.json', identity | dict(backup_sha256=result['sha256']))
        # Copy from the validated backup, not a moving source database.
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(target)) as db:
                source.backup(db)
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('PRAGMA recursive_triggers=ON')
                db.execute('BEGIN IMMEDIATE')
                try:
                    for statement in statements(CANDIDATE.read_text()): db.execute(statement)
                    db.execute('INSERT INTO SchemaMigration VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('0003-candidate', 3, CANDIDATE.name, identity['candidate_sha256'],
                         now(), 0, 'system', '0.3.1', 'Offline rehearsal only', None))
                    core._audit(db, 'system', 'AI_SCHEMA_REHEARSAL', 'schema',
                                dict(candidate_sha256=identity['candidate_sha256']), now())
                    db.execute('PRAGMA user_version=3')
                    if db.execute('PRAGMA foreign_key_check').fetchall():
                        raise ConfigurationError('Candidate foreign key failure')
                    db.commit()
                except BaseException:
                    db.rollback(); raise
    # Resume never reruns DDL; only committed, fully validated results publish.
    _validate(core, target, identity['candidate_sha256'])
    with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as db:
        core._validate(db); core._verify_audit(db)
    report = identity | dict(backup_sha256=checksum(backup),
        candidate_database_sha256=checksum(target), schema_version=3,
        ai_execution_enabled=False, production_compatible=False,
        status='offline_candidate_validated')
    _publish(root, report)
    return report
