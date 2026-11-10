"""Explicit, backed-up 0001 -> 0002 upgrade; restart reconciles config after commit."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from . import __version__
from .core import Core, ConfigurationError, now


def statements(text):
    pending = ''
    for line in text.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    if pending.strip():
        raise ConfigurationError('Incomplete migration')


def upgrade(config_path):
    config_path = Path(config_path).resolve(strict=True)
    config = json.loads(config_path.read_text())
    migration = Path(__file__).resolve().parent / 'sql/0002_workspace.sql'
    digest = hashlib.sha256(migration.read_bytes()).hexdigest()
    updated = dict(config, schema_version=2, workspace_migration_path=str(migration),
                   workspace_schema_sha256=digest, core_source_version=__version__, application_status='workspace_mvp_source_ready',
                   mcp_status='stdio_adapter_ready',mcp_principal=config.get('mcp_principal','system'),mcp_allow_writes=config.get('mcp_allow_writes',False))
    dbpath = Path(config['database_path'])
    if not dbpath.is_absolute():
        dbpath = config_path.parent / dbpath
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=rw', uri=True)) as probe:
        version = probe.execute('PRAGMA user_version').fetchone()[0]
    if version == 1:
        core = Core(config_path)
        backup = dbpath.with_name(dbpath.name+'.pre-0002.backup')
        if backup.exists():
            # Validate an existing backup without overwriting it.
            with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as check:
                core._validate(check)
                if check.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise ConfigurationError('Invalid existing backup')
        else:
            core.backup(backup)
        with core.connection(write=True) as db:
            # connection's validation happens before DDL. No automatic migration.
            for statement in statements(migration.read_text()):
                db.execute(statement)
            db.execute('INSERT INTO SchemaMigration VALUES (?,?,?,?,?,?,?,?,?,?)',
                       ('0002',2,migration.name,digest,now(),0,'system',__version__,'Workspace MVP contracts',None))
            db.execute('PRAGMA user_version=2')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ConfigurationError('Migration foreign key failure')
            core._audit(db,'system','UPGRADE_SCHEMA','schema',{'version':2,'checksum':digest},now())
    elif version != 2:
        raise ConfigurationError('Unsupported upgrade source')
    # If a process stopped after database commit, this validates before recovering config.
    staged = config_path.with_name(config_path.name+'.upgrade-staged')
    with staged.open('w') as out:
        json.dump(updated,out,indent=2); out.flush(); os.fsync(out.fileno())
    try:
        Core(staged).health()
        os.replace(staged,config_path)
    finally:
        staged.unlink(missing_ok=True)
    return Core(config_path).health()
