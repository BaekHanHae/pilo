"""Local application contracts. No automatic migration or implicit grants."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import uuid


class ConfigurationError(RuntimeError):
    pass


class AccessDenied(PermissionError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def schema_shape(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE substr(name,1,7)<>'sqlite_' ORDER BY type,name").fetchall()


class Core:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve(strict=True)
        self.config = json.loads(self.config_path.read_text())
        self.path = self._path(self.config['database_path'])
        self.migration = self._path(self.config['applied_migration_path'])
        self.sql = self.migration.read_bytes()
        if hashlib.sha256(self.sql).hexdigest() != self.config['schema_sha256']:
            raise ConfigurationError('Applied migration checksum mismatch')
        self.version = self.config['schema_version']
        if self.version not in (1, 2) or self.config['automatic_migration'] is not False:
            raise ConfigurationError('Unsupported database contract')
        self.migrations = [('0001', 1, self.migration, self.config['schema_sha256'])]
        if self.version == 2:
            extension = self._path(self.config['workspace_migration_path'])
            digest = hashlib.sha256(extension.read_bytes()).hexdigest()
            if digest != self.config['workspace_schema_sha256']:
                raise ConfigurationError('Workspace migration checksum mismatch')
            self.migrations.append(('0002', 2, extension, digest))
        # Build expected schema without importing the historical test runner.
        expected = sqlite3.connect(':memory:')
        try:
            expected.executescript(self.sql.decode('utf-8'))
            for _, _, path, _ in self.migrations[1:]:
                expected.executescript(path.read_text())
            self.expected_shape = schema_shape(expected)
        finally:
            expected.close()

    def _path(self, value):
        p = Path(value)
        return (p if p.is_absolute() else self.config_path.parent / p).resolve(strict=True)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, isolation_level=None, timeout=5)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA recursive_triggers=ON')
            for name in ('foreign_keys', 'recursive_triggers'):
                if db.execute('PRAGMA ' + name).fetchone() != (1,):
                    raise ConfigurationError('Required SQLite enforcement unavailable')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            self._validate(db)
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _validate(self, db):
        if db.execute('PRAGMA user_version').fetchone() != (self.version,):
            raise ConfigurationError('Unsupported schema version')
        history = db.execute('SELECT migration_id,version,name,checksum FROM SchemaMigration ORDER BY version').fetchall()
        if history != [(mid, version, path.name, digest) for mid, version, path, digest in self.migrations]:
            raise ConfigurationError('Unsupported migration history')
        if schema_shape(db) != self.expected_shape:
            raise ConfigurationError('Installed schema drift detected')

    def _authorize(self, db, actor, permission, project=None):
        if self.version == 2:
            from .security import authorize
            return authorize(self, db, actor, permission, project)
        principal = db.execute("SELECT 1 FROM Principal WHERE principal_id=? AND status='ACTIVE'", (actor,)).fetchone()
        granted = db.execute('''SELECT 1 FROM PrincipalRole pr
            JOIN RolePermission rp ON rp.role_id=pr.role_id
            JOIN Permission p ON p.permission_id=rp.permission_id
            WHERE pr.principal_id=? AND p.permission_key=? AND
            ((pr.scope_type='SYSTEM' AND pr.scope_id IS NULL) OR
             (pr.scope_type='PROJECT' AND pr.scope_id=?)) LIMIT 1''', (actor, permission, project)).fetchone()
        if not principal or not granted:
            raise AccessDenied('Permission denied')
        # ABAC semantics remain unimplemented. Fail closed rather than bypass policies.
        if db.execute("SELECT 1 FROM AccessPolicy WHERE status='ACTIVE' LIMIT 1").fetchone():
            raise AccessDenied('Active policy requires an evaluator; operation denied')

    def health(self):
        """Trusted local operator diagnostics; contains no project content."""
        with self.connection() as db:
            integrity = db.execute('PRAGMA integrity_check').fetchall()
            foreign = db.execute('PRAGMA foreign_key_check').fetchall()
            if integrity != [('ok',)] or foreign:
                raise ConfigurationError('Database integrity verification failed')
            self._verify_audit(db)
            return {'status': 'ok', 'schema_version': self.version, 'sqlite_version': sqlite3.sqlite_version,
                    'strict_tables': sum(r[5] for r in db.execute('PRAGMA table_list') if r[2] == 'table'),
                    'triggers': db.execute("SELECT count(*) FROM sqlite_schema WHERE type='trigger'").fetchone()[0],
                    'audit_events': db.execute('SELECT count(*) FROM AuditEvent').fetchone()[0]}

    def list_projects(self, actor):
        with self.connection() as db:
            self._authorize(db, actor, 'project.list')
            columns = ('project_id', 'project_key', 'name', 'status')
            return [dict(zip(columns, r)) for r in db.execute('SELECT project_id,project_key,name,status FROM Project ORDER BY project_key')]

    def get_project(self, actor, project):
        with self.connection() as db:
            self._authorize(db, actor, 'project.read', project)
            row = db.execute('SELECT project_id,project_key,name,status,root_path FROM Project WHERE project_id=?', (project,)).fetchone()
            if not row:
                raise LookupError('Project unavailable')
            return dict(zip(('project_id', 'project_key', 'name', 'status', 'root_path'), row))

    def create_project(self, actor, key, name, root_path):
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise ValueError('Project key must contain 1–128 characters')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Project name is required')
        root = Path(root_path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Project root must be a directory')
        project, space, timestamp = str(uuid.uuid4()), str(uuid.uuid4()), now()
        with self.connection(write=True) as db:
            self._authorize(db, actor, 'project.create')
            self._verify_audit(db)
            db.execute('INSERT INTO Project(project_id,project_key,name,root_path,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                       (project, key, name, str(root), timestamp, timestamp))
            db.execute("INSERT INTO KnowledgeSpace(space_id,space_type,project_id,name,created_at,updated_at) VALUES (?,'PROJECT',?,?,?,?)",
                       (space, project, name, timestamp, timestamp))
            self._audit(db, actor, 'CREATE_PROJECT', project, {'project_key': key, 'space_id': space}, timestamp)
        return {'project_id': project, 'space_id': space}

    def _verify_audit(self, db):
        previous = None
        rows = db.execute('SELECT sequence_number,event_payload,previous_hash,event_hash,event_id,actor_id,action,resource_type,resource_id,created_at FROM AuditEvent ORDER BY sequence_number')
        for expected, row in enumerate(rows, 1):
            seq, payload, prior, digest, event, actor, action, kind, resource, timestamp = row
            if seq != expected or prior != previous or payload is None:
                raise ConfigurationError('Audit sequence verification failed')
            parsed = json.loads(payload)
            if canonical(parsed) != payload or hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise ConfigurationError('Audit payload verification failed')
            if seq == 1:
                if action != 'INITIALIZE_DATABASE' or kind != 'DATABASE' or resource != 'pilo' or parsed.get('actor_id') != actor or parsed.get('created_at') != timestamp or parsed.get('action') != action:
                    raise ConfigurationError('Unsupported audit bootstrap')
            elif parsed != {'format': 'pilo.audit.v1', 'event_id': event, 'sequence_number': seq,
                            'actor_id': actor, 'action': action, 'resource_type': kind, 'resource_id': resource,
                            'created_at': timestamp, 'previous_hash': prior, 'details': parsed.get('details')}:
                raise ConfigurationError('Audit envelope verification failed')
            previous = digest

    def _audit(self, db, actor, action, resource, details, timestamp):
        previous = db.execute('SELECT sequence_number,event_hash FROM AuditEvent ORDER BY sequence_number DESC LIMIT 1').fetchone()
        if not previous:
            raise ConfigurationError('Missing audit bootstrap')
        sequence, prior = previous[0] + 1, previous[1]
        event = str(uuid.uuid4())
        payload = canonical({'format': 'pilo.audit.v1', 'event_id': event, 'sequence_number': sequence,
                             'actor_id': actor, 'action': action, 'resource_type': 'PROJECT',
                             'resource_id': resource, 'created_at': timestamp, 'previous_hash': prior, 'details': details})
        db.execute('INSERT INTO AuditEvent(event_id,sequence_number,actor_id,action,resource_type,resource_id,event_payload,previous_hash,event_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (event, sequence, actor, action, 'PROJECT', resource, payload, prior, hashlib.sha256(payload.encode()).hexdigest(), timestamp))

    def backup(self, destination):
        """Trusted local operator command. Exclusive target, consistent SQLite backup."""
        target = Path(destination).absolute()
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with self.connection() as source:
                self._verify_audit(source)
                out = sqlite3.connect(target)
                try:
                    source.backup(out)
                    self._validate(out)
                    self._verify_audit(out)
                    if out.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or out.execute('PRAGMA foreign_key_check').fetchall():
                        raise ConfigurationError('Backup validation failed')
                finally:
                    out.close()
            return {'backup_path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
        except BaseException:
            target.unlink(missing_ok=True)
            raise
