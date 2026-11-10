"""Immutable plans, single-worker ticks, bounded pure CODE attempts and fencing."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .core import AccessDenied,ConfigurationError,canonical,now

BUILTINS=('text.hash','text.count','context.echo')

def implementation_hash():return hashlib.sha256(Path(__file__).with_name('worker.py').read_bytes()).hexdigest()
def hash_json(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def new_id():
    import uuid
    return str(uuid.uuid4())

class ExecutionMixin:
    def register_skill(self,actor,skill,version='1'):
        if skill not in BUILTINS or version!='1':raise ValueError('Only reviewed built-in skill revision 1 supported')
        manifest={'skill_id':skill,'version':version,'mode':'CODE','entrypoint':skill,'permissions':['code.run'],'resource_class':'CPU','side_effect_class':'PURE','input_schema':{'text':'string'},'output_schema':'object','timeout_seconds':10,'max_attempts':2}
        with self.connection(write=True) as db:
            self._check(db,actor,'skill.approve',None)
            db.execute('INSERT INTO SkillDefinition VALUES(?,?,?,?,?,?,?)',(skill,version,canonical(manifest),hash_json(manifest),implementation_hash(),actor,now()))
            self._audit_change(db,actor,'REGISTER_SKILL','skills',{'skill_id':skill,'version':version})
        return manifest
    def create_plan(self,actor,project,steps):
        if not isinstance(steps,list) or not 1<=len(steps)<=50:raise ValueError('Plan must contain 1-50 steps')
        keys=[s.get('key') for s in steps]
        if any(not isinstance(k,str) or not k for k in keys) or len(set(keys))!=len(keys):raise ValueError('Unique step keys required')
        visiting=set();visited=set();bykey={s['key']:s for s in steps}
        def visit(k):
            if k in visiting:raise ValueError('DAG cycle')
            if k in visited:return
            visiting.add(k)
            deps=bykey[k].get('depends_on',[])
            if not isinstance(deps,list):raise ValueError('Dependencies must be a list')
            for d in deps:
                if d not in bykey:raise ValueError('Dependency unavailable')
                visit(d)
            visiting.remove(k);visited.add(k)
        for k in keys:visit(k)
        with self.connection(write=True) as db:
            self._check(db,actor,'execution.run',project);self._project(db,project)
            execution=self._execution(db,actor,project,'PLAN');plan=new_id();ids={k:new_id() for k in keys}
            for n,step in enumerate(steps,1):
                if set(step)-{'key','skill_id','version','input','snapshot_id','depends_on','timeout_seconds','max_attempts'}:raise ValueError('Unknown plan property')
                skill=step.get('skill_id');version=step.get('version','1')
                row=db.execute('SELECT manifest,manifest_hash,implementation_hash FROM SkillDefinition WHERE skill_id=? AND version=?',(skill,version)).fetchone()
                if not row or row[2]!=implementation_hash():raise AccessDenied('Skill not approved or code changed')
                manifest=json.loads(row[0])
                for permission in manifest['permissions']:self._check(db,actor,permission,project)
                values=step.get('input',{})
                if 'snapshot_id' in step:values={'text':self._snapshot(db,actor,step['snapshot_id'])['content']}
                from .worker import run
                run(skill,values)  # Bounded schema validation and deterministic builtin only.
                if not 0.01<=step.get('timeout_seconds',10)<=10 or not 1<=step.get('max_attempts',2)<=3:raise ValueError('Attempt limits out of bounds')
                db.execute('INSERT INTO ExecutionStep(step_id,execution_id,step_number,step_key,step_type,name) VALUES(?,?,?,?,?,?)',(ids[step['key']],execution,n,step['key'],'CODE',skill))
                db.execute('INSERT INTO ExecutionSkillBinding VALUES(?,?,?,?,?)',(ids[step['key']],skill,version,row[1],canonical(values)))
                db.execute("INSERT INTO StepScheduling(step_id,queue_state) VALUES(?,'PENDING')",(ids[step['key']],))
            for step in steps:
                for dep in step.get('depends_on',[]):db.execute('INSERT INTO ExecutionStepDependency VALUES(?,?,?)',(execution,ids[step['key']],ids[dep]))
            db.execute('INSERT INTO ExecutionPlan VALUES(?,?,?,?,?)',(plan,project,hash_json(steps),canonical(steps),now()))
            db.execute('INSERT INTO ExecutionPlanBinding VALUES(?,?)',(execution,plan))
            self._audit_change(db,actor,'CREATE_PLAN',project,{'execution_id':execution,'plan_id':plan})
            return execution
    def cancel_execution(self,actor,execution):
        with self.connection(write=True) as db:
            row=db.execute('SELECT project_id FROM Execution WHERE execution_id=?',(execution,)).fetchone()
            if not row:raise LookupError('Execution unavailable')
            self._check(db,actor,'execution.run',row[0])
            db.execute("UPDATE StepScheduling SET queue_state='CANCELLED',fencing_token=fencing_token+1,lease_owner=NULL WHERE step_id IN(SELECT step_id FROM ExecutionStep WHERE execution_id=?) AND queue_state NOT IN('COMPLETED','FAILED','CANCELLED','SKIPPED')",(execution,))
            db.execute("UPDATE ExecutionStep SET status='CANCELLED' WHERE execution_id=? AND status NOT IN('COMPLETED','FAILED','CANCELLED','SKIPPED')",(execution,))
            db.execute("UPDATE StepAttempt SET status='CANCELLED',finished_at=? WHERE status='RUNNING' AND step_id IN(SELECT step_id FROM ExecutionStep WHERE execution_id=?)",(now(),execution))
            db.execute("UPDATE ResourceReservation SET released_at=? WHERE released_at IS NULL AND attempt_id IN(SELECT a.attempt_id FROM StepAttempt a JOIN ExecutionStep s USING(step_id) WHERE s.execution_id=?)",(now(),execution))
            db.execute("UPDATE Execution SET status='CANCELLED',updated_at=?,completed_at=? WHERE execution_id=?",(now(),now(),execution))
            self._audit_change(db,actor,'CANCEL_EXECUTION',row[0],{'execution_id':execution})
    def execution_detail(self,actor,execution):
        with self.connection() as db:
            row=db.execute('SELECT project_id,status FROM Execution WHERE execution_id=?',(execution,)).fetchone()
            if not row:raise LookupError('Execution unavailable')
            self._check(db,actor,'execution.read',row[0])
            steps=db.execute('SELECT s.step_key,s.status,q.queue_state,q.attempt_number,s.output_ref FROM ExecutionStep s JOIN StepScheduling q USING(step_id) WHERE execution_id=? ORDER BY step_number',(execution,)).fetchall()
            return {'execution_id':execution,'status':row[1],'steps':[{'key':r[0],'status':r[1],'queue_state':r[2],'attempts':r[3],'output':json.loads(self.store.get(r[4])) if r[4] else None} for r in steps]}
    def scheduler_tick(self,actor,execution,worker_id='local',lease_seconds=30):
        if not 1<=lease_seconds<=300:raise ValueError('Lease out of bounds')
        claimed=None;clock=time.time()
        with self.connection(write=True) as db:
            row=db.execute('SELECT project_id,status FROM Execution WHERE execution_id=?',(execution,)).fetchone()
            if not row:raise LookupError('Execution unavailable')
            project,status=row;self._check(db,actor,'execution.run',project)
            if status in ('CANCELLED','COMPLETED','FAILED'):return {'claimed':False,'status':status}
            for step,token in db.execute("SELECT q.step_id,q.fencing_token FROM StepScheduling q JOIN ExecutionStep s USING(step_id) WHERE s.execution_id=? AND q.queue_state='RUNNING' AND q.lease_expires_at<=?",(execution,clock)).fetchall():
                db.execute("UPDATE StepAttempt SET status='INTERRUPTED',finished_at=? WHERE step_id=? AND fencing_token=? AND status='RUNNING'",(now(),step,token))
                db.execute("UPDATE ResourceReservation SET released_at=? WHERE attempt_id IN(SELECT attempt_id FROM StepAttempt WHERE step_id=? AND fencing_token=?) AND released_at IS NULL",(now(),step,token))
                db.execute("UPDATE StepScheduling SET queue_state='RETRY_WAIT',fencing_token=fencing_token+1,lease_owner=NULL,next_attempt_at=? WHERE step_id=?",(clock,step))
                db.execute("UPDATE ExecutionStep SET status='READY' WHERE step_id=?",(step,))
            rows=db.execute("""SELECT s.step_id,s.step_key,q.queue_state,q.attempt_number,q.fencing_token,b.skill_id,b.skill_version,b.manifest_hash,b.input_json
                FROM ExecutionStep s JOIN StepScheduling q USING(step_id) JOIN ExecutionSkillBinding b USING(step_id)
                WHERE s.execution_id=? AND q.queue_state IN('PENDING','BLOCKED','READY','RETRY_WAIT','WAITING_APPROVAL') AND q.next_attempt_at<=? ORDER BY s.step_number""",(execution,clock)).fetchall()
            plan=json.loads(db.execute('SELECT definition FROM ExecutionPlan JOIN ExecutionPlanBinding USING(plan_id) WHERE execution_id=?',(execution,)).fetchone()[0]);definitions={s['key']:s for s in plan}
            for step,key,queue,attempts,token,skill,version,manifest_hash,values in rows:
                deps=[r[0] for r in db.execute('SELECT s.status FROM ExecutionStepDependency d JOIN ExecutionStep s ON s.step_id=d.depends_on_step_id WHERE d.step_id=?',(step,))]
                if any(x in ('FAILED','CANCELLED','SKIPPED') for x in deps):
                    db.execute("UPDATE StepScheduling SET queue_state='SKIPPED' WHERE step_id=?",(step,));db.execute("UPDATE ExecutionStep SET status='SKIPPED' WHERE step_id=?",(step,));continue
                if any(x!='COMPLETED' for x in deps):
                    db.execute("UPDATE StepScheduling SET queue_state='BLOCKED' WHERE step_id=?",(step,));continue
                limits=definitions[key]
                if attempts>=limits.get('max_attempts',2):
                    db.execute("UPDATE StepScheduling SET queue_state='FAILED' WHERE step_id=?",(step,));db.execute("UPDATE ExecutionStep SET status='FAILED' WHERE step_id=?",(step,));continue
                registered=db.execute('SELECT manifest,manifest_hash,implementation_hash FROM SkillDefinition WHERE skill_id=? AND version=?',(skill,version)).fetchone()
                if not registered or registered[1]!=manifest_hash or registered[2]!=implementation_hash():raise AccessDenied('Skill integrity mismatch')
                for permission in json.loads(registered[0])['permissions']:self._check(db,actor,permission,project)
                active=db.execute("SELECT count(*) FROM ResourceReservation WHERE resource_class='CPU' AND released_at IS NULL AND lease_expires_at>?",(clock,)).fetchone()[0]
                if active>=1:continue
                attempt=new_id();fence=token+1;expires=clock+lease_seconds
                db.execute("UPDATE StepScheduling SET queue_state='RUNNING',attempt_number=attempt_number+1,fencing_token=?,lease_owner=?,lease_expires_at=? WHERE step_id=? AND fencing_token=?",(fence,worker_id,expires,step,token))
                db.execute("UPDATE ExecutionStep SET status='RUNNING',started_at=? WHERE step_id=?",(now(),step))
                db.execute("INSERT INTO StepAttempt VALUES(?,?,?,?,?,'RUNNING',?,NULL,NULL,?,NULL)",(attempt,step,attempts+1,fence,worker_id,hash_json(json.loads(values)),now()))
                db.execute("INSERT INTO ResourceReservation VALUES(?,'CPU',?,NULL)",(attempt,expires))
                self._audit_change(db,actor,'CLAIM_STEP',project,{'attempt_id':attempt,'fence':fence})
                claimed=(step,attempt,fence,skill,json.loads(values),limits.get('timeout_seconds',10),project,attempts+1,limits.get('max_attempts',2));break
            if claimed is None:
                statuses=[r[0] for r in db.execute('SELECT status FROM ExecutionStep WHERE execution_id=?',(execution,))]
                if statuses and all(x in ('COMPLETED','FAILED','CANCELLED','SKIPPED') for x in statuses):
                    final='FAILED' if any(x=='FAILED' for x in statuses) else 'COMPLETED'
                    db.execute('UPDATE Execution SET status=?,completed_at=?,updated_at=? WHERE execution_id=?',(final,now(),now(),execution))
                    self._audit_change(db,actor,'FINISH_EXECUTION',project,{'execution_id':execution,'status':final})
                return {'claimed':False}
        step,attempt,fence,skill,values,timeout,project,number,max_attempts=claimed;error=None;ref=None;start=time.monotonic()
        try:
            package=Path(__file__).resolve().parents[1]
            result=subprocess.run([sys.executable,'-m','pilo_core.worker'],input=canonical({'skill':skill,'input':values}),text=True,capture_output=True,timeout=timeout,cwd=package,env={'PATH':os.defpath,'PYTHONPATH':str(package),'PYTHONDONTWRITEBYTECODE':'1'})
            if result.returncode!=0:raise ValueError('Skill output validation failed')
            output=json.loads(result.stdout)
            if not isinstance(output,dict):raise ValueError('Skill output must be an object')
            ref=self.store.put(canonical(output).encode())
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:error='TIMEOUT' if isinstance(exc,subprocess.TimeoutExpired) else type(exc).__name__
        with self.connection(write=True) as db:
            self._check(db,actor,'execution.run',project);self._check(db,actor,'code.run',project)
            current=db.execute('SELECT queue_state,fencing_token,lease_expires_at FROM StepScheduling WHERE step_id=?',(step,)).fetchone()
            if current[0]!='RUNNING' or current[1]!=fence or current[2]<=time.time():raise ConfigurationError('Stale worker result fenced')
            final='COMPLETED' if error is None else ('READY' if number<max_attempts and error=='TIMEOUT' else 'FAILED')
            db.execute('UPDATE ExecutionStep SET status=?,output_ref=?,error_ref=?,completed_at=? WHERE step_id=?',(final,ref,error,now() if final!='READY' else None,step))
            db.execute('UPDATE StepScheduling SET queue_state=?,lease_owner=NULL,lease_expires_at=NULL,next_attempt_at=? WHERE step_id=?',('RETRY_WAIT' if final=='READY' else final,time.time()+min(30,2**number),step))
            db.execute('UPDATE StepAttempt SET status=?,output_ref=?,error_code=?,finished_at=? WHERE attempt_id=?',('COMPLETED' if error is None else 'FAILED',ref,error,now(),attempt))
            db.execute('UPDATE ResourceReservation SET released_at=? WHERE attempt_id=?',(now(),attempt))
            self._audit_change(db,actor,'FINISH_STEP',project,{'attempt_id':attempt,'status':final,'error_code':error})
            db.execute('INSERT INTO TraceSpan VALUES(?,?,?,?,?,?,?,?,?,?)',(new_id(),execution,None,execution,project,'skill.execute',int((time.monotonic()-start)*1000),final,canonical({'attempt_id':attempt,'skill_id':skill}),now()))
        return {'claimed':True,'attempt_id':attempt,'status':final}
