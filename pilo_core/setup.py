"""Explicit local setup, never exported as an MCP operation."""
import json
import os
from pathlib import Path
import tempfile
import uuid
from .workspace import Workspace
from .operator import provision, register_project


def add_project(config, key, name, root, principal='pilo-reader'):
    core=Workspace(config)
    if not principal or principal=='system':raise ValueError('A dedicated reader identity is required')
    project=register_project(core,key,name,root)['project_id']
    provision(core,principal,['project.read','context.read'],project)
    indexer='setup-indexer:'+str(uuid.uuid4())
    provision(core,indexer,['files.scan'],project)
    try:
        scan=core.scan(indexer,project)
    finally:
        with core.connection(write=True) as db:
            db.execute("UPDATE Principal SET status='DISABLED' WHERE principal_id=?",(indexer,))
            core._audit_change(db,'system','DISABLE_SETUP_INDEXER',project,{'principal_id':indexer})
    value=dict(core.config,mcp_principal=principal,mcp_allow_writes=False,
        mcp_enabled_tools=['pilo_list_projects','pilo_get_project','pilo_get_context','pilo_get_snapshot','pilo_search_evidence','pilo_get_evidence'])
    path=Path(config).resolve();fd,staged=tempfile.mkstemp(dir=path.parent,prefix='.setup-')
    try:
        with os.fdopen(fd,'w') as output:
            json.dump(value,output,indent=2);output.flush();os.fsync(output.fileno())
        os.replace(staged,path)
    finally:Path(staged).unlink(missing_ok=True)
    return {'project_id':project,'principal_id':principal,'indexed_files':scan['files'],
        'excluded_files':scan['excluded'],'config_path':str(path),'mcp_allow_writes':False}
