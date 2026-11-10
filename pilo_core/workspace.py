"""Authorized file/knowledge ingestion and reproducible retrieval."""
from datetime import datetime,timezone,timedelta
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from .core import Core,AccessDenied,ConfigurationError,canonical,now
from .security import authorize,has_permission,policy_hash,scope_hash,approval_context
from .storage import ContentStore


def uid():return str(uuid.uuid4())
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def safe_read(root,relative,limit=2_000_000):
    parts=Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ('.','..') for p in parts):raise AccessDenied('Invalid relative path')
    current=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current);os.close(current);current=child
        fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=current)
        with os.fdopen(fd,'rb') as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size>limit:raise ValueError('Source size/type refused')
            data=f.read(limit+1);after=os.fstat(f.fileno())
            if len(data)>limit or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during read')
            data.decode('utf-8')
            return data
    finally:os.close(current)


class WorkspaceBase(Core):
    def __init__(self,config_path):
        super().__init__(config_path)
        if self.version!=2:raise ConfigurationError('Run explicit workspace upgrade first')
        root=self.config.get('content_store_path',str(self.path.parent/'content'))
        if not Path(root).is_absolute():root=self.config_path.parent/root
        self.store=ContentStore(root)
    def _check(self,db,actor,action,project,approval=None,resource=None):
        return authorize(self,db,actor,action,project,approval,resource)
    def _project(self,db,project):
        row=db.execute("SELECT p.root_path,s.space_id FROM Project p JOIN KnowledgeSpace s ON s.project_id=p.project_id WHERE p.project_id=? AND p.status='ACTIVE' AND s.status='ACTIVE'",(project,)).fetchone()
        if not row:raise LookupError('Project unavailable')
        return row
    def _space(self,db,actor,space,permission):
        row=db.execute("SELECT space_type,project_id FROM KnowledgeSpace WHERE space_id=? AND status='ACTIVE'",(space,)).fetchone()
        if not row:raise AccessDenied('Space unavailable')
        self._check(db,actor,permission,row[1] if row[0]=='PROJECT' else None)
    def _execution(self,db,actor,project,kind):
        execution=uid();stamp=now()
        db.execute("INSERT INTO Execution(execution_id,scope_type,project_id,actor_type,actor_id,execution_type,status,created_at,updated_at) VALUES (?,'PROJECT',?,'USER',?,?, 'RUNNING',?,?)",(execution,project,actor,kind,stamp,stamp))
        return execution
    def _audit_change(self,db,actor,action,project,details):
        self._verify_audit(db);self._audit(db,actor,action,project,details,now())
    def _generation(self,db,space):
        db.execute('UPDATE SpaceGeneration SET source_generation=source_generation+1,indexed_generation=source_generation+1 WHERE space_id=?',(space,))
    def _unit(self,db,space,text,revision=None,version=None):
        # Fixed character chunks are deterministic; budget uses a conservative UTF-8 byte upper bound.
        for ordinal,start in enumerate(range(0,len(text),2000)):
            chunk=text[start:start+2000]
            db.execute('INSERT INTO ContentUnit VALUES (?,?,?,?,?,?,?)',(uid(),space,revision,version,ordinal,chunk,hashlib.sha256(chunk.encode()).hexdigest()))
    def scan(self,actor,project,patterns=('*.py','*.md','*.txt','*.json','*.toml','*.yaml','*.yml'),max_files=2000):
        with self.connection() as db:
            self._check(db,actor,'files.scan',project);root,space=self._project(db,project)
        root=Path(root).resolve(strict=True);files={};excluded=[]
        for path in sorted(root.rglob('*')):
            rel=path.relative_to(root).as_posix();parts=Path(rel).parts
            if any(p.startswith('.') or p in ('node_modules','__pycache__','data','backups','extensions') for p in parts):continue
            if path.is_symlink():excluded.append(rel);continue
            if not path.is_file() or not any(fnmatch.fnmatch(rel,p) for p in patterns):continue
            if len(files)>=max_files:raise ValueError('Scan file budget exceeded')
            try:data=safe_read(root,rel)
            except (UnicodeError,ValueError,OSError):excluded.append(rel);continue
            # Secret-pattern exclusion is conservative and never included as a diagnostic excerpt.
            if re.search(rb'(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*[\x22\x27]?[^\s\x22\x27]{8,}',data):excluded.append(rel);continue
            files[rel]=(self.store.put(data),data)
        changed=[]
        with self.connection(write=True) as db:
            self._check(db,actor,'files.scan',project)
            for rel,(ref,data) in files.items():
                row=db.execute('SELECT f.file_id,r.content_hash FROM FileAsset f LEFT JOIN FileRevision r ON r.revision_id=f.current_revision_id WHERE f.space_id=? AND f.logical_path=? AND f.status IN(\'ACTIVE\',\'MISSING\')',(space,rel)).fetchone()
                if row and row[1]==ref:
                    db.execute("UPDATE FileAsset SET status='ACTIVE',last_seen_at=? WHERE file_id=?",(now(),row[0]));continue
                file_id=row[0] if row else uid();revision=uid();stamp=now()
                if not row:
                    db.execute('INSERT INTO FileAsset(file_id,space_id,logical_path,filename,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(file_id,space,rel,Path(rel).name,stamp,stamp,stamp,stamp))
                    db.execute("INSERT INTO FileLocationHistory VALUES(?,?,?,?,?,?)",(uid(),file_id,rel,stamp,None,'REGISTER'))
                number=db.execute('SELECT coalesce(max(revision_number),0)+1 FROM FileRevision WHERE file_id=?',(file_id,)).fetchone()[0]
                db.execute('INSERT INTO FileRevision(revision_id,file_id,space_id,revision_number,content_hash,size_bytes,observed_at,storage_ref,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(revision,file_id,space,number,ref,len(data),stamp,ref,stamp))
                db.execute("UPDATE FileAsset SET current_revision_id=?,status='ACTIVE',last_seen_at=?,updated_at=? WHERE file_id=?",(revision,stamp,stamp,file_id))
                db.execute('INSERT INTO ResourceRegistry VALUES(?,?,?,?,?,?)',(revision,space,revision,None,ref,ref))
                self._unit(db,space,data.decode(),revision=revision);changed.append(rel)
            for file_id,rel in db.execute("SELECT file_id,logical_path FROM FileAsset WHERE space_id=? AND status='ACTIVE'",(space,)).fetchall():
                if rel not in files and any(fnmatch.fnmatch(rel,p) for p in patterns):
                    db.execute("UPDATE FileAsset SET status='MISSING',updated_at=? WHERE file_id=?",(now(),file_id));changed.append(rel)
            if changed:self._generation(db,space)
            self._audit_change(db,actor,'SCAN_PROJECT',project,{'changed':changed,'excluded_count':len(excluded)})
        return {'changed':changed,'excluded':excluded,'files':len(files)}
    def request_approval(self,actor,action,project,resource,expires_seconds=600):
        if not 1<=expires_seconds<=3600:raise ValueError('Approval expiry out of bounds')
        with self.connection(write=True) as db:
            if not has_permission(db,actor,action,project):raise AccessDenied('Action permission required')
            self._check(db,actor,'approval.request',project)
            context=approval_context(db,action,project,resource);approval=uid();stamp=now()
            expiry=(datetime.now(timezone.utc)+timedelta(seconds=expires_seconds)).isoformat(timespec='milliseconds').replace('+00:00','Z')
            db.execute("INSERT INTO ApprovalRequest(approval_context_hash,policy_version_ref,approval_id,resource_type,resource_id,resource_hash,action,status,requested_by,requested_at,expires_at) VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?)",(digest(context),policy_hash(db),approval,'WORKSPACE',digest(resource),digest(resource),action,actor,stamp,expiry))
            db.execute('INSERT INTO ApprovalGrant VALUES(?,?,?,NULL)',(approval,project,canonical(context)))
            self._audit_change(db,actor,'REQUEST_APPROVAL',project,{'approval_id':approval,'action':action})
            return approval
    def decide_approval(self,actor,approval,decision='APPROVE',reason='Operator review'):
        with self.connection(write=True) as db:
            row=db.execute('SELECT g.project_id,r.requested_by,r.expires_at FROM ApprovalGrant g JOIN ApprovalRequest r USING(approval_id) WHERE approval_id=?',(approval,)).fetchone()
            if not row:raise LookupError('Approval unavailable')
            self._check(db,actor,'approval.decide',row[0])
            if actor==row[1]:raise AccessDenied('Independent approver required')
            if row[2]<=now():raise AccessDenied('Approval expired')
            db.execute('INSERT INTO ApprovalDecision VALUES(?,?,?,?,?,?)',(uid(),approval,actor,decision,reason,now()))
            self._audit_change(db,actor,'DECIDE_APPROVAL',row[0],{'approval_id':approval,'decision':decision})
    def revoke_approval(self,actor,approval):
        with self.connection(write=True) as db:
            row=db.execute('SELECT project_id FROM ApprovalGrant WHERE approval_id=?',(approval,)).fetchone()
            if not row:raise LookupError('Approval unavailable')
            self._check(db,actor,'approval.decide',row[0]);db.execute('UPDATE ApprovalGrant SET revoked_at=? WHERE approval_id=?',(now(),approval))
            self._audit_change(db,actor,'REVOKE_APPROVAL',row[0],{'approval_id':approval})
    def save_knowledge(self,actor,project,title,text,kind='REFERENCE',approval=None):
        resource={'title':title,'hash':hashlib.sha256(text.encode()).hexdigest(),'kind':kind}
        with self.connection() as db:self._check(db,actor,'knowledge.write',project,approval,resource);_,space=self._project(db,project)
        ref=self.store.put(text.encode());knowledge,version=uid(),uid();stamp=now()
        with self.connection(write=True) as db:
            self._check(db,actor,'knowledge.write',project,approval,resource)
            db.execute('INSERT INTO KnowledgeItem(knowledge_id,space_id,title,knowledge_type,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(knowledge,space,title,kind,actor,stamp,stamp))
            db.execute("INSERT INTO KnowledgeVersion(version_id,knowledge_id,space_id,version_number,content_ref,content_hash,created_by,created_at) VALUES(?,?,?,1,?,?,?,?)",(version,knowledge,space,ref,ref,actor,stamp))
            self._audit_change(db,actor,'DRAFT_KNOWLEDGE',project,{'knowledge_id':knowledge,'version_id':version})
        return {'knowledge_id':knowledge,'version_id':version,'hash':ref}
    def activate_knowledge(self,actor,version,approval=None):
        with self.connection(write=True) as db:
            row=db.execute('SELECT v.knowledge_id,v.space_id,v.content_ref,v.content_hash,s.project_id FROM KnowledgeVersion v JOIN KnowledgeSpace s USING(space_id) WHERE version_id=?',(version,)).fetchone()
            if not row:raise LookupError('Version unavailable')
            knowledge,space,ref,content_hash,project=row;resource={'version_id':version,'hash':content_hash}
            self._check(db,actor,'knowledge.approve',project,approval,resource);text=self.store.get(ref).decode()
            db.execute("UPDATE KnowledgeVersion SET review_status='APPROVED',approved_by=?,approved_at=? WHERE version_id=? AND review_status<>'APPROVED'",(actor,now(),version))
            db.execute('UPDATE KnowledgeItem SET current_version_id=?,updated_at=? WHERE knowledge_id=?',(version,now(),knowledge))
            if not db.execute('SELECT 1 FROM ResourceRegistry WHERE resource_id=?',(version,)).fetchone():
                db.execute('INSERT INTO ResourceRegistry VALUES(?,?,?,?,?,?)',(version,space,None,version,ref,content_hash));self._unit(db,space,text,version=version)
            self._generation(db,space);self._audit_change(db,actor,'ACTIVATE_KNOWLEDGE',project,resource)
    def accessible_projects(self,actor):
        with self.connection() as db:
            visible=[]
            for project,key,name,status in db.execute('SELECT project_id,project_key,name,status FROM Project ORDER BY project_key LIMIT 1000'):
                try:self._check(db,actor,'project.read',project)
                except AccessDenied:continue
                visible.append({'project_id':project,'project_key':key,'name':name,'status':status})
            return {'projects':visible}
    def _allowed_spaces(self,db,actor,project):
        self._check(db,actor,'context.read',project);_,space=self._project(db,project);spaces=[space]
        common=db.execute("SELECT space_id FROM KnowledgeSpace WHERE space_type='COMMON' AND status='ACTIVE'").fetchone()
        if common:
            try:self._check(db,actor,'common.read',None);spaces.append(common[0])
            except AccessDenied:pass
        return sorted(spaces)
    def snapshot(self,actor,snapshot_id):
        with self.connection() as db:return self._snapshot(db,actor,snapshot_id)
    def _snapshot(self,db,actor,snapshot_id):
        row=db.execute('SELECT s.content_ref,s.context_hash,r.project_id,s.token_count,r.status FROM ContextSnapshot s JOIN RetrievalRun r USING(retrieval_id) WHERE snapshot_id=?',(snapshot_id,)).fetchone()
        if not row:raise LookupError('Snapshot unavailable')
        allowed=self._allowed_spaces(db,actor,row[2])
        for space, in db.execute('SELECT DISTINCT space_id FROM ContextSnapshotItem WHERE snapshot_id=?',(snapshot_id,)):
            if space not in allowed:raise AccessDenied('Snapshot source permission revoked')
        content=self.store.get(row[0])
        if hashlib.sha256(content).hexdigest()!=row[1]:raise ConfigurationError('Snapshot corrupted')
        return {'snapshot_id':snapshot_id,'content':content.decode(),'token_count':row[3],'status':row[4]}
    def retrieve(self,actor,project,query,max_tokens=4096,idempotency_key=None,execution_id=None,strategy='lexical'):
        if strategy not in ('lexical','semantic'):raise ValueError('Invalid search strategy')
        if not isinstance(query,str) or not query.strip() or len(query)>1000:raise ValueError('Invalid query')
        if not 1<=max_tokens<=32768:raise ValueError('Context budget out of bounds')
        key=idempotency_key or uid();request_hash=digest([actor,project,query,max_tokens,strategy])
        with self.connection(write=True) as db:
            spaces=self._allowed_spaces(db,actor,project);scope=scope_hash(db,actor,spaces);policy=policy_hash(db)
            if execution_id:
                owner=db.execute('SELECT project_id,actor_id FROM Execution WHERE execution_id=?',(execution_id,)).fetchone()
                if owner!=(project,actor):raise AccessDenied('Execution ownership mismatch')
                prior=db.execute('SELECT r.request_hash,s.snapshot_id FROM RetrievalRun r JOIN ContextSnapshot s USING(retrieval_id) WHERE r.execution_id=? AND r.idempotency_key=?',(execution_id,key)).fetchone()
                if prior:
                    if prior[0]!=request_hash:raise ValueError('Idempotency key request mismatch')
                    return self._snapshot(db,actor,prior[1])
            generation=db.execute('SELECT space_id,source_generation,indexed_generation FROM SpaceGeneration ORDER BY space_id').fetchall()
            gens=[r for r in generation if r[0] in spaces]
            if any(s!=i for _,s,i in gens):raise ConfigurationError('Search index generation is stale')
            cache_key=digest([query,scope,policy,gens,strategy]);cached=db.execute('SELECT candidates FROM QueryCache WHERE cache_key=? AND scope_fingerprint=?',(cache_key,scope)).fetchone()
            candidates=json.loads(cached[0]) if cached and strategy=='lexical' else None
            if strategy=='semantic':self._check(db,actor,'vector.read',project)
            placeholders=','.join('?' for _ in spaces)
            base=f"""SELECT u.unit_id,u.space_id,u.text,u.content_hash,coalesce(f.logical_path,k.title),k.knowledge_type
                FROM ContentUnit u LEFT JOIN FileRevision v ON v.revision_id=u.revision_id
                LEFT JOIN FileAsset f ON f.file_id=v.file_id LEFT JOIN KnowledgeVersion kv ON kv.version_id=u.knowledge_version_id
                LEFT JOIN KnowledgeItem k ON k.knowledge_id=kv.knowledge_id
                WHERE u.space_id IN({placeholders}) AND
                ((f.status='ACTIVE' AND f.current_revision_id=u.revision_id) OR (k.status='ACTIVE' AND k.current_version_id=u.knowledge_version_id AND kv.review_status='APPROVED'))"""
            rows=db.execute(base,spaces).fetchall();byid={r[0]:r for r in rows}
            if strategy=='semantic':
                candidates=self._semantic_rank(db,actor,project,query,rows)
            if candidates is None:
                if len(query)>=3:
                    match='"'+query.replace('"','""')+'"'
                    hits={r[0] for r in db.execute('SELECT rowid FROM ContentFTS WHERE ContentFTS MATCH ?',(match,))}
                    rowids=dict(db.execute('SELECT unit_id,rowid FROM ContentUnit'))
                else:hits=set();rowids={}
                ranked=[]
                for row in rows:
                    mandatory=row[5] in ('RULE','DECISION');exact=query.casefold() in (row[4] or '').casefold();lexical=query.casefold() in row[2].casefold()
                    if mandatory or exact or lexical or rowids.get(row[0]) in hits:
                        ranked.append((not mandatory,not exact,not lexical,row[4] or '',row[0]))
                candidates=[x[-1] for x in sorted(ranked)][:100]
                db.execute('INSERT INTO QueryCache VALUES(?,?,?,?,?)',(cache_key,scope,policy,canonical(candidates),now()))
                for space,s,i in gens:db.execute('INSERT INTO CacheDependency VALUES(?,?,?,?)',(cache_key,space,s,i))
            execution=execution_id or self._execution(db,actor,project,'RETRIEVAL');retrieval=uid();snapshot=uid();items=[];pieces=[];used=0;excluded=[]
            for unit in candidates:
                row=byid.get(unit)
                if not row:raise ConfigurationError('Cached source no longer eligible')
                piece=f'[{row[4]}]\n{row[2]}\n';cost=len(piece.encode())+(1 if pieces else 0)
                if used+cost>max_tokens:
                    if row[5] in ('RULE','DECISION'):raise ValueError('Mandatory context exceeds budget')
                    excluded.append(unit);continue
                items.append(row);pieces.append(piece);used+=cost
            body='\n'.join(pieces);ref=self.store.put(body.encode());status='COMPLETED' if items and not excluded else 'PARTIAL'
            db.execute('INSERT INTO RetrievalRun VALUES(?,?,?,?,?,?,?,?,?,?,?)',(retrieval,execution,project,actor,request_hash,key,scope,policy,status,'SUFFICIENT' if status=='COMPLETED' else 'INSUFFICIENT',now()))
            db.execute('INSERT INTO ContextSnapshot VALUES(?,?,?,?,?,?,?,?,?)',(snapshot,execution,retrieval,ref,ref,len(body.encode()),'utf8-byte-upper-bound-v1',('semantic-ollama-v1' if strategy=='semantic' else 'deterministic-v1'),now()))
            for ordinal,row in enumerate(items):db.execute('INSERT INTO ContextSnapshotItem VALUES(?,?,?,?,?)',(snapshot,ordinal,row[1],row[0],row[3]))
            for rank,unit in enumerate(candidates,1):db.execute('INSERT INTO RetrievalCandidate VALUES(?,?,?,?,?)',(retrieval,unit,rank,'EXCLUDED' if unit in excluded else 'SELECTED','budget' if unit in excluded else 'policy-and-relevance'))
            db.execute('INSERT INTO SnapshotSeal VALUES(?)',(snapshot,))
            self._audit_change(db,actor,'CREATE_CONTEXT',project,{'snapshot_id':snapshot,'retrieval_id':retrieval})
            if not execution_id:db.execute("UPDATE Execution SET status='COMPLETED',completed_at=?,updated_at=? WHERE execution_id=?",(now(),now(),execution))
            result=self._snapshot(db,actor,snapshot);result.update(execution_id=execution,retrieval_id=retrieval,cache_hit=bool(cached),excluded_count=len(excluded));return result
    def _reindex_space(self,db,space):
        for rowid,text in db.execute('SELECT rowid,text FROM ContentUnit WHERE space_id=?',(space,)).fetchall():
            db.execute("INSERT INTO ContentFTS(ContentFTS,rowid,text) VALUES('delete',?,?)",(rowid,text))
            db.execute('INSERT INTO ContentFTS(rowid,text) VALUES(?,?)',(rowid,text))
        db.execute('UPDATE SpaceGeneration SET indexed_generation=source_generation WHERE space_id=?',(space,))
        db.execute('DELETE FROM QueryCache WHERE cache_key IN(SELECT cache_key FROM CacheDependency WHERE space_id=?)',(space,))
    def rebuild_index(self,actor,project,approval=None):
        with self.connection(write=True) as db:
            self._check(db,actor,'index.rebuild',project,approval,{'project_id':project})
            _,space=self._project(db,project);self._reindex_space(db,space)
            self._audit_change(db,actor,'REBUILD_INDEX',project,{})

from .knowledge import KnowledgeMixin
from .execution import ExecutionMixin
from .recovery import RecoveryMixin
from .diagnostics import DiagnosticsMixin
from .extensions import ExtensionsMixin
class Workspace(ExtensionsMixin,KnowledgeMixin,ExecutionMixin,RecoveryMixin,DiagnosticsMixin,WorkspaceBase):
    pass
