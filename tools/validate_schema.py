#!/usr/bin/env python3
"""Dependency-free PILO migration runner and regression suite. Python 3.11+."""
import argparse, hashlib, json, pathlib, sqlite3, tempfile, time, platform, subprocess, sys
from datetime import datetime, timezone
ROOT = pathlib.Path(__file__).resolve().parent
SQL = ROOT.parent / 'database/migrations/0001_initial_schema.sql'
NOW = '2026-11-09T00:00:00.000Z'

def connect(path=':memory:'):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA recursive_triggers=ON')  # Also protects against REPLACE deleting history.
    if db.execute('PRAGMA foreign_keys').fetchone() != (1,):
        raise RuntimeError('Foreign-key enforcement unavailable')
    if sqlite3.sqlite_version_info < (3, 37):
        raise RuntimeError('SQLite 3.37 or newer is required')
    db.execute("SELECT json_valid('{}')")
    return db

def statements(text):
    pending = ''
    for line in text.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    if pending.strip():
        raise ValueError('Incomplete SQL statement')

def checks(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('Database integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Foreign-key check failed')

def schema_shape(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE substr(name,1,7) <> 'sqlite_' ORDER BY type,name").fetchall()

def verify_shape(db, text):
    expected = connect()
    try:
        expected.execute('BEGIN')
        for statement in statements(text):
            expected.execute(statement)
        if schema_shape(db) != schema_shape(expected):
            raise ValueError('Installed schema differs from migration')
    finally:
        expected.close()

def migrate(db, text=None):
    text = SQL.read_bytes().decode('utf-8') if text is None else text
    checksum = hashlib.sha256(text.encode()).hexdigest()
    if db.in_transaction:
        raise RuntimeError('Migration requires a connection outside a transaction')
    for pragma in ('foreign_keys','recursive_triggers'):
        if db.execute('PRAGMA '+pragma).fetchone() != (1,):
            raise ValueError('Required connection setting disabled: '+pragma)
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM sqlite_schema WHERE name='SchemaMigration'").fetchone():
            history = db.execute('SELECT migration_id,version,name,checksum FROM SchemaMigration ORDER BY version').fetchall()
            if len(history) != 1 or history[0][:3] != ('0001',1,SQL.name):
                raise ValueError('Unsupported or incomplete migration history')
            row = (history[0][3],)
            if row:
                if row[0] != checksum:
                    raise ValueError('Migration checksum mismatch')
                checks(db)
                verify_shape(db, text)
                if db.execute('PRAGMA user_version').fetchone() != (1,):
                    raise ValueError('SchemaMigration/user_version mismatch')
                db.commit()
                return False
            raise ValueError('Partial or unmanaged schema')
        if schema_shape(db) or db.execute('PRAGMA user_version').fetchone() != (0,):
            raise ValueError('Initial migration requires an empty unmanaged database')
        started = time.monotonic()
        for statement in statements(text):
            db.execute(statement)
        checks(db)
        if db.execute("SELECT count(*) FROM KnowledgeSpace WHERE space_type='COMMON'").fetchone() != (1,):
            raise ValueError('Common space bootstrap failed')
        db.execute('INSERT INTO SchemaMigration VALUES (?,?,?,?,?,?,?,?,?,?)',
                   ('0001',1,SQL.name,checksum,datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),int((time.monotonic()-started)*1000),'system','0.1',
                    'Initial STRICT schema',None))
        db.execute('PRAGMA user_version=1')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    checks(db)
    return True

RESULTS=[]
def test(name, fn):
    try:
        fn()
        RESULTS.append({'test':name,'status':'PASS'})
    except Exception as e:
        RESULTS.append({'test':name,'status':'FAIL','error':repr(e)})
        raise

def suite():
    db=connect()
    test('Atomic initial migration and integrity checks',lambda:migrate(db))
    def insert(table, **values):
        # Explicit fixture values override neutral values for required descriptive fields.
        for _,col,typ,required,default,pk in db.execute(f'PRAGMA table_info({table})'):
            if col not in values and required and default is None:
                values[col]=NOW if col.endswith('_at') else (1 if typ=='INTEGER' else col)
        cols=','.join(values)
        db.execute(f'INSERT INTO {table} ({cols}) VALUES ({",".join("?" for _ in values)})',tuple(values.values()))
    def fails(name,fn,kind=sqlite3.IntegrityError):
        def run():
            db.execute('SAVEPOINT negative')
            try:
                try:fn()
                except kind:return
                raise AssertionError('Invalid operation unexpectedly succeeded')
            finally:
                db.execute('ROLLBACK TO negative');db.execute('RELEASE negative')
        test(name,run)
    for p in ['a','b']:
        insert('Project',project_id=p,project_key=p)
        insert('KnowledgeSpace',space_id=p,space_type='PROJECT',project_id=p)
        insert('FileAsset',file_id=p,space_id=p,logical_path='input.txt')
        insert('FileRevision',revision_id=p,file_id=p,space_id=p)
        db.execute('UPDATE FileAsset SET current_revision_id=? WHERE file_id=?',(p,p))
        insert('ExtractedArtifact',artifact_id=p,space_id=p,revision_id=p,artifact_type='TEXT',extraction_method='PARSER')
        insert('Evidence',evidence_id=p,space_id=p,source_type='FILE',revision_id=p,artifact_id=p)
        insert('Claim',claim_id=p,space_id=p,claim_type='FACT',created_by='system')
        insert('ClaimEvidence',space_id=p,claim_id=p,evidence_id=p,relation='SUPPORTS')
        insert('KnowledgeItem',knowledge_id=p,space_id=p,knowledge_type='FACT',created_by='system')
        insert('KnowledgeVersion',version_id=p,knowledge_id=p,space_id=p,created_by='system')
        insert('KnowledgeEvidence',space_id=p,version_id=p,evidence_id=p,relation='SUPPORTS')
        insert('KnowledgeVersionClaim',space_id=p,version_id=p,claim_id=p,relation='BASED_ON')
        insert('Execution',execution_id=p,scope_type='PROJECT',project_id=p,actor_type='USER',actor_id='system')
        insert('ExecutionStep',step_id=p,execution_id=p)
        insert('AnalysisResult',analysis_id=p,execution_id=p,step_id=p,analysis_method='CODE',status='RUNNING')
    test('Normal source, evidence, claim, execution and knowledge insertion',lambda:checks(db))
    fails('Duplicate project key',lambda:insert('Project',project_id='dup',project_key='a'))
    fails('Second common space',lambda:insert('KnowledgeSpace',space_id='dup',space_type='COMMON'))
    fails('Project space requires project',lambda:insert('KnowledgeSpace',space_id='dup',space_type='PROJECT'))
    fails('STRICT rejects noninteger revision size',lambda:insert('FileRevision',revision_id='bad',file_id='a',space_id='a',revision_number=2,size_bytes='bad'))
    fails('Negative size',lambda:insert('FileRevision',revision_id='bad',file_id='a',space_id='a',revision_number=2,size_bytes=-1))
    fails('Evidence cross-space revision',lambda:insert('Evidence',evidence_id='bad',space_id='a',source_type='FILE',revision_id='b'))
    fails('Evidence mismatched artifact revision',lambda:insert('Evidence',evidence_id='bad',space_id='a',source_type='FILE',revision_id='a',artifact_id='b'))
    fails('Artifact without revision NULL bypass',lambda:insert('Evidence',evidence_id='bad',space_id='a',source_type='WEB',artifact_id='a'))
    fails('FILE evidence without revision',lambda:insert('Evidence',evidence_id='bad',space_id='a',source_type='FILE'))
    fails('Cross-space claim evidence',lambda:insert('ClaimEvidence',space_id='a',claim_id='a',evidence_id='b',relation='SUPPORTS'))
    fails('Cross-space knowledge evidence',lambda:insert('KnowledgeEvidence',space_id='a',version_id='a',evidence_id='b',relation='SUPPORTS'))
    fails('Cross-space knowledge claim',lambda:insert('KnowledgeVersionClaim',space_id='a',version_id='a',claim_id='b',relation='BASED_ON'))
    fails('Unapproved current version',lambda:db.execute("UPDATE KnowledgeItem SET current_version_id='a' WHERE knowledge_id='a'"))
    for p in ['a','b']:
        db.execute("UPDATE KnowledgeVersion SET review_status='APPROVED',approved_by='system',approved_at=? WHERE version_id=?",(NOW,p))
    db.execute("UPDATE KnowledgeItem SET current_version_id='a' WHERE knowledge_id='a'")
    # Direct provenance membership must remain identical after approval.
    insert('KnowledgeVersion',version_id='editable',knowledge_id='a',space_id='a',version_number=2,created_by='system')
    insert('Evidence',evidence_id='extra',space_id='a',source_type='USER_INPUT')
    insert('Claim',claim_id='extra',space_id='a',claim_type='FACT',created_by='system')
    for table,target,relation,changed in [('KnowledgeEvidence','evidence_id','SUPPORTS','CONTEXT'),('KnowledgeVersionClaim','claim_id','BASED_ON','INCLUDES')]:
        def draft_workflow(t=table,c=target,r=relation,changed=changed):
            db.execute('SAVEPOINT draft_workflow')
            try:
                insert(t,space_id='a',version_id='editable',**{c:'a'},relation=r)
                db.execute(f"UPDATE {t} SET relation=? WHERE version_id='editable'",(changed,))
                assert db.execute(f"SELECT relation FROM {t} WHERE version_id='editable'").fetchone()==(changed,)
                db.execute(f"DELETE FROM {t} WHERE version_id='editable'")
                insert(t,space_id='a',version_id='editable',**{c:'extra'},relation=r)
                db.execute("UPDATE KnowledgeVersion SET review_status='APPROVED',approved_by='system',approved_at=? WHERE version_id='editable'",(NOW,))
                checks(db)
            finally:
                db.execute('ROLLBACK TO draft_workflow');db.execute('RELEASE draft_workflow')
        test(table+' draft editing then approval succeeds',draft_workflow)
        def frozen(name,fn):
            def checked():
                try:fn()
                except sqlite3.IntegrityError as e:
                    if 'Approved knowledge associations are immutable' not in str(e):raise AssertionError('Unexpected rejection: '+str(e))
                    raise
            fails(name,checked)
        frozen(table+' approved insert blocked',lambda t=table,c=target,r=relation:insert(t,space_id='a',version_id='a',**{c:'extra'},relation=r))
        frozen(table+' approved relation update blocked',lambda t=table,ch=changed:db.execute(f"UPDATE {t} SET relation=? WHERE version_id='a'",(ch,)))
        frozen(table+' approved delete blocked',lambda t=table:db.execute(f"DELETE FROM {t} WHERE version_id='a'"))
        frozen(table+' move out of approved version blocked',lambda t=table:db.execute(f"UPDATE {t} SET version_id='editable' WHERE version_id='a'"))
        insert(table,space_id='a',version_id='editable',**{target:'extra'},relation=relation)
        frozen(table+' move into approved version blocked',lambda t=table:db.execute(f"UPDATE {t} SET version_id='a' WHERE version_id='editable'"))
        frozen(table+' replace approved link blocked',lambda t=table,c=target,r=relation:db.execute(f"INSERT OR REPLACE INTO {t}(space_id,version_id,{c},relation,created_at) VALUES ('a','a','a',?,?)",(r,NOW)))
        test(table+' rejected edits preserve approved snapshot',lambda t=table,c=target,r=relation:assert_equal(db.execute(f"SELECT {c},relation FROM {t} WHERE version_id='a'").fetchall(),[('a',r)]))

    fails('Wrong owner current knowledge version',lambda:db.execute("UPDATE KnowledgeItem SET current_version_id='b' WHERE knowledge_id='a'"))
    fails('Duplicate version number',lambda:insert('KnowledgeVersion',version_id='dup',knowledge_id='a',space_id='a',created_by='system'))
    fails('Cross-execution dependency',lambda:insert('ExecutionStepDependency',execution_id='a',step_id='a',depends_on_step_id='b'))
    fails('Missing execution step',lambda:insert('AnalysisResult',analysis_id='bad',execution_id='a',step_id='missing',analysis_method='CODE'))
    fails('Model invocation execution mismatch',lambda:insert('ModelInvocation',invocation_id='bad',execution_id='a',analysis_id='b'))
    fails('Error analysis execution mismatch',lambda:insert('ErrorRecord',error_id='bad',execution_id='a',analysis_id='b'))
    fails('Pinned reference requires version',lambda:insert('KnowledgeReference',reference_id='bad',source_space_id='a',target_knowledge_id='b',reference_mode='PINNED',created_by='system'))
    insert('ApprovalRequest',approval_id='approve',resource_type='KNOWLEDGE_PROMOTION',resource_id='promote',resource_version_ref='a',resource_hash='content_hash',action='PROMOTE',status='PENDING',requested_by='system')
    fails('Direct approval without decision',lambda:db.execute("UPDATE ApprovalRequest SET status='APPROVED',resolved_at=? WHERE approval_id='approve'",(NOW,)))
    insert('ApprovalDecision',decision_id='decision',approval_id='approve',decided_by='system',decision='APPROVE')
    test('Decision atomically resolves request',lambda:assert_equal(db.execute("SELECT status FROM ApprovalRequest WHERE approval_id='approve'").fetchone(),('APPROVED',)))
    fails('Duplicate final decision',lambda:insert('ApprovalDecision',decision_id='dup',approval_id='approve',decided_by='system',decision='REJECT'))
    insert('KnowledgePromotion',promotion_id='promote',idempotency_key='request-1',source_knowledge_id='a',source_version_id='a',approval_id='approve',requested_by='system',status='APPROVED')
    fails('Promotion completion without target',lambda:db.execute("UPDATE KnowledgePromotion SET status='COMPLETED' WHERE promotion_id='promote'"))
    insert('KnowledgeItem',knowledge_id='common-item',space_id='common',knowledge_type='FACT',created_by='system')
    insert('KnowledgeVersion',version_id='common-version',knowledge_id='common-item',space_id='common',created_by='system',review_status='APPROVED',approved_by='system',approved_at=NOW)
    fails('Promotion without lineage',lambda:db.execute("UPDATE KnowledgePromotion SET status='COMPLETED',target_knowledge_id='common-item',target_version_id='common-version' WHERE promotion_id='promote'"))
    insert('KnowledgeLineage',lineage_id='lineage',source_knowledge_id='a',source_version_id='a',target_knowledge_id='common-item',target_version_id='common-version',relation_type='PROMOTED_FROM',promotion_id='promote')
    db.execute("UPDATE KnowledgePromotion SET status='COMPLETED',target_knowledge_id='common-item',target_version_id='common-version' WHERE promotion_id='promote'")
    test('Approved promotion with common version and lineage',lambda:checks(db))
    insert('AuditEvent',event_id='audit',actor_id='system',action='TEST',resource_type='TEST')
    for table,key,val in [('FileRevision','revision_id','a'),('KnowledgeVersion','version_id','a'),('Evidence','evidence_id','a'),('ApprovalDecision','decision_id','decision'),('AuditEvent','event_id','audit'),('KnowledgeLineage','lineage_id','lineage')]:
        fails(table+' delete blocked',lambda t=table,k=key,v=val:db.execute(f'DELETE FROM {t} WHERE {k}=?',(v,)))
    fails('Knowledge content update blocked',lambda:db.execute("UPDATE KnowledgeVersion SET content_hash='tampered' WHERE version_id='a'"))
    fails('Approved review downgrade blocked',lambda:db.execute("UPDATE KnowledgeVersion SET review_status='DRAFT',approved_by=NULL,approved_at=NULL WHERE version_id='a'"))
    fails('Audit update blocked',lambda:db.execute("UPDATE AuditEvent SET action='tampered'"))
    def deferred():
        db.execute('BEGIN')
        db.execute("UPDATE FileAsset SET current_revision_id='b' WHERE file_id='a'")
        try:
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
        else:raise AssertionError('Deferred pointer committed')
        assert db.execute("SELECT current_revision_id FROM FileAsset WHERE file_id='a'").fetchone()==('a',)
    test('Deferred file owner FK fails at commit and rolls back',deferred)
    def rollback():
        db.execute('BEGIN');insert('Project',project_id='rollback',project_key='rollback');db.rollback()
        assert db.execute("SELECT 1 FROM Project WHERE project_id='rollback'").fetchone() is None
    test('Business transaction rollback',rollback)
    test('Same-checksum migration safely skipped',lambda:assert_equal(migrate(db),False))
    def checksum_failure():
        try:migrate(db,SQL.read_text()+'\n-- changed\n')
        except ValueError:return
        raise AssertionError('Changed checksum accepted')
    test('Changed migration checksum refused',checksum_failure)
    def atomic():
        fresh=connect()
        try:migrate(fresh,SQL.read_text()+'\nCREATE TABLE invalid syntax;\n')
        except sqlite3.Error:pass
        else:raise AssertionError('Injected error did not fail')
        assert fresh.execute("SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()==[]
        migrate(fresh);checks(fresh);fresh.close()
    test('Late migration error rolls back all DDL and seeds; retry succeeds',atomic)
    def metadata():
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        assert all(r[5]==1 for r in db.execute('PRAGMA table_list') if r[1] in tables)
        for t in tables:
            # Forces SQLite to resolve every FK, including those with no fixture rows.
            db.execute(f'EXPLAIN DELETE FROM {t} WHERE 0')
        checks(db)
    test('All tables STRICT and all FK parent declarations resolve',metadata)
    fails('Common singleton cannot be deleted',lambda:db.execute("DELETE FROM KnowledgeSpace WHERE space_id='common'"))
    fails('Promotion idempotency key duplicate',lambda:insert('KnowledgePromotion',promotion_id='duplicate',idempotency_key='request-1',source_knowledge_id='a',source_version_id='a',requested_by='system'))
    fails('Promoted lineage mismatched request',lambda:insert('KnowledgeLineage',lineage_id='bad',source_knowledge_id='b',source_version_id='b',target_knowledge_id='common-item',target_version_id='common-version',relation_type='PROMOTED_FROM',promotion_id='promote'))
    insert('Evidence',evidence_id='common-evidence',space_id='common',source_type='USER_INPUT')
    insert('EvidenceLineage',lineage_id='evidence-lineage',source_evidence_id='a',target_evidence_id='common-evidence',relation_type='PROMOTED_FROM',promotion_id='promote')
    fails('Promoted evidence lineage wrong source space',lambda:insert('EvidenceLineage',lineage_id='bad',source_evidence_id='b',target_evidence_id='common-evidence',relation_type='PROMOTED_FROM',promotion_id='promote'))
    def disk():
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'pilo.sqlite3'
            first=connect(path);migrate(first);first.close()
            second=connect(path);assert migrate(second) is False;checks(second);second.close()
    test('On-disk migration, reopen and checksum verification',disk)
    insert('ApprovalRequest',approval_id='changes',resource_type='TEST',resource_id='test',action='REVIEW',status='PENDING',requested_by='system')
    insert('ApprovalDecision',decision_id='changes-decision',approval_id='changes',decided_by='system',decision='REQUEST_CHANGES')
    test('Request changes preserves distinct terminal status',lambda:assert_equal(db.execute("SELECT status FROM ApprovalRequest WHERE approval_id='changes'").fetchone(),('CHANGES_REQUESTED',)))
    fails('Changes-requested request cannot reopen',lambda:db.execute("UPDATE ApprovalRequest SET status='PENDING',resolved_at=NULL WHERE approval_id='changes'"))
    test('DRAFT is default review state',lambda:assert_equal(db.execute("SELECT dflt_value FROM pragma_table_info('KnowledgeVersion') WHERE name='review_status'").fetchone(),("'DRAFT'",)))
    test('Migration secondary version marker matches',lambda:assert_equal(db.execute('PRAGMA user_version').fetchone(),(1,)))
    def marker_mismatch():
        db.execute('PRAGMA user_version=0')
        try:
            try:migrate(db)
            except ValueError:return
            raise AssertionError('Version mismatch accepted')
        finally:db.execute('PRAGMA user_version=1')
    test('Migration refuses secondary marker mismatch',marker_mismatch)
    # Approved claim support is part of the version's provenance, including indirect moves.
    def frozen_claim(name, sql, args=()):
        def run():
            try:db.execute(sql,args)
            except sqlite3.IntegrityError as e:
                if 'Approved claim evidence is immutable' not in str(e):raise AssertionError(str(e))
                raise
        fails(name,run)
    frozen_claim('Approved claim support insertion blocked',"INSERT INTO ClaimEvidence VALUES ('a','a','extra','SUPPORTS',NULL,?)",(NOW,))
    frozen_claim('Approved claim support assessment update blocked',"UPDATE ClaimEvidence SET assessment='changed' WHERE claim_id='a'")
    frozen_claim('Approved claim support delete blocked',"DELETE FROM ClaimEvidence WHERE claim_id='a'")
    frozen_claim('Approved claim support move out blocked',"UPDATE ClaimEvidence SET claim_id='extra' WHERE claim_id='a'")
    insert('ClaimEvidence',space_id='a',claim_id='extra',evidence_id='extra',relation='SUPPORTS')
    frozen_claim('Approved claim support move in blocked',"UPDATE ClaimEvidence SET claim_id='a' WHERE claim_id='extra'")
    frozen_claim('Approved claim support REPLACE blocked',"INSERT OR REPLACE INTO ClaimEvidence VALUES ('a','a','a','CONTEXT',NULL,?)",(NOW,))
    test('Approved claim support snapshot preserved',lambda:assert_equal(db.execute("SELECT evidence_id,relation,assessment FROM ClaimEvidence WHERE claim_id='a'").fetchall(),[('a','SUPPORTS',None)]))
    def editable_claim():
        db.execute("UPDATE ClaimEvidence SET assessment='draft edit' WHERE claim_id='extra'")
        db.execute("DELETE FROM ClaimEvidence WHERE claim_id='extra'")
        checks(db)
    test('Unapproved claim support remains editable',editable_claim)
    fails('Analysis rejects unknown execution status',lambda:db.execute("UPDATE AnalysisResult SET status='UNKNOWN' WHERE analysis_id='a'"))
    fails('Analysis rejects unknown validation status',lambda:db.execute("UPDATE AnalysisResult SET validation_status='UNKNOWN' WHERE analysis_id='a'"))
    def completed_invalid():
        db.execute('SAVEPOINT analysis_status')
        try:
            db.execute("UPDATE AnalysisResult SET status='COMPLETED',validation_status='INVALID' WHERE analysis_id='a'")
            assert db.execute("SELECT status,validation_status FROM AnalysisResult WHERE analysis_id='a'").fetchone()==('COMPLETED','INVALID')
        finally:db.execute('ROLLBACK TO analysis_status');db.execute('RELEASE analysis_status')
    test('Completed execution can have invalid output',completed_invalid)
    def refused_fresh(name,prepare):
        def run():
            fresh=connect()
            try:
                prepare(fresh)
                before=schema_shape(fresh)
                try:migrate(fresh)
                except ValueError:pass
                else:raise AssertionError('Unsafe initial migration accepted')
                assert schema_shape(fresh)==before
                assert not fresh.in_transaction
            finally:fresh.close()
        test(name,run)
    refused_fresh('Unmanaged table is preserved and refused',lambda d:d.execute('CREATE TABLE user_data(x TEXT)'))
    refused_fresh('Nonzero marker without history is refused',lambda d:d.execute('PRAGMA user_version=7'))
    refused_fresh('Foreign keys disabled is refused',lambda d:d.execute('PRAGMA foreign_keys=OFF'))
    refused_fresh('Recursive triggers disabled is refused',lambda d:d.execute('PRAGMA recursive_triggers=OFF'))
    def refused_existing(name,mutate):
        def run():
            fresh=connect()
            try:
                migrate(fresh);mutate(fresh);before=schema_shape(fresh)
                try:migrate(fresh)
                except ValueError:pass
                else:raise AssertionError('Altered database accepted')
                assert schema_shape(fresh)==before
                assert not fresh.in_transaction
            finally:fresh.close()
        test(name,run)
    refused_existing('Missing audit trigger is detected',lambda d:d.execute('DROP TRIGGER trg_AuditEvent_update'))
    refused_existing('Unexpected schema table is detected',lambda d:d.execute('CREATE TABLE unexpected(x TEXT)'))
    refused_existing('Future migration history is refused by bootstrap runner',lambda d:d.execute("INSERT INTO SchemaMigration SELECT '0002',2,'0002.sql',checksum,applied_at,0,applied_by,core_version,NULL,NULL FROM SchemaMigration WHERE version=1"))
    def backup_restore():
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);live=connect(root/'live.db');migrate(live)
            live.execute("INSERT INTO Project(project_id,project_key,name,status,created_at,updated_at) VALUES ('backup-p','backup-p','Backup project','ACTIVE',?,?)",(NOW,NOW))
            backup=connect(root/'backup.db');live.backup(backup);backup.close();live.close()
            restored=connect(root/'backup.db')
            try:
                checks(restored);assert migrate(restored) is False
                assert restored.execute("SELECT name FROM Project WHERE project_id='backup-p'").fetchone()==('Backup project',)
            finally:restored.close()
    test('Consistent SQLite backup reopens with data and migration history',backup_restore)
    def writer_contention():
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'lock.db';first=connect(path);migrate(first);second=connect(path)
            second.execute('PRAGMA busy_timeout=1');first.execute('BEGIN IMMEDIATE')
            try:
                try:migrate(second)
                except sqlite3.OperationalError as e:
                    assert 'locked' in str(e)
                else:raise AssertionError('Competing write lock unexpectedly acquired')
            finally:first.rollback()
            assert migrate(second) is False;first.close();second.close()
    test('Competing writer fails cleanly and retry succeeds',writer_contention)
    insert('ApprovalRequest',approval_id='expiry',resource_type='TEST',resource_id='expiry-target',action='REVIEW',status='PENDING',requested_by='system',expires_at='2026-11-09T00:01:00.000Z')
    fails('Decision at exact expiry is rejected',lambda:insert('ApprovalDecision',decision_id='late',approval_id='expiry',decided_by='system',decision='APPROVE',decided_at='2026-11-09T00:01:00.000Z'))
    fails('Decision before request time is rejected',lambda:insert('ApprovalDecision',decision_id='early',approval_id='expiry',decided_by='system',decision='APPROVE',decided_at='2026-11-08T23:59:59.999Z'))
    fails('Approval target hash mutation is rejected',lambda:db.execute("UPDATE ApprovalRequest SET resource_hash='new' WHERE approval_id='expiry'"))
    fails('Approval policy mutation is rejected',lambda:db.execute("UPDATE ApprovalRequest SET policy_version_ref='new' WHERE approval_id='expiry'"))
    fails('Direct changes-requested without decision is rejected',lambda:db.execute("UPDATE ApprovalRequest SET status='CHANGES_REQUESTED',resolved_at=? WHERE approval_id='expiry'",(NOW,)))
    db.execute("UPDATE ApprovalRequest SET status='CANCELLED',resolved_at=? WHERE approval_id='expiry'",(NOW,))
    fails('Cancelled request cannot receive approval',lambda:insert('ApprovalDecision',decision_id='cancelled',approval_id='expiry',decided_by='system',decision='APPROVE'))
    fails('Evidence invalid JSON locator is rejected',lambda:insert('Evidence',evidence_id='bad-json',space_id='a',source_type='USER_INPUT',locator='{bad'))
    fails('Policy invalid JSON is rejected',lambda:insert('AccessPolicy',policy_id='bad-json',policy_key='bad-json',policy_type='REQUIRE_APPROVAL',effect='DENY',parameters='{bad',created_by='system'))
    fails('Negative model token count is rejected',lambda:insert('ModelInvocation',invocation_id='negative',execution_id='a',input_tokens=-1))
    fails('Invalid retryable boolean is rejected',lambda:insert('ErrorRecord',error_id='bad-bool',execution_id='a',retryable=2))
    fails('Execution self dependency is rejected',lambda:insert('ExecutionStepDependency',execution_id='a',step_id='a',depends_on_step_id='a'))
    def crash_before_commit(journal):
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'crash.db'
            code="""import importlib.util,sys,os
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
db=m.connect(sys.argv[2]);db.execute('PRAGMA journal_mode='+sys.argv[3]);db.execute('BEGIN IMMEDIATE')
for st in m.statements(m.SQL.read_text()):db.execute(st)
db.execute('PRAGMA user_version=1')
os._exit(17)
"""
            result=subprocess.run([sys.executable,'-c',code,str(pathlib.Path(__file__).resolve()),str(path),journal],capture_output=True,text=True,timeout=20)
            assert result.returncode==17,result.stderr
            reopened=connect(path)
            try:
                assert schema_shape(reopened)==[]
                assert reopened.execute('PRAGMA user_version').fetchone()==(0,)
                assert migrate(reopened) is True
                checks(reopened)
            finally:reopened.close()
    test('Process exit before commit rolls back DELETE journal and permits retry',lambda:crash_before_commit('DELETE'))
    test('Process exit before commit rolls back WAL journal and permits retry',lambda:crash_before_commit('WAL'))
    refused_fresh('sqliteX user table cannot evade unmanaged-schema check',lambda d:d.execute('CREATE TABLE sqliteXpayload(value TEXT)'))
    refused_existing('sqliteX added table cannot evade schema drift check',lambda d:d.execute('CREATE TABLE sqliteXpayload(value TEXT)'))
    for final_state in ['COMPLETED','FAILED','CANCELLED']:
        aid='final-'+final_state
        insert('AnalysisResult',analysis_id=aid,execution_id='a',analysis_method='CODE',status=final_state)
        def no_terminal_change(name,fn):
            def guarded():
                try:fn()
                except sqlite3.IntegrityError as e:
                    if 'Terminal analysis' not in str(e) and 'Final analysis is immutable' not in str(e):raise AssertionError(str(e))
                    raise
            fails(name,guarded)
        no_terminal_change(final_state+' analysis deletion blocked',lambda aid=aid:db.execute('DELETE FROM AnalysisResult WHERE analysis_id=?',(aid,)))
        no_terminal_change(final_state+' analysis update blocked',lambda aid=aid:db.execute('UPDATE AnalysisResult SET processor=? WHERE analysis_id=?',('rewritten',aid)))
        no_terminal_change(final_state+' analysis REPLACE blocked',lambda aid=aid:db.execute('INSERT OR REPLACE INTO AnalysisResult SELECT * FROM AnalysisResult WHERE analysis_id=?',(aid,)))
    insert('AnalysisResult',analysis_id='snapshot',execution_id='a',analysis_method='CODE',status='RUNNING')
    insert('AnalysisResult',analysis_id='editable-analysis',execution_id='a',analysis_method='CODE',status='RUNNING')
    descriptors=[
        ('AnalysisInput',dict(analysis_input_id='snapshot-input',input_type='USER_INPUT'),dict(analysis_input_id='extra-input',input_type='USER_INPUT'),'input_ref'),
        ('AnalysisOutput',dict(output_id='snapshot-output'),dict(output_id='extra-output'),'content_ref'),
        ('AnalysisEvidence',dict(evidence_id='a'),dict(evidence_id='extra'),'usage_role'),
        ('AnalysisClaim',dict(claim_id='a',relation_type='EVALUATED'),dict(claim_id='extra',relation_type='EVALUATED'),'relation_type')]
    for table,existing,new_values,field in descriptors:
        insert(table,analysis_id='snapshot',**existing)
        insert(table,analysis_id='editable-analysis',**new_values)
    db.execute("UPDATE AnalysisResult SET status='COMPLETED' WHERE analysis_id='snapshot'")
    for table,existing,new_values,field in descriptors:
        no_terminal_change(table+' insertion after completion blocked',lambda t=table,v=new_values:insert(t,analysis_id='snapshot',**v))
        # Same-value updates must still not reassign or rewrite a closed snapshot.
        no_terminal_change(table+' update after completion blocked',lambda t=table,f=field:db.execute(f"UPDATE {t} SET {f}={f} WHERE analysis_id='snapshot'"))
        no_terminal_change(table+' deletion after completion blocked',lambda t=table:db.execute(f"DELETE FROM {t} WHERE analysis_id='snapshot'"))
        no_terminal_change(table+' move out of terminal analysis blocked',lambda t=table:db.execute(f"UPDATE {t} SET analysis_id='editable-analysis' WHERE analysis_id='snapshot'"))
        no_terminal_change(table+' move into terminal analysis blocked',lambda t=table:db.execute(f"UPDATE {t} SET analysis_id='snapshot' WHERE analysis_id='editable-analysis'"))
        no_terminal_change(table+' REPLACE after completion blocked',lambda t=table:db.execute(f"INSERT OR REPLACE INTO {t} SELECT * FROM {t} WHERE analysis_id='snapshot'"))
        test(table+' failed mutations preserve snapshot count',lambda t=table:assert_equal(db.execute(f"SELECT count(*) FROM {t} WHERE analysis_id='snapshot'").fetchone(),(1,)))
    def exact_file_bytes():
        global SQL
        original_sql=SQL
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'0001_initial_schema.sql'
            raw=original_sql.read_bytes().replace(b'\n',b'\r\n')
            path.write_bytes(raw);SQL=path;fresh=connect()
            try:
                migrate(fresh)
                assert fresh.execute('SELECT checksum FROM SchemaMigration').fetchone()==(hashlib.sha256(raw).hexdigest(),)
                assert migrate(fresh) is False
                path.write_bytes(raw.replace(b'\r\n',b'\n'))
                try:migrate(fresh)
                except ValueError as e:assert 'checksum' in str(e).lower()
                else:raise AssertionError('Changed file bytes accepted')
            finally:fresh.close();SQL=original_sql
    test('Migration checksum binds exact UTF-8 file bytes including CRLF',exact_file_bytes)
    test('Final integrity_check and foreign_key_check',lambda:checks(db))
    db.close()

def assert_equal(a,b):
    assert a==b,(a,b)

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=pathlib.Path);p.add_argument('--report',type=pathlib.Path);args=p.parse_args()
    if args.database:
        db=connect(args.database)
        try:print('Applied' if migrate(db) else 'Already applied (checksum verified)')
        finally:db.close()
        return
    suite()
    report={'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'migration_sha256':hashlib.sha256(SQL.read_bytes()).hexdigest(),'results':RESULTS}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(RESULTS)} tests passed; integrity_check=ok; foreign_key_check=[]')
if __name__=='__main__':main()
