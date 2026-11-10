"""RBAC cannot be widened by policies, manifests, cached data or caller identity fields."""
import hashlib
import json
from .core import AccessDenied, canonical, now


def policy_hash(db):
    return hashlib.sha256(canonical(db.execute('SELECT policy_id,policy_type,effect,parameters,status,updated_at FROM AccessPolicy ORDER BY policy_id').fetchall()).encode()).hexdigest()


def has_permission(db,actor,permission,project):
    return bool(db.execute("""SELECT 1 FROM Principal p JOIN PrincipalRole pr ON pr.principal_id=p.principal_id
        JOIN RolePermission rp ON rp.role_id=pr.role_id JOIN Permission r ON r.permission_id=rp.permission_id
        WHERE p.principal_id=? AND p.status='ACTIVE' AND r.permission_key=? AND
        ((pr.scope_type='SYSTEM' AND pr.scope_id IS NULL) OR (pr.scope_type='PROJECT' AND pr.scope_id=?))""",(actor,permission,project)).fetchone())


def scope_hash(db,actor,spaces):
    roles=db.execute('SELECT role_id,scope_type,scope_id FROM PrincipalRole WHERE principal_id=? ORDER BY role_id,scope_type,scope_id',(actor,)).fetchall()
    return hashlib.sha256(canonical([actor,roles,spaces,policy_hash(db)]).encode()).hexdigest()


def authorize(core,db,actor,permission,project=None,approval_id=None,context=None):
    if project and permission in ('files.scan','knowledge.write','knowledge.approve','execution.run'):
        lease=db.execute('SELECT lease_expires_at FROM RecoveryLease WHERE project_id=?',(project,)).fetchone()
        if lease:
            import time
            if lease[0]>time.time():raise AccessDenied('Project is locked for recovery')
    if not has_permission(db,actor,permission,project):
        raise AccessDenied('Permission denied')
    for kind,effect,raw in db.execute("SELECT policy_type,effect,parameters FROM AccessPolicy WHERE status='ACTIVE' ORDER BY priority DESC,policy_id"):
        params=json.loads(raw)
        allowed={'actions','projects','principals','classification'}
        if not isinstance(params,dict) or set(params)-allowed:
            raise AccessDenied('Unsupported policy parameters')
        for key in ('actions','projects','principals'):
            if key in params and (not isinstance(params[key],list) or not all(isinstance(x,str) for x in params[key])):
                raise AccessDenied('Invalid policy selector')
        if 'actions' in params and permission not in params['actions']: continue
        if 'principals' in params and actor not in params['principals']: continue
        if 'projects' in params and project not in params['projects']: continue
        if effect=='DENY' or kind=='DENY_EXTERNAL_TRANSFER' and permission.endswith('.export'):
            raise AccessDenied('Policy denied operation')
        if kind=='RESOURCE_CLASSIFICATION' and params.get('classification') not in (None,'PUBLIC','INTERNAL'):
            raise AccessDenied('Restricted classification')
        if effect=='REQUIRE_APPROVAL':
            validate_approval(db,actor,permission,project,approval_id,context)
    return True


def approval_context(db,action,project,resource):
    return {'action':action,'project_id':project,'resource':resource,'policy_hash':policy_hash(db)}


def validate_approval(db,actor,action,project,approval_id,resource):
    if not approval_id or resource is None: raise AccessDenied('Approval required')
    expected=approval_context(db,action,project,resource)
    row=db.execute("""SELECT r.status,r.action,r.approval_context_hash,r.expires_at,g.project_id,g.context_json,g.revoked_at,d.decided_by,r.requested_by
       FROM ApprovalRequest r JOIN ApprovalGrant g USING(approval_id) JOIN ApprovalDecision d USING(approval_id)
       WHERE r.approval_id=? AND d.decision='APPROVE'""",(approval_id,)).fetchone()
    if not row or row[0]!='APPROVED' or row[1]!=('PROMOTE' if action=='knowledge.promote' else action) or row[4]!=project or row[6] is not None or row[8]!=actor:
        raise AccessDenied('Invalid approval')
    if row[3] is None or row[3]<=now() or row[2]!=hashlib.sha256(canonical(expected).encode()).hexdigest() or json.loads(row[5])!=expected:
        raise AccessDenied('Expired or changed approval context')
    if not has_permission(db,row[7],'approval.decide',project): raise AccessDenied('Approver authority revoked')
