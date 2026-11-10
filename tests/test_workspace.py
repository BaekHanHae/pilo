from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from pilo_core import Core,AccessDenied,ConfigurationError
from pilo_core.migrations import upgrade
from pilo_core.workspace import Workspace

ROOT=Path(__file__).resolve().parents[1]
PERMISSIONS=('project.create','project.read','project.list','files.scan','context.read','common.read','knowledge.write','knowledge.approve','checkpoint.create','checkpoint.read','recovery.run','index.rebuild','skill.approve','code.run','execution.run','execution.read','diagnostics.run','diagnostics.read','error.write','error.read','model.record','approval.request','approval.decide','knowledge.promote','common.write','memory.read','memory.write')

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.project=self.root/'project';self.project.mkdir();(self.project/'readme.md').write_text('PILO 검색 문맥 스냅샷\n日本語の検索と復元\nretrieval context atomic snapshot')
        for args in [('init','-q'),('config','user.name','PILO Test'),('config','user.email','pilo@example.invalid'),('add','.'),('commit','-qm','fixture')]:subprocess.run(['git','-C',str(self.project),*args],check=True,capture_output=True)
        from pilo_core.bootstrap import initialize
        initialize(self.root/'instance',upgrade_workspace=False)
        self.db=self.root/'instance/data/pilo.sqlite3';self.config=self.root/'instance/database_config.json'
        upgrade(self.config);self.core=Workspace(self.config)
        with self.dbconn() as db:
            for permission in PERMISSIONS:
                db.execute('INSERT INTO Permission VALUES(?,?,?,?)',(permission,permission,'test','t'))
                role=db.execute("SELECT role_id FROM PrincipalRole WHERE principal_id='system'").fetchone()[0];db.execute('INSERT INTO RolePermission VALUES(?,?)',(role,permission))
            db.execute("INSERT INTO Principal VALUES('reviewer','USER','reviewer','reviewer','ACTIVE','t','t')")
            db.execute("INSERT INTO PrincipalRole VALUES('reviewer','reviewer',?,'SYSTEM',NULL,'t',NULL)",(role,))
        self.p=self.core.create_project('system','one','One',self.project)['project_id']
    @contextmanager
    def dbconn(self):
        c=sqlite3.connect(self.db);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA recursive_triggers=ON')
        try:
            with c:yield c
        finally:c.close()
    def scan(self):return self.core.scan('system',self.p)
    def retrieve(self,query='snapshot',**kw):return self.core.retrieve('system',self.p,query,**kw)
    def execution(self):return self.core.create_plan('system',self.p,[{'key':'a','skill_id':'text.count','input':{'text':'hello world'}}])
    def test_upgrade_backup_and_idempotence(self):
        self.assertTrue(self.db.with_name(self.db.name+'.pre-0002.backup').exists());self.assertEqual(upgrade(self.config)['schema_version'],2)
        self.assertEqual(self.core.health()['status'],'ok')
        with self.dbconn() as db:self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_end_to_end(self):
        self.scan();snapshot=self.retrieve();self.assertIn('atomic snapshot',snapshot['content'])
        self.core.register_skill('system','text.count');execution=self.core.create_plan('system',self.p,[{'key':'count','skill_id':'text.count','snapshot_id':snapshot['snapshot_id']}])
        self.assertTrue(self.core.scheduler_tick('system',execution)['claimed']);self.core.scheduler_tick('system',execution)
        self.assertEqual(self.core.execution_detail('system',execution)['status'],'COMPLETED')
        checkpoint=self.core.create_checkpoint('system',self.p);self.assertTrue(self.core.verify_checkpoint('system',checkpoint['checkpoint_id']))
        self.assertEqual(self.core.recover('system',checkpoint['checkpoint_id'])['status'],'COMPLETED')
    def test_incremental_revision_snapshot_preserved(self):
        self.scan();first=self.retrieve();(self.project/'readme.md').write_text('newunique content');self.scan()
        self.assertEqual(self.retrieve()['status'],'PARTIAL');self.assertEqual(self.core.snapshot('system',first['snapshot_id'])['content'],first['content'])
        self.assertIn('newunique',self.retrieve('newunique')['content'])
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT count(*) FROM FileRevision').fetchone()[0],2)
    def test_deleted_and_secret_files_excluded(self):
        self.scan();(self.project/'readme.md').unlink();(self.project/'secret.txt').write_text('api_key=abcdefghijklmnop');self.scan()
        self.assertEqual(self.retrieve()['status'],'PARTIAL');self.assertNotIn('abcdefghijklmnop',self.retrieve('api_key')['content'])
    def test_symlink_containment(self):
        outside=self.root/'outside.txt';outside.write_text('privateunique');(self.project/'leak.md').symlink_to(outside)
        self.assertIn('leak.md',self.scan()['excluded']);self.assertNotIn('privateunique',self.retrieve('privateunique')['content'])
    def test_cjk_and_short_query(self):
        self.scan()
        for query in ('검색 문맥','日本語','検索','PILO'):self.assertIn('PILO',self.retrieve(query)['content'])
    def test_cache_generation_and_current_permission(self):
        self.scan();self.assertFalse(self.retrieve()['cache_hit']);self.assertTrue(self.retrieve()['cache_hit'])
        old=self.retrieve();(self.project/'readme.md').write_text('new snapshot');self.scan();self.assertFalse(self.retrieve()['cache_hit'])
        with self.dbconn() as db:db.execute("UPDATE Principal SET status='DISABLED' WHERE principal_id='system'")
        with self.assertRaises(AccessDenied):self.core.snapshot('system',old['snapshot_id'])
    def test_idempotency_and_request_conflict(self):
        self.scan();first=self.retrieve(idempotency_key='key');second=self.retrieve(idempotency_key='key',execution_id=first['execution_id']);self.assertEqual(first['snapshot_id'],second['snapshot_id'])
        with self.assertRaises(ValueError):self.retrieve('other',idempotency_key='key',execution_id=first['execution_id'])
    def test_space_isolation(self):
        other=self.root/'other';other.mkdir();p2=self.core.create_project('system','two','Two',other)['project_id']
        with self.dbconn() as db:
            db.execute("INSERT INTO Principal VALUES('limited','USER','limited','Limited','ACTIVE','t','t')")
            db.execute("INSERT INTO Role VALUES('limited','limited','Limited',NULL,'t')")
            db.execute("INSERT INTO PrincipalRole VALUES('limited','limited','limited','PROJECT',?,'t',NULL)",(p2,))
            db.execute("INSERT INTO RolePermission VALUES('limited','context.read')")
        self.scan();snapshot=self.retrieve()
        self.assertEqual(self.core.retrieve('limited',p2,'snapshot')['content'],'')
        with self.assertRaises(AccessDenied):self.core.snapshot('limited',snapshot['snapshot_id'])
    def test_snapshot_atomic_failure_and_corruption(self):
        self.scan()
        with patch.object(self.core,'_audit_change',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):self.retrieve()
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT count(*) FROM ContextSnapshot').fetchone()[0],0)
        snapshot=self.retrieve()
        with self.dbconn() as db:ref=db.execute('SELECT content_ref FROM ContextSnapshot WHERE snapshot_id=?',(snapshot['snapshot_id'],)).fetchone()[0]
        (self.core.store.root/ref).write_bytes(b'corrupt')
        with self.assertRaises(ConfigurationError):self.core.snapshot('system',snapshot['snapshot_id'])
    def test_mandatory_knowledge_budget(self):
        result=self.core.save_knowledge('system',self.p,'Must keep','mandatory rule '*20,'RULE');self.core.activate_knowledge('system',result['version_id'])
        with self.assertRaises(ValueError):self.retrieve(max_tokens=5)
        self.assertIn('mandatory rule',self.retrieve()['content'])
    def test_fts_rollback_generation(self):
        self.scan()
        with self.dbconn() as db:before=db.execute('SELECT * FROM SpaceGeneration').fetchall()
        (self.project/'readme.md').write_text('changed unique')
        with patch.object(self.core,'_audit_change',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.scan()
        with self.dbconn() as db:self.assertEqual(before,db.execute('SELECT * FROM SpaceGeneration').fetchall())
        self.assertIn('atomic snapshot',self.retrieve()['content'])
    def test_cycle_rejected_by_service_and_database(self):
        self.core.register_skill('system','text.count')
        with self.assertRaises(ValueError):self.core.create_plan('system',self.p,[{'key':'a','skill_id':'text.count','input':{'text':'a'},'depends_on':['b']},{'key':'b','skill_id':'text.count','input':{'text':'a'},'depends_on':['a']}])
        with self.core.connection(write=True) as db:
            ex=self.core._execution(db,'system',self.p,'TEST')
            for n in (1,2):db.execute('INSERT INTO ExecutionStep(step_id,execution_id,step_number,step_key,step_type,name) VALUES(?,?,?,?,?,?)',(str(n),ex,n,str(n),'TEST','test'))
            db.execute('INSERT INTO ExecutionStepDependency VALUES(?,?,?)',(ex,'1','2'))
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO ExecutionStepDependency VALUES(?,?,?)',(ex,'2','1'))
    def test_plan_hash_and_terminal_transition(self):
        self.core.register_skill('system','text.count');execution=self.execution();self.core.scheduler_tick('system',execution)
        with self.dbconn() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE ExecutionStep SET status='PENDING' WHERE execution_id=?",(execution,))
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE ExecutionPlan SET definition='[]'")
    def test_skill_integrity_and_unknown_entrypoint(self):
        with self.assertRaises(ValueError):self.core.register_skill('system','os.system')
        self.core.register_skill('system','text.count');execution=self.execution()
        with patch('pilo_core.execution.implementation_hash',return_value='changed'):
            with self.assertRaises(AccessDenied):self.core.scheduler_tick('system',execution)
    def test_dependency_order_and_cancel(self):
        self.core.register_skill('system','text.count');execution=self.core.create_plan('system',self.p,[{'key':'b','skill_id':'text.count','input':{'text':'b'},'depends_on':['a']},{'key':'a','skill_id':'text.count','input':{'text':'a'}}])
        self.core.scheduler_tick('system',execution);detail=self.core.execution_detail('system',execution)
        self.assertEqual(detail['steps'][0]['queue_state'],'BLOCKED');self.assertEqual(detail['steps'][1]['status'],'COMPLETED')
        self.core.cancel_execution('system',execution);self.assertEqual(self.core.scheduler_tick('system',execution)['status'],'CANCELLED')
    def test_timeout_retry_attempt_history(self):
        self.core.register_skill('system','text.count');execution=self.execution()
        with patch('pilo_core.execution.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',1)):
            self.assertEqual(self.core.scheduler_tick('system',execution)['status'],'READY')
        with self.dbconn() as db:db.execute('UPDATE StepScheduling SET next_attempt_at=0')
        self.core.scheduler_tick('system',execution)
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT count(*) FROM StepAttempt').fetchone()[0],2)
    def test_stale_result_fencing(self):
        self.core.register_skill('system','text.count');execution=self.execution()
        from pilo_core import execution as module
        original=module.subprocess.run
        def expired(*a,**kw):
            with self.dbconn() as db:db.execute('UPDATE StepScheduling SET lease_expires_at=0')
            return original(*a,**kw)
        with patch('pilo_core.execution.subprocess.run',side_effect=expired):
            with self.assertRaises(ConfigurationError):self.core.scheduler_tick('system',execution)
        with self.dbconn() as db:self.assertIsNone(db.execute('SELECT output_ref FROM ExecutionStep').fetchone()[0])
        self.assertEqual(self.core.scheduler_tick('system',execution)['status'],'COMPLETED')
    def test_policy_deny_and_approval_context(self):
        with self.dbconn() as db:db.execute("INSERT INTO AccessPolicy VALUES('p','p','REQUIRE_APPROVAL','REQUIRE_APPROVAL',?,'ACTIVE',0,'system','t','t')",(json.dumps({'actions':['knowledge.write']}),))
        text='approved text';resource={'title':'Title','hash':hashlib.sha256(text.encode()).hexdigest(),'kind':'REFERENCE'}
        with self.assertRaises(AccessDenied):self.core.save_knowledge('system',self.p,'Title',text)
        approval=self.core.request_approval('system','knowledge.write',self.p,resource)
        with self.assertRaises(AccessDenied):self.core.decide_approval('system',approval)
        self.core.decide_approval('reviewer',approval)
        self.core.save_knowledge('system',self.p,'Title',text,approval=approval)
        with self.assertRaises(AccessDenied):self.core.save_knowledge('system',self.p,'Title','changed',approval=approval)
        self.core.revoke_approval('reviewer',approval)
        with self.assertRaises(AccessDenied):self.core.save_knowledge('system',self.p,'Title',text,approval=approval)
    def test_checkpoint_dirty_missing_bytes_and_replay(self):
        self.scan();snapshot=self.retrieve();cp=self.core.create_checkpoint('system',self.p)
        result=self.core.recover('system',cp['checkpoint_id'],'REPLAY',idempotency_key='replay');self.assertIn(snapshot['snapshot_id'],result['verification']['snapshot_ids'])
        self.assertEqual(result['operation_id'],self.core.recover('system',cp['checkpoint_id'],'REPLAY',idempotency_key='replay')['operation_id'])
        (self.project/'dirty.txt').write_text('dirty')
        with self.assertRaises(ConfigurationError):self.core.create_checkpoint('system',self.p)
        manifest=self.core.verify_checkpoint('system',cp['checkpoint_id']);ref=next(iter(manifest['objects'].values()))['ref'];(self.core.store.root/ref).unlink()
        with self.assertRaises(ConfigurationError):self.core.verify_checkpoint('system',cp['checkpoint_id'])
    def test_rollback_preserves_history(self):
        self.scan();cp=self.core.create_checkpoint('system',self.p);(self.project/'readme.md').write_text('new state')
        subprocess.run(['git','-C',str(self.project),'commit','-am','second','-q'],check=True);self.scan()
        resource=self.core.recovery_context('system',cp['checkpoint_id'],'ROLLBACK');approval=self.core.request_approval('system','recovery.run',self.p,resource);self.core.decide_approval('reviewer',approval)
        result=self.core.recover('system',cp['checkpoint_id'],'ROLLBACK',approval,idempotency_key='rollback');self.assertEqual(result['status'],'COMPLETED')
        self.assertIn('atomic snapshot',(self.project/'readme.md').read_text());self.assertIn('atomic snapshot',self.retrieve()['content'])
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT count(*) FROM FileRevision').fetchone()[0],2)
    def test_diagnostics_error_redaction_model_link(self):
        self.scan();snapshot=self.retrieve();diagnostic=self.core.diagnostics('system',self.p)
        self.assertEqual(diagnostic['status'],'PASSED')
        error=self.core.record_error('system',self.p,snapshot['execution_id'],'IO','secret=abc123456 path /Users/alice/private.txt line 22',{'secret':'bad','python':'3.15'})
        cases=self.core.error_cases('system',self.p);self.assertNotIn('abc123456',str(cases));self.assertNotIn('alice',str(cases))
        self.core.save_resolution('system',error['case_id'],'Fix',diagnostic['run_id'])
        self.core.record_model_invocation('system',self.p,snapshot['snapshot_id'],'fixture','fixture',10,5,'0.001')
        self.assertEqual(self.core.metrics('system',self.p)['model_cost'],'0.001')
    def test_migration_config_crash_reconciliation(self):
        config=json.loads(self.config.read_text());config['schema_version']=1;self.config.write_text(json.dumps(config))
        self.assertEqual(upgrade(self.config)['schema_version'],2)


    def test_promotion_independent_approval_and_private_lineage(self):
        draft=self.core.save_knowledge('system',self.p,'Shared','path /Users/alice/private.txt secret=longsecret')
        self.core.add_evidence('system',draft['version_id'],'redacted supporting evidence')
        self.core.activate_knowledge('system',draft['version_id'])
        request=self.core.request_promotion('system',draft['version_id'],'promote-key')
        with self.assertRaises(AccessDenied):self.core.apply_promotion('system',request['promotion_id'])
        self.core.decide_approval('reviewer',request['approval_id'])
        target=self.core.apply_promotion('system',request['promotion_id'])
        self.assertEqual(target,self.core.apply_promotion('system',request['promotion_id']))
        result=self.retrieve('LOCAL_PATH');self.assertIn('[REDACTED]',result['content'])
        with self.dbconn() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM EvidenceLineage').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM KnowledgeLineage').fetchone()[0],1)
            db.execute("INSERT INTO Principal VALUES('common-user','USER','common-user','Common','ACTIVE','t','t')")
            db.execute("INSERT INTO Role VALUES('common-role','common-role','Common',NULL,'t')")
            db.execute("INSERT INTO PrincipalRole VALUES('common-role','common-user','common-role','SYSTEM',NULL,'t',NULL)")
            db.execute("INSERT INTO RolePermission VALUES('common-role','common.read')")
        self.assertEqual(self.core.lineage('common-user',target['version_id']),[])
    def test_snapshot_children_are_sealed(self):
        self.scan();snapshot=self.retrieve()
        with self.dbconn() as db:
            unit,space,content_hash=db.execute('SELECT unit_id,space_id,content_hash FROM ContentUnit LIMIT 1').fetchone()
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO ContextSnapshotItem VALUES(?,?,?,?,?)',(snapshot['snapshot_id'],999,space,unit,content_hash))
    def test_rebuild_own_space_only(self):
        self.scan()
        with self.dbconn() as db:db.execute("UPDATE SpaceGeneration SET source_generation=3,indexed_generation=2 WHERE space_id='common'")
        self.core.rebuild_index('system',self.p)
        with self.dbconn() as db:self.assertEqual(db.execute("SELECT source_generation,indexed_generation FROM SpaceGeneration WHERE space_id='common'").fetchone(),(3,2))
    def test_recovery_lock_denies_scan(self):
        with self.dbconn() as db:db.execute('INSERT INTO RecoveryLease VALUES(?,?,1,?)',(self.p,'other',time.time()+60))
        with self.assertRaises(AccessDenied):self.scan()
    def test_model_snapshot_execution_fk(self):
        self.scan();snapshot=self.retrieve()
        with self.core.connection(write=True) as db:
            other=self.core._execution(db,'system',self.p,'TEST')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("INSERT INTO ModelInvocation(invocation_id,execution_id,model_provider,model_name,status,created_at,context_snapshot_id) VALUES('bad',?,'p','m','COMPLETED','t',?)",(other,snapshot['snapshot_id']))
    def test_mcp_modern_legacy_identity_and_disabled_writes(self):
        from pilo_core.mcp_server import Server,ProtocolError,META,MODERN,LEGACY,SUPPORTED_VERSIONS
        self.core.config['mcp_principal']='system';server=Server(self.core)
        meta={META+'protocolVersion':MODERN,META+'clientCapabilities':{}}
        def request(method,params=None):return server.dispatch({'jsonrpc':'2.0','id':1,'method':method,'params':dict(params or {},_meta=meta)})
        self.assertEqual(request('server/discover')['supportedVersions'],SUPPORTED_VERSIONS)
        tools=request('tools/list');self.assertTrue(tools['tools'])
        self.assertTrue(request('tools/call',{'name':'pilo_scan_project','arguments':{'project_id':self.p}})['isError'])
        with self.assertRaises(ProtocolError):request('tools/call',{'name':'pilo_get_project','arguments':{'project_id':self.p,'actor':'reviewer'}})
        self.assertFalse(request('tools/call',{'name':'pilo_get_project','arguments':{'project_id':self.p}})['isError'])
        self.assertIn('contents',request('resources/read',{'uri':'pilo://project/'+self.p}))
        self.assertIn('messages',request('prompts/get',{'name':'pilo-start-task','arguments':{'project_id':self.p}}))
        self.assertEqual(server.dispatch({'jsonrpc':'2.0','id':2,'method':'initialize','params':{'protocolVersion':LEGACY}})['protocolVersion'],LEGACY)
    def test_mcp_real_subprocess_protocol(self):
        config=json.loads(self.config.read_text());config['mcp_principal']='system';self.config.write_text(json.dumps(config))
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'pilo_get_project','arguments':{'project_id':self.p}}}]
        result=subprocess.run([os.sys.executable,'-m','pilo_core.mcp_server','--config',str(self.config)],input='\n'.join(json.dumps(x) for x in requests)+'\n',text=True,capture_output=True,cwd=ROOT,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);responses=[json.loads(x) for x in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in responses],[1,2,3]);self.assertEqual(responses[-1]['result']['structuredContent']['project_id'],self.p)
    def test_migration_failure_rolls_back(self):
        # Reproduce a preflight failure against a clean version-1 backup, never production.
        from pilo_core.bootstrap import initialize
        initialize(self.root/'bad-instance',upgrade_workspace=False)
        path=self.root/'bad-instance/data/pilo.sqlite3';out=sqlite3.connect(path)
        out.execute('CREATE TABLE unmanaged(value TEXT)');out.commit();out.close()
        config=json.loads(self.config.read_text());config.update(database_path=str(path),schema_version=1);c=self.root/'bad.json';c.write_text(json.dumps(config))
        with self.assertRaises(ConfigurationError):upgrade(c)
        connection=sqlite3.connect(path)
        try:self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],1)
        finally:connection.close()


    def test_process_exit_snapshot_rollback_and_retry(self):
        self.scan()
        code="""import os,sys
from pilo_core.workspace import Workspace
w=Workspace(sys.argv[1])
def stop(*args,**kwargs):os._exit(17)
w._audit_change=stop
w.retrieve('system',sys.argv[2],'snapshot',idempotency_key='crash')
"""
        result=subprocess.run([os.sys.executable,'-c',code,str(self.config),self.p],cwd=ROOT,timeout=10,capture_output=True)
        self.assertEqual(result.returncode,17)
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT count(*) FROM ContextSnapshot').fetchone()[0],0)
        self.assertIn('atomic snapshot',self.retrieve(idempotency_key='crash')['content'])
    def test_concurrent_same_idempotency_key(self):
        self.scan()
        with self.core.connection(write=True) as db:execution=self.core._execution(db,'system',self.p,'CONCURRENT')
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.core.retrieve('system',self.p,'snapshot',execution_id=execution,idempotency_key='same'),range(2)))
        self.assertEqual(results[0]['snapshot_id'],results[1]['snapshot_id'])
    def test_recovery_interruption_reconciles_without_db_rewind(self):
        self.scan();checkpoint=self.core.create_checkpoint('system',self.p)
        (self.project/'readme.md').write_text('second clean state')
        subprocess.run(['git','-C',str(self.project),'commit','-am','second','-q'],check=True);self.scan()
        def approve():
            context=self.core.recovery_context('system',checkpoint['checkpoint_id'],'ROLLBACK')
            approval=self.core.request_approval('system','recovery.run',self.p,context);self.core.decide_approval('reviewer',approval);return approval
        approval=approve()
        with patch.object(self.core,'_reindex_space',side_effect=RuntimeError('interrupted after Git')):
            with self.assertRaises(RuntimeError):self.core.recover('system',checkpoint['checkpoint_id'],'ROLLBACK',approval,idempotency_key='recover-interrupted')
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT status FROM RecoveryOperation').fetchone()[0],'INTERRUPTED')
        result=self.core.recover('system',checkpoint['checkpoint_id'],'ROLLBACK',approve(),idempotency_key='recover-interrupted')
        self.assertEqual(result['status'],'COMPLETED');self.assertIn('atomic snapshot',self.retrieve()['content'])
    def test_stale_generation_fails_closed(self):
        self.scan()
        with self.dbconn() as db:db.execute('UPDATE SpaceGeneration SET source_generation=source_generation+1')
        with self.assertRaises(ConfigurationError):self.retrieve()
        self.core.rebuild_index('system',self.p)
        # COMMON remains stale and is independently authorized, so the combined scope still refuses.
        with self.assertRaises(ConfigurationError):self.retrieve()
    def test_approval_expiry_and_authority_revocation(self):
        with self.dbconn() as db:db.execute("INSERT INTO AccessPolicy VALUES('approve','approve','REQUIRE_APPROVAL','REQUIRE_APPROVAL',?,'ACTIVE',0,'system','t','t')",(json.dumps({'actions':['knowledge.write']}),))
        text='text';resource={'title':'T','hash':hashlib.sha256(text.encode()).hexdigest(),'kind':'REFERENCE'}
        approval=self.core.request_approval('system','knowledge.write',self.p,resource);self.core.decide_approval('reviewer',approval)
        with patch('pilo_core.security.now',return_value='9999-01-01T00:00:00.000Z'):
            with self.assertRaises(AccessDenied):self.core.save_knowledge('system',self.p,'T',text,approval=approval)
        with self.dbconn() as db:db.execute("UPDATE Principal SET status='DISABLED' WHERE principal_id='reviewer'")
        with self.assertRaises(AccessDenied):self.core.save_knowledge('system',self.p,'T',text,approval=approval)


    def test_memory_typed_reference_and_common_resolution(self):
        self.scan()
        with self.dbconn() as db:resource=db.execute('SELECT resource_id FROM ResourceRegistry LIMIT 1').fetchone()[0]
        memory=self.core.remember('system',self.p,resource,{'task_kind':'debug'})
        self.assertEqual(self.core.memories('system',self.p,'build'),[])
        self.assertEqual(self.core.memories('system',self.p,'debug')[0]['memory_id'],memory)
        draft=self.core.save_knowledge('system',self.p,'Common','common reference content');self.core.activate_knowledge('system',draft['version_id'])
        promotion=self.core.request_promotion('system',draft['version_id'],'reference-promotion');self.core.decide_approval('reviewer',promotion['approval_id']);target=self.core.apply_promotion('system',promotion['promotion_id'])
        with self.dbconn() as db:knowledge=db.execute('SELECT knowledge_id FROM KnowledgeVersion WHERE version_id=?',(target['version_id'],)).fetchone()[0]
        reference=self.core.reference_common('system',self.p,knowledge)
        snapshot=self.retrieve();resolved=self.core.resolve_reference('system',self.p,reference,snapshot['execution_id']);self.assertEqual(resolved['version_id'],target['version_id'])
        with self.assertRaises(AccessDenied):self.core.remember('system',self.p,target['version_id'])
    def test_checkpoint_refuses_stale_scan(self):
        self.scan();(self.project/'readme.md').write_text('committed but not scanned')
        subprocess.run(['git','-C',str(self.project),'commit','-am','stale','-q'],check=True)
        with self.assertRaises(ConfigurationError):self.core.create_checkpoint('system',self.p)
    def test_unknown_policy_fails_closed(self):
        with self.dbconn() as db:db.execute("INSERT INTO AccessPolicy VALUES('bad','bad','PROJECT_ISOLATION','ALLOW',?,'ACTIVE',0,'system','t','t')",(json.dumps({'eval':'arbitrary code'}),))
        with self.assertRaises(AccessDenied):self.scan()


    def test_operator_explicit_project_grant(self):
        from pilo_core.operator import provision
        provision(self.core,'new-reader',['project.read'],self.p)
        self.assertEqual(self.core.get_project('new-reader',self.p)['project_key'],'one')
        with self.assertRaises(AccessDenied):self.core.list_projects('new-reader')
        with self.assertRaises(ValueError):provision(self.core,'other',['*'])
    def test_mcp_cancellation_suppresses_response(self):
        from pilo_core.mcp_server import serve,Server,META,MODERN
        import io
        meta={META+'protocolVersion':MODERN,META+'clientCapabilities':{}}
        requests=[{'jsonrpc':'2.0','id':'cancel-me','method':'tools/call','params':{'_meta':meta,'name':'pilo_get_project','arguments':{'project_id':self.p}}},{'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':'cancel-me'}}]
        original=Server.handle
        def delayed(server,method,params):
            if method=='tools/call':time.sleep(0.05)
            return original(server,method,params)
        output=io.StringIO()
        with patch.object(Server,'handle',delayed):serve(self.config,io.StringIO('\n'.join(json.dumps(r) for r in requests)+'\n'),output)
        self.assertEqual(output.getvalue(),'')


    def test_fresh_installation_is_runnable_and_never_overwrites(self):
        from pilo_core.bootstrap import initialize
        target=self.root/'fresh';self.assertEqual(initialize(target)['schema_version'],2)
        fresh=Workspace(target/'database_config.json')
        with fresh.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Project').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM Permission').fetchone()[0],0)
        with self.assertRaises(FileExistsError):initialize(target)


    def test_budget_accounts_for_assembly_separators(self):
        (self.project/'a.md').write_text('needle');(self.project/'b.md').write_text('needle');self.scan()
        first_piece='[a.md]\nneedle\n';second_piece='[b.md]\nneedle\n';budget=len((first_piece+second_piece).encode())
        result=self.retrieve('needle',max_tokens=budget)
        self.assertLessEqual(len(result['content'].encode()),budget)
        self.assertEqual(result['token_count'],len(result['content'].encode()))
    def test_project_discovery_filters_unauthorized_projects(self):
        from pilo_core.operator import provision
        provision(self.core,'discovery',['project.read'],self.p)
        other=self.root/'other-root';other.mkdir();self.core.create_project('system','other','Other',other)
        projects=self.core.accessible_projects('discovery')['projects']
        self.assertEqual([p['project_id'] for p in projects],[self.p])
        self.assertEqual(self.core.accessible_projects('missing')['projects'],[])


    def test_operator_project_registration_is_idempotent_without_grants(self):
        from pilo_core.operator import register_project
        target=self.root/'registered';target.mkdir()
        first=register_project(self.core,'registered','Registered',target)
        second=register_project(self.core,'registered','Registered',target)
        self.assertEqual(first['project_id'],second['project_id']);self.assertFalse(second['created'])
        with self.assertRaises(ValueError):register_project(self.core,'registered','Wrong',self.project)


    def test_mcp_codex_2025_06_18_negotiation_and_fallback(self):
        from pilo_core.mcp_server import Server,LEGACY
        server=Server(self.core)
        result=server.dispatch({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'codex','version':'test'}}})
        self.assertEqual(result['protocolVersion'],'2025-06-18')
        tools=server.dispatch({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        self.assertIn('pilo_list_projects',[x['name'] for x in tools['tools']])
        offered=Server(self.core).dispatch({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2099-01-01'}})
        self.assertEqual(offered['protocolVersion'],LEGACY)

if __name__=='__main__':unittest.main()
