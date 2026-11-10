"""Bounded diagnostics, redacted occurrences, verified resolutions and metrics."""
from decimal import Decimal,InvalidOperation
import hashlib
import json
import platform
import re
import sqlite3
import time
import uuid
from .core import AccessDenied,ConfigurationError,canonical,now


def redact(text):
    text=re.sub(r'(?i)(authorization\s*[:=]\s*|bearer\s+)[^\s,;]+',r'\1[REDACTED]',str(text))
    text=re.sub(r'(?i)(api[_-]?key|password|secret|token)(\s*[:=]\s*)[^\s,;]+',r'\1\2[REDACTED]',text)
    text=re.sub(r'/(?:Users|home|private|tmp)/[^\s"\x27:,]+','[LOCAL_PATH]',text)
    return text[:10000]

def fingerprint(category,message):
    normalized=re.sub(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b','<uuid>',redact(message),flags=re.I)
    normalized=re.sub(r'line \d+','line <n>',normalized)
    return hashlib.sha256(canonical(['v1',category,normalized]).encode()).hexdigest()

def uid():return str(uuid.uuid4())

class DiagnosticsMixin:
    def diagnostics(self,actor,project,profile='content-integrity'):
        if profile not in ('database','content-integrity','environment'):raise ValueError('Unapproved diagnostic profile')
        start=time.monotonic()
        with self.connection(write=True) as db:
            self._check(db,actor,'diagnostics.run',project);_,space=self._project(db,project)
            execution=self._execution(db,actor,project,'DIAGNOSTICS')
            if profile=='database':
                integrity=db.execute('PRAGMA integrity_check').fetchall();foreign=db.execute('PRAGMA foreign_key_check').fetchall()
                result={'integrity_ok':integrity==[('ok',)],'foreign_key_errors':len(foreign)};passed=result['integrity_ok'] and not foreign
            elif profile=='environment':
                result={'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'fts5':bool(db.execute("SELECT 1 FROM sqlite_schema WHERE name='ContentFTS'").fetchone())};passed=result['fts5']
            else:
                refs=[r[0] for r in db.execute('SELECT content_ref FROM ResourceRegistry WHERE space_id=?',(space,))]
                failed=0
                for ref in refs:
                    try:self.store.get(ref)
                    except ConfigurationError:failed+=1
                result={'checked_objects':len(refs),'failed_objects':failed};passed=not failed
            status='PASSED' if passed else 'FAILED';ref=self.store.put(canonical(result).encode());run=uid()
            db.execute('INSERT INTO DiagnosticRun VALUES(?,?,?,?,?,?,?)',(run,project,execution,profile,status,ref,now()))
            db.execute('INSERT INTO TraceSpan VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),execution,None,execution,project,'diagnostics.'+profile,int((time.monotonic()-start)*1000),status,canonical(result),now()))
            db.execute('UPDATE Execution SET status=?,completed_at=?,updated_at=? WHERE execution_id=?',('COMPLETED' if passed else 'FAILED',now(),now(),execution))
            self._audit_change(db,actor,'RUN_DIAGNOSTICS',project,{'run_id':run,'status':status})
            return {'run_id':run,'status':status,'result':result}
    def record_error(self,actor,project,execution,category,message,environment=None):
        category=redact(category);message=redact(message);environment=environment or {}
        # Never collect arbitrary environment variables, paths, credentials or stack payloads.
        allowed_environment={k:redact(v) for k,v in environment.items() if k in ('python','sqlite','platform','component','version')}
        with self.connection(write=True) as db:
            self._check(db,actor,'error.write',project);_,space=self._project(db,project)
            if not db.execute('SELECT 1 FROM Execution WHERE execution_id=? AND project_id=?',(execution,project)).fetchone():raise AccessDenied('Error execution scope mismatch')
            fp=fingerprint(category,message)
            candidates=[r[0] for r in db.execute('SELECT c.case_id FROM ErrorCase c JOIN ErrorFingerprint f USING(case_id) WHERE c.space_id=? AND f.fingerprint_version=\'v1\' AND f.fingerprint=? ORDER BY c.case_id',(space,fp))]
            case,error,occurrence=uid(),uid(),uid();stamp=now()
            db.execute("INSERT INTO ErrorCase VALUES(?,?,'OPEN',?)",(case,space,stamp))
            db.execute("INSERT INTO ErrorFingerprint VALUES(?,'v1',?)",(case,fp))
            db.execute('INSERT INTO ErrorRecord(error_id,execution_id,error_category,message,fingerprint,created_at) VALUES(?,?,?,?,?,?)',(error,execution,category,message,fp,stamp))
            db.execute('INSERT INTO ErrorOccurrence VALUES(?,?,?,?,?)',(occurrence,case,error,canonical(allowed_environment),stamp))
            self._audit_change(db,actor,'RECORD_ERROR',project,{'case_id':case,'occurrence_id':occurrence})
            return {'case_id':case,'occurrence_id':occurrence,'similar_cases':candidates,'fingerprint_version':'v1'}
    def error_cases(self,actor,project,query=''):
        with self.connection() as db:
            self._check(db,actor,'error.read',project);_,space=self._project(db,project)
            rows=db.execute("SELECT c.case_id,c.status,e.message FROM ErrorCase c JOIN ErrorOccurrence o USING(case_id) JOIN ErrorRecord e USING(error_id) WHERE c.space_id=? AND instr(lower(e.message),lower(?))>0 ORDER BY c.created_at,c.case_id LIMIT 100",(space,query)).fetchall()
            return [{'case_id':r[0],'status':r[1],'message':r[2]} for r in rows]
    def save_resolution(self,actor,case,description,diagnostic_run=None):
        with self.connection(write=True) as db:
            row=db.execute('SELECT s.project_id FROM ErrorCase c JOIN KnowledgeSpace s USING(space_id) WHERE case_id=?',(case,)).fetchone()
            if not row:raise LookupError('Case unavailable')
            project=row[0];self._check(db,actor,'error.write',project)
            status='PROPOSED';evidence=None
            if diagnostic_run:
                run=db.execute("SELECT result_ref FROM DiagnosticRun WHERE run_id=? AND project_id=? AND status='PASSED'",(diagnostic_run,project)).fetchone()
                if not run:raise ValueError('Passing same-project diagnostic required')
                self.store.get(run[0]);evidence=run[0];status='TESTED'
            resolution=uid();db.execute('INSERT INTO ErrorResolution VALUES(?,?,?,?,?,?)',(resolution,case,status,redact(description),evidence,now()))
            # TESTED does not imply universal VERIFIED; preserve human review boundary.
            self._audit_change(db,actor,'SAVE_RESOLUTION',project,{'resolution_id':resolution,'status':status});return resolution
    def metrics(self,actor,project):
        with self.connection() as db:
            self._check(db,actor,'diagnostics.read',project)
            rows=db.execute('SELECT operation_name,count(*),sum(duration_ms),sum(CASE WHEN status IN(\'FAILED\',\'INTERRUPTED\') THEN 1 ELSE 0 END) FROM TraceSpan WHERE project_id=? GROUP BY operation_name ORDER BY operation_name',(project,)).fetchall()
            costs=db.execute('SELECT m.actual_cost_decimal FROM ModelInvocation m JOIN Execution e USING(execution_id) WHERE e.project_id=? AND m.actual_cost_decimal IS NOT NULL',(project,)).fetchall()
            return {'operations':[{'operation':r[0],'count':r[1],'duration_ms':r[2],'failures':r[3]} for r in rows],'model_cost':str(sum((Decimal(r[0]) for r in costs),Decimal(0)))}
    def record_model_invocation(self,actor,project,snapshot,provider,model,input_tokens,output_tokens,cost='0',currency='USD'):
        if isinstance(input_tokens,bool) or isinstance(output_tokens,bool) or not isinstance(input_tokens,int) or not isinstance(output_tokens,int) or min(input_tokens,output_tokens)<0:raise ValueError('Invalid token counts')
        try:decimal=Decimal(cost)
        except (InvalidOperation,TypeError):raise ValueError('Invalid decimal cost')
        if not decimal.is_finite() or decimal<0 or currency!='USD':raise ValueError('Invalid cost or unsupported currency')
        with self.connection(write=True) as db:
            self._check(db,actor,'model.record',project);self._snapshot(db,actor,snapshot)
            row=db.execute('SELECT s.execution_id,r.project_id FROM ContextSnapshot s JOIN RetrievalRun r USING(retrieval_id) WHERE snapshot_id=?',(snapshot,)).fetchone()
            if row[1]!=project:raise AccessDenied('Model invocation project mismatch')
            invocation=uid();db.execute("INSERT INTO ModelInvocation(invocation_id,execution_id,model_provider,model_name,input_tokens,output_tokens,actual_cost_decimal,currency,status,created_at,context_snapshot_id) VALUES(?,?,?,?,?,?,?,?,'COMPLETED',?,?)",(invocation,row[0],redact(provider),redact(model),input_tokens,output_tokens,str(decimal),currency,now(),snapshot))
            self._audit_change(db,actor,'RECORD_MODEL_CALL',project,{'invocation_id':invocation,'snapshot_id':snapshot});return invocation
