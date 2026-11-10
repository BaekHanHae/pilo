"""Clean-worktree checkpoints; journaled Git/logical-state recovery, never DB rewind."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from .core import AccessDenied,ConfigurationError,canonical,now
from .security import validate_approval


def git(root,*args):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,timeout=30,env={'PATH':os.defpath,'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1'})
    if result.returncode:raise ConfigurationError('Git preflight/operation failed')
    return result.stdout.strip()

def clean(root):
    if git(root,'status','--porcelain','--untracked-files=all'):raise ConfigurationError('Clean worktree required; preserve or commit changes first')
    return git(root,'rev-parse','HEAD')

def uid():return str(uuid.uuid4())

def hash_json(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

class RecoveryMixin:
    def create_checkpoint(self,actor,project):
        with self.connection() as db:
            self._check(db,actor,'checkpoint.create',project);root,space=self._project(db,project)
        commit=clean(root)
        with self.connection(write=True) as db:
            self._check(db,actor,'checkpoint.create',project)
            # Recheck under the serialized logical-state transaction.
            if clean(root)!=commit:raise ConfigurationError('Git state changed')
            files=db.execute("SELECT file_id,current_revision_id,logical_path FROM FileAsset WHERE space_id=? AND status='ACTIVE' ORDER BY file_id",(space,)).fetchall()
            from .workspace import safe_read
            for file_id,revision,relative in files:
                expected=db.execute('SELECT content_hash FROM FileRevision WHERE revision_id=?',(revision,)).fetchone()[0]
                if hashlib.sha256(safe_read(root,relative)).hexdigest()!=expected:raise ConfigurationError('Checkpoint scan is stale; scan before checkpoint')
            knowledge=db.execute("SELECT knowledge_id,current_version_id FROM KnowledgeItem WHERE space_id=? AND status='ACTIVE' AND current_version_id IS NOT NULL ORDER BY knowledge_id",(space,)).fetchall()
            resources=[r[1] for r in files]+[r[1] for r in knowledge]
            objects={}
            for resource in resources:
                row=db.execute('SELECT content_ref,content_hash FROM ResourceRegistry WHERE resource_id=? AND space_id=?',(resource,space)).fetchone()
                if not row:raise ConfigurationError('Checkpoint resource registry incomplete')
                data=self.store.get(row[0])
                if hashlib.sha256(data).hexdigest()!=row[1]:raise ConfigurationError('Checkpoint resource corrupted')
                objects[resource]={'ref':row[0],'hash':row[1]}
            snapshots=[r[0] for r in db.execute('SELECT s.snapshot_id FROM ContextSnapshot s JOIN RetrievalRun r USING(retrieval_id) WHERE r.project_id=? ORDER BY s.snapshot_id',(project,))]
            manifest={'format':'pilo.checkpoint.v1','project_id':project,'space_id':space,'git_commit':commit,'files':files,'knowledge':knowledge,'objects':objects,'snapshots':snapshots,'schema_version':2,'policy_version':'current-at-use','created_at':now()}
            ref=self.store.put(canonical(manifest).encode());checkpoint=uid()
            db.execute('INSERT INTO Checkpoint VALUES(?,?,?,?,?,?,?)',(checkpoint,project,ref,ref,commit,actor,now()))
            for resource in resources:db.execute('INSERT INTO CheckpointItem VALUES(?,?)',(checkpoint,resource))
            db.execute('INSERT INTO CheckpointSeal VALUES(?)',(checkpoint,))
            self._audit_change(db,actor,'CREATE_CHECKPOINT',project,{'checkpoint_id':checkpoint,'manifest_hash':ref})
            return {'checkpoint_id':checkpoint,'manifest_hash':ref,'git_commit':commit}
    def verify_checkpoint(self,actor,checkpoint):
        with self.connection() as db:
            row=db.execute('SELECT project_id,manifest_ref,manifest_hash,git_commit FROM Checkpoint WHERE checkpoint_id=?',(checkpoint,)).fetchone()
            if not row:raise LookupError('Checkpoint unavailable')
            project,ref,expected,commit=row;self._check(db,actor,'checkpoint.read',project);root,space=self._project(db,project)
            raw=self.store.get(ref)
            if hashlib.sha256(raw).hexdigest()!=expected:raise ConfigurationError('Manifest hash mismatch')
            manifest=json.loads(raw)
            if manifest['project_id']!=project or manifest['space_id']!=space or manifest['git_commit']!=commit:raise ConfigurationError('Manifest identity mismatch')
            git(root,'cat-file','-e',commit+'^{commit}')
            for resource,item in manifest['objects'].items():
                row=db.execute('SELECT content_ref,content_hash FROM ResourceRegistry WHERE resource_id=? AND space_id=?',(resource,space)).fetchone()
                if row!=(item['ref'],item['hash']):raise ConfigurationError('Manifest resource mismatch')
                if hashlib.sha256(self.store.get(item['ref'])).hexdigest()!=item['hash']:raise ConfigurationError('Checkpoint object corrupt')
            for snapshot in manifest['snapshots']:self._snapshot(db,actor,snapshot)
            return manifest
    def recovery_context(self,actor,checkpoint,kind):
        if kind not in ('ROLLBACK','REPLAY','INDEX_ONLY'):raise ValueError('Unsupported recovery kind')
        manifest=self.verify_checkpoint(actor,checkpoint)
        with self.connection() as db:
            project=manifest['project_id'];self._check(db,actor,'recovery.run',project);root,_=self._project(db,project)
            return {'checkpoint_id':checkpoint,'manifest_hash':hash_json(manifest),'kind':kind,'current_git':clean(root)}
    def recover(self,actor,checkpoint,kind='INDEX_ONLY',approval=None,idempotency_key=None):
        manifest=self.verify_checkpoint(actor,checkpoint);project=manifest['project_id'];key=idempotency_key or uid();plan_hash=hash_json([checkpoint,kind,manifest])
        if kind not in ('ROLLBACK','REPLAY','INDEX_ONLY'):raise ValueError('Unsupported recovery kind')
        with self.connection() as db:
            self._check(db,actor,'recovery.run',project);root,_=self._project(db,project)
            prior=db.execute('SELECT operation_id,plan_hash,status FROM RecoveryOperation WHERE project_id=? AND idempotency_key=?',(project,key)).fetchone()
            if prior and prior[1]!=plan_hash:raise ValueError('Recovery idempotency conflict')
            if prior and prior[2]=='COMPLETED':return {'operation_id':prior[0],'status':'COMPLETED'}
        lockpath=self.path.parent/('recovery-'+hashlib.sha256(project.encode()).hexdigest()+'.lock')
        with lockpath.open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise ConfigurationError('Recovery already running') from exc
            owner=uid();operation=prior[0] if prior else uid();clock=time.time();current=clean(root)
            resource={'checkpoint_id':checkpoint,'manifest_hash':hash_json(manifest),'kind':kind,'current_git':current}
            with self.connection(write=True) as db:
                self._check(db,actor,'recovery.run',project,approval,resource)
                if kind=='ROLLBACK':validate_approval(db,actor,'recovery.run',project,approval,resource)
                lease=db.execute('SELECT lease_expires_at FROM RecoveryLease WHERE project_id=?',(project,)).fetchone()
                if lease and lease[0]>clock:raise ConfigurationError('Recovery lease remains active')
                db.execute('INSERT INTO RecoveryLease VALUES(?,?,1,?) ON CONFLICT(project_id) DO UPDATE SET lease_owner=excluded.lease_owner,fencing_token=RecoveryLease.fencing_token+1,lease_expires_at=excluded.lease_expires_at',(project,owner,clock+120))
                token=db.execute('SELECT fencing_token FROM RecoveryLease WHERE project_id=?',(project,)).fetchone()[0]
                if not prior:
                    execution=self._execution(db,actor,project,'RECOVERY')
                    db.execute("INSERT INTO RecoveryOperation VALUES(?,?,?,?,?,?,'READY','PREFLIGHT',?,?)",(operation,project,checkpoint,execution,kind,plan_hash,key,now()))
                else:db.execute("UPDATE RecoveryOperation SET status='RECONCILING' WHERE operation_id=?",(operation,))
                db.execute("UPDATE RecoveryOperation SET status='RUNNING',phase='APPLY' WHERE operation_id=?",(operation,))
                self._audit_change(db,actor,'BEGIN_RECOVERY',project,{'operation_id':operation,'fencing_token':token})
            try:
                safety=None
                if kind=='ROLLBACK' and not (prior and current==manifest['git_commit']):
                    # Save the current clean state before switching Git; all historical rows remain.
                    safety=self.create_checkpoint(actor,project)
                    if clean(root)!=current:raise ConfigurationError('Git state changed before recovery')
                    git(root,'checkout','--detach',manifest['git_commit'])
                with self.connection(write=True) as db:
                    lease=db.execute('SELECT lease_owner,fencing_token,lease_expires_at FROM RecoveryLease WHERE project_id=?',(project,)).fetchone()
                    if lease[0]!=owner or lease[1]!=token or lease[2]<=time.time():raise ConfigurationError('Recovery worker fenced')
                    self._check(db,actor,'recovery.run',project,approval,resource)
                    if kind=='ROLLBACK':
                        # Revalidate exactly the approval reviewed before the Git side effect.
                        validate_approval(db,actor,'recovery.run',project,approval,resource)
                        keep={r[0] for r in manifest['files']}
                        for file_id, in db.execute("SELECT file_id FROM FileAsset WHERE space_id=? AND status='ACTIVE'",(manifest['space_id'],)).fetchall():
                            if file_id not in keep:db.execute("UPDATE FileAsset SET status='MISSING',updated_at=? WHERE file_id=?",(now(),file_id))
                        for file_id,revision,_ in manifest['files']:
                            db.execute("UPDATE FileAsset SET current_revision_id=?,status='ACTIVE',updated_at=? WHERE file_id=? AND space_id=?",(revision,now(),file_id,manifest['space_id']))
                        for knowledge,version in manifest['knowledge']:
                            db.execute('UPDATE KnowledgeItem SET current_version_id=?,updated_at=? WHERE knowledge_id=? AND space_id=?',(version,now(),knowledge,manifest['space_id']))
                        self._generation(db,manifest['space_id'])
                    self._reindex_space(db,manifest['space_id'])
                    db.execute("UPDATE RecoveryOperation SET status='VERIFYING',phase='POSTFLIGHT' WHERE operation_id=?",(operation,))
                    if db.execute('PRAGMA foreign_key_check').fetchall():raise ConfigurationError('Recovery FK failure')
                    result={'kind':kind,'manifest_verified':True,'git_commit':git(root,'rev-parse','HEAD'),'safety_checkpoint':safety,'snapshot_ids':manifest['snapshots'] if kind=='REPLAY' else []}
                    if kind=='ROLLBACK' and result['git_commit']!=manifest['git_commit']:raise ConfigurationError('Recovery Git verification failed')
                    db.execute('INSERT INTO RecoveryVerification VALUES(?,?,?)',(operation,canonical(result),now()))
                    db.execute("UPDATE RecoveryOperation SET status='COMPLETED',phase='DONE' WHERE operation_id=?",(operation,))
                    db.execute("UPDATE Execution SET status='COMPLETED',completed_at=?,updated_at=? WHERE execution_id=(SELECT execution_id FROM RecoveryOperation WHERE operation_id=?)",(now(),now(),operation))
                    db.execute('UPDATE RecoveryLease SET lease_expires_at=0,lease_owner=NULL WHERE project_id=? AND fencing_token=?',(project,token))
                    self._audit_change(db,actor,'COMPLETE_RECOVERY',project,{'operation_id':operation,'verification':result})
                    return {'operation_id':operation,'status':'COMPLETED','verification':result}
            except BaseException:
                with self.connection(write=True) as db:
                    db.execute("UPDATE RecoveryOperation SET status='INTERRUPTED' WHERE operation_id=?",(operation,))
                    db.execute('UPDATE RecoveryLease SET lease_expires_at=0,lease_owner=NULL WHERE project_id=? AND fencing_token=?',(project,token))
                    self._audit_change(db,actor,'INTERRUPT_RECOVERY',project,{'operation_id':operation})
                raise
