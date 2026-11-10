"""Approval-bound redacted promotion with full direct/claim evidence copying."""
from datetime import datetime,timezone,timedelta
import hashlib
import json
import uuid
from .core import AccessDenied,ConfigurationError,canonical,now
from .security import approval_context,policy_hash,validate_approval,has_permission
from .diagnostics import redact


def uid():return str(uuid.uuid4())
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

class KnowledgeMixin:
    def add_evidence(self,actor,version,text):
        with self.connection(write=True) as db:
            row=db.execute('SELECT v.space_id,s.project_id FROM KnowledgeVersion v JOIN KnowledgeSpace s USING(space_id) WHERE version_id=?',(version,)).fetchone()
            if not row:raise LookupError('Version unavailable')
            self._check(db,actor,'knowledge.write',row[1]);evidence=uid();ref=self.store.put(text.encode())
            db.execute("INSERT INTO Evidence(evidence_id,space_id,source_type,source_ref,content_excerpt,content_hash,collected_at) VALUES(?,?,'USER_INPUT',?,?,?,?)",(evidence,row[0],ref,text,ref,now()))
            db.execute("INSERT INTO KnowledgeEvidence VALUES(?,?,?,'SUPPORTS',?)",(row[0],version,evidence,now()))
            self._audit_change(db,actor,'ATTACH_EVIDENCE',row[1],{'version_id':version,'evidence_id':evidence});return evidence
    def _promotion_source(self,db,actor,version):
        row=db.execute("SELECT v.knowledge_id,v.space_id,v.content_ref,v.content_hash,s.project_id,k.title,k.knowledge_type FROM KnowledgeVersion v JOIN KnowledgeSpace s USING(space_id) JOIN KnowledgeItem k USING(knowledge_id) WHERE v.version_id=? AND s.space_type='PROJECT' AND v.review_status='APPROVED'",(version,)).fetchone()
        if not row:raise LookupError('Approved project knowledge required')
        self._check(db,actor,'context.read',row[4]);self._check(db,actor,'common.write',None)
        if not has_permission(db,actor,'knowledge.promote',row[4]):raise AccessDenied('Promotion permission required')
        text=redact(self.store.get(row[2]).decode())
        resource={'version_id':version,'source_hash':row[3],'target_hash':hashlib.sha256(text.encode()).hexdigest()}
        return row,text,resource
    def request_promotion(self,actor,version,idempotency_key):
        with self.connection(write=True) as db:
            source,text,resource=self._promotion_source(db,actor,version);project=source[4]
            self._check(db,actor,'approval.request',project)
            prior=db.execute('SELECT promotion_id,source_version_id,approval_id FROM KnowledgePromotion WHERE idempotency_key=?',(idempotency_key,)).fetchone()
            if prior:
                if prior[1]!=version:raise ValueError('Promotion idempotency mismatch')
                return {'promotion_id':prior[0],'approval_id':prior[2]}
            promotion,approval=uid(),uid();stamp=now();context=approval_context(db,'knowledge.promote',project,resource)
            expiry=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(timespec='milliseconds').replace('+00:00','Z')
            db.execute("INSERT INTO ApprovalRequest(approval_context_hash,policy_version_ref,approval_id,resource_type,resource_id,resource_version_ref,resource_hash,action,status,requested_by,requested_at,expires_at) VALUES(?,?,?,'KNOWLEDGE_PROMOTION',?,?,?,'PROMOTE','PENDING',?,?,?)",(digest(context),policy_hash(db),approval,promotion,version,source[3],actor,stamp,expiry))
            db.execute('INSERT INTO ApprovalGrant VALUES(?,?,?,NULL)',(approval,project,canonical(context)))
            db.execute("INSERT INTO KnowledgePromotion(promotion_id,idempotency_key,source_knowledge_id,source_version_id,approval_id,requested_by,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'WAITING_APPROVAL',?,?)",(promotion,idempotency_key,source[0],version,approval,actor,stamp,stamp))
            self._audit_change(db,actor,'REQUEST_PROMOTION',project,{'promotion_id':promotion,'approval_id':approval})
            return {'promotion_id':promotion,'approval_id':approval,'redacted_preview':text,'context':resource}
    def apply_promotion(self,actor,promotion):
        with self.connection(write=True) as db:
            promotion_row=db.execute('SELECT source_version_id,approval_id,status,target_version_id FROM KnowledgePromotion WHERE promotion_id=?',(promotion,)).fetchone()
            if not promotion_row:raise LookupError('Promotion unavailable')
            source,text,resource=self._promotion_source(db,actor,promotion_row[0]);knowledge,space,_,_,project,title,kind=source
            if promotion_row[2]=='COMPLETED':return {'version_id':promotion_row[3]}
            validate_approval(db,actor,'knowledge.promote',project,promotion_row[1],resource)
            self._check(db,actor,'knowledge.promote',project,promotion_row[1],resource)
            common=db.execute("SELECT space_id FROM KnowledgeSpace WHERE space_type='COMMON' AND status='ACTIVE'").fetchone()[0]
            db.execute("UPDATE KnowledgePromotion SET status='APPROVED',updated_at=? WHERE promotion_id=?",(now(),promotion))
            db.execute("UPDATE KnowledgePromotion SET status='APPLYING',updated_at=? WHERE promotion_id=?",(now(),promotion))
            target,version=uid(),uid();stamp=now();ref=self.store.put(text.encode())
            db.execute('INSERT INTO KnowledgeItem(knowledge_id,space_id,title,knowledge_type,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(target,common,redact(title),kind,actor,stamp,stamp))
            db.execute('INSERT INTO KnowledgeVersion(version_id,knowledge_id,space_id,version_number,content_ref,content_hash,created_by,created_at) VALUES(?,?,?,1,?,?,?,?)',(version,target,common,ref,ref,actor,stamp))
            direct=db.execute('SELECT evidence_id,relation FROM KnowledgeEvidence WHERE version_id=?',(promotion_row[0],)).fetchall()
            claims=db.execute('SELECT c.claim_id,c.statement,c.claim_type,c.status,v.relation FROM KnowledgeVersionClaim v JOIN Claim c USING(claim_id) WHERE v.version_id=?',(promotion_row[0],)).fetchall()
            claim_support={c[0]:db.execute('SELECT evidence_id,relation FROM ClaimEvidence WHERE claim_id=?',(c[0],)).fetchall() for c in claims}
            evidence_ids={e[0] for e in direct}|{e[0] for support in claim_support.values() for e in support};mapping={}
            for evidence in sorted(evidence_ids):
                original=db.execute('SELECT content_excerpt,verification_status,revision_id FROM Evidence WHERE evidence_id=? AND space_id=?',(evidence,space)).fetchone()
                if not original:raise ConfigurationError('Promotion evidence scope mismatch')
                excerpt=original[0]
                if excerpt is None and original[2]:
                    storage=db.execute('SELECT storage_ref FROM FileRevision WHERE revision_id=?',(original[2],)).fetchone()[0];excerpt=self.store.get(storage).decode()
                if excerpt is None:raise ConfigurationError('Separately usable evidence text required')
                excerpt=redact(excerpt);target_evidence=uid();mapping[evidence]=target_evidence;hashtext=hashlib.sha256(excerpt.encode()).hexdigest()
                db.execute("INSERT INTO Evidence(evidence_id,space_id,source_type,source_ref,content_excerpt,content_hash,collected_at,verification_status) VALUES(?,?,'USER_INPUT',?,?,?,?,?)",(target_evidence,common,'promotion:'+promotion,excerpt,hashtext,stamp,original[1]))
                db.execute("INSERT INTO EvidenceLineage VALUES(?,?,?,'PROMOTED_FROM',?,?)",(uid(),evidence,target_evidence,promotion,stamp))
            for evidence,relation in direct:db.execute('INSERT INTO KnowledgeEvidence VALUES(?,?,?,?,?)',(common,version,mapping[evidence],relation,stamp))
            for claim,statement,claim_type,status,relation in claims:
                target_claim=uid();db.execute('INSERT INTO Claim VALUES(?,?,?,?,?,?,?,?)',(target_claim,common,redact(statement),claim_type,status,actor,stamp,stamp))
                for evidence,support in claim_support[claim]:db.execute('INSERT INTO ClaimEvidence VALUES(?,?,?,?,?,?)',(common,target_claim,mapping[evidence],support,None,stamp))
                db.execute('INSERT INTO KnowledgeVersionClaim VALUES(?,?,?,?,?)',(common,version,target_claim,relation,stamp))
            db.execute("UPDATE KnowledgeVersion SET review_status='APPROVED',approved_by=?,approved_at=? WHERE version_id=?",(actor,stamp,version))
            db.execute('UPDATE KnowledgeItem SET current_version_id=? WHERE knowledge_id=?',(version,target))
            db.execute("INSERT INTO KnowledgeLineage VALUES(?,?,?,?,?,?,'PROMOTED_FROM',?)",(promotion,uid(),knowledge,promotion_row[0],target,version,stamp))
            db.execute('INSERT INTO ResourceRegistry VALUES(?,?,?,?,?,?)',(version,common,None,version,ref,ref));self._unit(db,common,text,version=version);self._generation(db,common)
            db.execute("UPDATE KnowledgePromotion SET target_knowledge_id=?,target_version_id=?,status='COMPLETED',updated_at=? WHERE promotion_id=?",(target,version,stamp,promotion))
            self._audit_change(db,actor,'COMPLETE_PROMOTION',project,{'promotion_id':promotion,'target_version_id':version});return {'version_id':version}
    def lineage(self,actor,version):
        with self.connection() as db:
            row=db.execute('SELECT space_id FROM KnowledgeVersion WHERE version_id=?',(version,)).fetchone()
            if not row:raise LookupError('Version unavailable')
            self._space(db,actor,row[0],'context.read' if row[0]!='common' else 'common.read')
            results=[]
            for source,space in db.execute('SELECT l.source_version_id,v.space_id FROM KnowledgeLineage l JOIN KnowledgeVersion v ON v.version_id=l.source_version_id WHERE l.target_version_id=?',(version,)):
                try:self._space(db,actor,space,'context.read')
                except AccessDenied:continue
                results.append({'source_version_id':source})
            return results

    def remember(self,actor,project,resource_id,conditions=None):
        conditions=conditions or {}
        if not isinstance(conditions,dict) or set(conditions)-{'task_kind'}:raise ValueError('Unknown memory condition')
        with self.connection(write=True) as db:
            self._check(db,actor,'memory.write',project);_,space=self._project(db,project)
            row=db.execute('SELECT space_id FROM ResourceRegistry WHERE resource_id=?',(resource_id,)).fetchone()
            if row!=(space,):raise AccessDenied('Memory resource scope mismatch')
            memory=uid();db.execute('INSERT INTO MemoryReference VALUES(?,?,?,?)',(memory,space,resource_id,canonical(conditions)))
            self._audit_change(db,actor,'SAVE_MEMORY_REFERENCE',project,{'memory_id':memory});return memory
    def memories(self,actor,project,task_kind=None):
        with self.connection() as db:
            self._check(db,actor,'memory.read',project);_,space=self._project(db,project)
            rows=db.execute('SELECT memory_id,resource_id,conditions FROM MemoryReference WHERE space_id=? ORDER BY memory_id',(space,)).fetchall()
            return [{'memory_id':m,'resource_id':r,'conditions':json.loads(c)} for m,r,c in rows if 'task_kind' not in json.loads(c) or json.loads(c)['task_kind']==task_kind]
    def reference_common(self,actor,project,knowledge_id,mode='LATEST',pinned_version=None):
        if mode not in ('PINNED','LATEST') or (mode=='PINNED')!=(pinned_version is not None):raise ValueError('Invalid reference shape')
        with self.connection(write=True) as db:
            self._check(db,actor,'knowledge.write',project);self._check(db,actor,'common.read',None);_,space=self._project(db,project)
            row=db.execute("SELECT k.current_version_id FROM KnowledgeItem k JOIN KnowledgeSpace s USING(space_id) WHERE k.knowledge_id=? AND s.space_type='COMMON' AND k.status='ACTIVE'",(knowledge_id,)).fetchone()
            if not row:raise AccessDenied('Eligible common knowledge required')
            version=pinned_version or row[0]
            if not db.execute("SELECT 1 FROM KnowledgeVersion WHERE knowledge_id=? AND version_id=? AND review_status='APPROVED'",(knowledge_id,version)).fetchone():raise AccessDenied('Approved reference target required')
            reference=uid();db.execute("INSERT INTO KnowledgeReference VALUES(?,?,?,?,?,'ACTIVE',?,?)",(reference,space,knowledge_id,mode,pinned_version,actor,now()))
            self._audit_change(db,actor,'REFERENCE_COMMON',project,{'reference_id':reference});return reference
    def resolve_reference(self,actor,project,reference,execution):
        with self.connection(write=True) as db:
            self._check(db,actor,'context.read',project);self._check(db,actor,'common.read',None);_,space=self._project(db,project)
            if not db.execute('SELECT 1 FROM Execution WHERE execution_id=? AND project_id=? AND actor_id=?',(execution,project,actor)).fetchone():raise AccessDenied('Execution scope mismatch')
            row=db.execute("SELECT r.reference_mode,r.pinned_version_id,k.current_version_id,k.knowledge_id FROM KnowledgeReference r JOIN KnowledgeItem k ON k.knowledge_id=r.target_knowledge_id JOIN KnowledgeSpace s ON s.space_id=k.space_id WHERE r.reference_id=? AND r.source_space_id=? AND r.status='ACTIVE' AND k.status='ACTIVE' AND s.space_type='COMMON'",(reference,space)).fetchone()
            if not row:raise AccessDenied('Reference unavailable')
            resolved=db.execute('SELECT version_id FROM ResolvedKnowledgeReference WHERE execution_id=? AND reference_id=?',(execution,reference)).fetchone()
            version=resolved[0] if resolved else (row[1] if row[0]=='PINNED' else row[2])
            target=db.execute("SELECT content_ref,content_hash FROM KnowledgeVersion WHERE version_id=? AND knowledge_id=? AND review_status='APPROVED'",(version,row[3])).fetchone()
            if not target:raise AccessDenied('Reference target no longer eligible')
            text=self.store.get(target[0]).decode()
            if not resolved:
                db.execute('INSERT INTO ResolvedKnowledgeReference VALUES(?,?,?,?)',(execution,reference,version,now()))
                self._audit_change(db,actor,'RESOLVE_REFERENCE',project,{'reference_id':reference,'version_id':version,'execution_id':execution})
            return {'version_id':version,'content':text,'hash':target[1]}
