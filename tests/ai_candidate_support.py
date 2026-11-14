"""Isolated candidate installation using real Core, migrations, RBAC and audit.

Only tests accept the augmented shape. Production Core still rejects it.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
from pilo_core.core import Core, schema_shape
from pilo_core.bootstrap import initialize
from pilo_core.operator import provision, register_project
from pilo_core.migrations import statements

CANDIDATE = Path(__file__).resolve().parents[1] / 'pilo_core/sql/0003_ai_attempt_candidate.sql'


class CandidateCore(Core):
    def __init__(self, config_path):
        super().__init__(config_path)
        with closing(sqlite3.connect(':memory:')) as db:
            for _, _, path, _ in self.migrations:
                db.executescript(path.read_text())
            db.executescript(CANDIDATE.read_text())
            self.expected_shape = schema_shape(db)


def install(root, seed=True):
    initialize(root / 'instance')
    config = root / 'instance/database_config.json'
    core = Core(config)
    project = register_project(core, 'test', 'Test', root)['project_id']
    other = register_project(core, 'other', 'Other', root)['project_id']
    with core.connection(write=True) as db:
        for statement in statements(CANDIDATE.read_text()):
            db.execute(statement)
    core = CandidateCore(config)
    provision(core, 'reviewer', ['ai.reconcile'], project)
    with core.connection(write=True) as db:
        db.execute("""INSERT INTO Execution(execution_id,scope_type,project_id,
            actor_type,actor_id,execution_type,created_at,updated_at)
            VALUES('e','PROJECT',?,'SYSTEM','system','AI','t','t')""", (project,))
        db.execute("""INSERT INTO ExecutionStep(step_id,execution_id,step_number,
            step_key,step_type,name) VALUES('s','e',1,'s','AI','Test')""")
        if not seed:
            return core, project, other
        db.execute("""INSERT INTO ApprovalRequest(approval_context_hash,
            policy_version_ref,approval_id,execution_id,resource_type,resource_id,
            action,status,requested_by,requested_at)
            VALUES('hash','policy','approval','e','WORKSPACE','resource',
            'ai.run','PENDING','system','2026-01-01')""")
        db.execute("INSERT INTO ApprovalDecision VALUES('decision','approval','reviewer','APPROVE','Test approval','2026-01-02')")
        db.execute("INSERT INTO ApprovalGrant VALUES('approval',?,'{}',NULL)", (project,))
        db.execute("""INSERT INTO AIAttemptRecord VALUES(
            'a',?,'e','s','test','EXTERNAL','RUNNING',4,'approval',NULL,?,NULL,'t','t',1)""",
            (project, 'a' * 64))
    return core, project, other
