"""Core-owned evidence registration and conservative checkpoint observation.

Only unchanged READ_ONLY results can be finalized. External and write effects
remain blocked pending a reviewed isolation/approved-output contract.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

from .core import ConfigurationError, canonical
from .storage import ContentStore
from .ai_scope import validate_ai_scope


class ProvenanceRejected(RuntimeError):
    """Evidence or observed workspace cannot establish the result."""


def core_store(core):
    # Derive authority from the trusted installation config, never a parameter.
    root = Path(core.config.get('content_store_path', str(core.path.parent / 'content')))
    if not root.is_absolute():
        root = core.config_path.parent / root
    return ContentStore(root)


def _git(root, *args):
    try:
        result = subprocess.run(
            ['git', '--no-optional-locks', '-C', str(root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            env={'PATH': '/usr/bin:/bin', 'GIT_CONFIG_NOSYSTEM': '1',
                 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0',
                 'GIT_NO_REPLACE_OBJECTS': '1'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvenanceRejected('Git observation unavailable') from exc
    if result.returncode or len(result.stdout) > 2_000_000:
        raise ProvenanceRejected('Git observation failed or exceeded budget')
    return result.stdout


def observe(core, db, project, checkpoint):
    row = db.execute('''SELECT p.root_path,c.manifest_ref,c.manifest_hash,c.git_commit
        FROM Project p JOIN Checkpoint c USING(project_id)
        JOIN CheckpointSeal s USING(checkpoint_id)
        WHERE p.project_id=? AND c.checkpoint_id=? AND p.status='ACTIVE' ''',
        (project, checkpoint)).fetchone()
    if row is None:
        raise ProvenanceRejected('Sealed project checkpoint required')
    root, ref, digest, commit = row
    try:
        raw = core_store(core).get(ref)
        manifest = json.loads(raw)
    except (ValueError, ConfigurationError) as exc:
        raise ProvenanceRejected('Checkpoint content unavailable') from exc
    if (hashlib.sha256(raw).hexdigest() != digest
            or manifest.get('project_id') != project or manifest.get('git_commit') != commit):
        raise ProvenanceRejected('Checkpoint identity mismatch')
    if _git(root, 'rev-parse', '--show-toplevel').strip().decode() != str(Path(root).resolve()):
        raise ProvenanceRejected('Project must be the Git worktree root')
    _git(root, 'cat-file', '-e', commit + '^{commit}')
    head = _git(root, 'rev-parse', '--verify', 'HEAD').strip().decode()
    status = _git(root, 'status', '--porcelain=v1', '--untracked-files=all',
                  '--ignored=matching', '--ignore-submodules=none')
    # Compare actual files as well: status may trust assume-unchanged/skip-worktree.
    diff = _git(root, 'diff', '--no-ext-diff', '--no-textconv', '--binary', commit, '--')
    flags = _git(root, 'ls-files', '-v')
    if (head != commit or status or diff
            or any(line[:1] != b'H' for line in flags.splitlines())):
        raise ProvenanceRejected('Worktree differs from approved checkpoint')
    tree = _git(root, 'rev-parse', commit + '^{tree}').strip().decode()
    return hashlib.sha256(canonical(dict(project_id=project, checkpoint_id=checkpoint,
                                        commit=head, tree=tree)).encode()).hexdigest()


def register_ai_evidence(core, *, actor, attempt_id, project_id, execution_id,
                         step_id, fencing_token, expected_revision, content, now):
    if not isinstance(content, bytes) or len(content) > 2_000_000:
        raise ProvenanceRejected('Bounded evidence bytes required')
    with core.connection(write=True) as db:
        core._authorize(db, actor, 'ai.evidence', project_id)
        row = db.execute('''SELECT project_id,execution_id,step_id,phase,
            fencing_token,revision,effect_class,checkpoint_id FROM AIAttemptRecord
            WHERE attempt_id=?''', (attempt_id,)).fetchone()
        if (type(fencing_token) is not int or type(expected_revision) is not int
                or row is None or row[:6] != (project_id, execution_id, step_id,
                     'RUNNING', fencing_token, expected_revision)):
            raise ProvenanceRejected('Stale evidence identity')
        if row[6] != 'READ_ONLY':
            raise ProvenanceRejected('External/write effects require independent review')
        validate_ai_scope(db, project_id=project_id, execution_id=execution_id,
            step_id=step_id, approval_id=None, checkpoint_id=row[7], side_effecting=False)
        observation = observe(core, db, project_id, row[7])
        digest = core_store(core).put(content)
        evidence = str(uuid.uuid4())
        core._verify_audit(db)
        db.execute('INSERT INTO AIEvidenceRecord VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (evidence, attempt_id, project_id, execution_id, step_id, fencing_token,
             expected_revision, digest, row[7], observation, now))
        core._audit(db, actor, 'AI_EVIDENCE_REGISTER', project_id,
                    dict(evidence_id=evidence, attempt_id=attempt_id, digest=digest,
                         observation_digest=observation), now)
        return evidence, digest


def verify_registered(core, db, evidence_id, digest, attempt_id, project_id,
                      execution_id, step_id, fence, revision, effect, checkpoint):
    if effect != 'READ_ONLY':
        raise ProvenanceRejected('Unknown external/write effects cannot be finalized')
    row = db.execute('''SELECT attempt_id,project_id,execution_id,step_id,
        fencing_token,attempt_revision,content_digest,checkpoint_id,observation_digest
        FROM AIEvidenceRecord WHERE evidence_id=?''', (evidence_id,)).fetchone()
    if row is None or row[:8] != (attempt_id, project_id, execution_id, step_id,
                                 fence, revision, digest, checkpoint):
        raise ProvenanceRejected('Evidence provenance mismatch')
    data = core_store(core).get(digest)
    if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != digest:
        raise ProvenanceRejected('Evidence bytes changed')
    if observe(core, db, project_id, checkpoint) != row[8]:
        raise ProvenanceRejected('Workspace observation changed')
