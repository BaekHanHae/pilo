"""Explicit OS-operator provisioning. Never expose this module through MCP."""
from .core import now

# Exact permission inventory; no wildcard role or automatic grants.
PERMISSIONS=('ai.run','vector.read','graph.read','project.create','project.read','project.list','files.scan','context.read','common.read',
 'knowledge.write','knowledge.approve','knowledge.promote','common.write','checkpoint.create',
 'checkpoint.read','recovery.run','index.rebuild','skill.approve','code.run','execution.run','execution.read',
 'memory.write','memory.read','diagnostics.run','diagnostics.read','error.write','error.read','model.record','approval.request','approval.decide')

def provision(core,principal,permissions,project=None):
    if not isinstance(principal,str) or not principal or not set(permissions)<=set(PERMISSIONS) or not permissions:
        raise ValueError('Explicit known permissions and principal required')
    role='operator:'+principal+(':'+project if project else ':system');stamp=now()
    with core.connection(write=True) as db:
        if project and not db.execute('SELECT 1 FROM Project WHERE project_id=?',(project,)).fetchone():raise LookupError('Project unavailable')
        if not db.execute('SELECT 1 FROM Principal WHERE principal_id=?',(principal,)).fetchone():
            db.execute("INSERT INTO Principal VALUES(?,'USER',?,?,'ACTIVE',?,?)",(principal,principal,principal,stamp,stamp))
        db.execute('INSERT INTO Role VALUES(?,?,?,?,?) ON CONFLICT(role_id) DO NOTHING',(role,role,principal,None,stamp))
        db.execute('INSERT INTO PrincipalRole VALUES(?,?,?,?,?,?,?) ON CONFLICT(principal_role_id) DO NOTHING',(role,principal,role,'PROJECT' if project else 'SYSTEM',project,stamp,'system'))
        for permission in permissions:
            db.execute('INSERT INTO Permission VALUES(?,?,?,?) ON CONFLICT(permission_id) DO NOTHING',(permission,permission,'Explicit operator grant',stamp))
            db.execute('INSERT INTO RolePermission VALUES(?,?) ON CONFLICT DO NOTHING',(role,permission))
        core._verify_audit(db);core._audit(db,'system','OPERATOR_GRANT',project or 'system',{'principal_id':principal,'permissions':sorted(permissions),'project_id':project},stamp)
    return {'principal_id':principal,'permissions':sorted(permissions),'project_id':project}


def register_project(core,key,name,root):
    """OS-operator bootstrap only; no service receives project.create implicitly."""
    from pathlib import Path
    import uuid
    path=Path(root).resolve(strict=True)
    if not path.is_dir() or not isinstance(key,str) or not key.strip() or len(key)>128 or not name:
        raise ValueError('Valid root, key and name required')
    with core.connection(write=True) as db:
        existing=db.execute('SELECT project_id,root_path,status FROM Project WHERE project_key=?',(key,)).fetchone()
        if existing:
            if existing[1]!=str(path) or existing[2]!='ACTIVE':raise ValueError('Existing project identity differs')
            return {'project_id':existing[0],'created':False}
        project,space=str(uuid.uuid4()),str(uuid.uuid4());stamp=now()
        core._verify_audit(db)
        db.execute('INSERT INTO Project(project_id,project_key,name,root_path,created_at,updated_at) VALUES(?,?,?,?,?,?)',(project,key,name,str(path),stamp,stamp))
        db.execute("INSERT INTO KnowledgeSpace(space_id,space_type,project_id,name,created_at,updated_at) VALUES(?,'PROJECT',?,?,?,?)",(space,project,name,stamp,stamp))
        core._audit(db,'system','OPERATOR_REGISTER_PROJECT',project,{'project_key':key,'space_id':space,'root_path':str(path)},stamp)
        return {'project_id':project,'space_id':space,'created':True}
