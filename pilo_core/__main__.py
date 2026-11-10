"""Trusted local CLI. Do not expose this operator interface as an MCP tool."""
import argparse
import json
import sys
import sqlite3
from pathlib import Path
from .core import Core


def main():
    parser = argparse.ArgumentParser(description='PILO-Core local operator interface')
    parser.add_argument('--config', default=str(Path.cwd() / 'database_config.json'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('list')
    search = sub.add_parser('search')
    search.add_argument('--project',required=True);search.add_argument('--query',required=True)
    init = sub.add_parser('init'); init.add_argument('--directory', required=True)
    setup = sub.add_parser('add-project')
    for field in ('key','name','root'):setup.add_argument('--'+field,required=True)
    setup.add_argument('--principal',default='pilo-reader')
    sub.add_parser('upgrade')
    sub.add_parser('serve')
    grant = sub.add_parser('grant')
    grant.add_argument('--principal', required=True)
    grant.add_argument('--permissions', required=True, help='Comma-separated exact permission keys')
    grant.add_argument('--project')
    workspace = sub.add_parser('workspace')
    workspace.add_argument('action')
    workspace.add_argument('--actor', required=True)
    workspace.add_argument('--arguments', default='{}', help='JSON object of named method arguments')
    backup = sub.add_parser('backup'); backup.add_argument('destination')
    listing = sub.add_parser('projects'); listing.add_argument('--actor', required=True)
    create = sub.add_parser('create-project')
    for field in ('actor', 'key', 'name', 'root'):
        create.add_argument('--' + field, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            from .bootstrap import initialize
            print(json.dumps(initialize(args.directory),indent=2));return 0
        if args.command == 'add-project':
            from .setup import add_project
            print(json.dumps(add_project(args.config,args.key,args.name,args.root,args.principal),indent=2));return 0
        if args.command == 'upgrade':
            from .migrations import upgrade
            print(json.dumps(upgrade(args.config), indent=2))
            return 0
        if args.command == 'serve':
            from .mcp_server import serve
            serve(args.config)
            return 0
        core = Core(args.config)
        if args.command in ('list','search'):
            from .workspace import Workspace
            workspace=Workspace(args.config);actor=workspace.config.get('mcp_principal','system')
            projects=workspace.accessible_projects(actor)
            if args.command=='list':result=projects
            else:
                matches=[p for p in projects['projects'] if args.project in (p['project_id'],p['project_key'])]
                if len(matches)!=1:raise LookupError('Readable project not found')
                result=workspace.retrieve(actor,matches[0]['project_id'],args.query)
        elif args.command == 'grant':
            from .operator import provision
            result = provision(core, args.principal, args.permissions.split(','), args.project)
        elif args.command == 'workspace':
            from .workspace import Workspace
            allowed = {'semantic_context','analyze_snapshot','graph_project','scan', 'retrieve', 'snapshot', 'rebuild_index', 'save_knowledge',
                       'activate_knowledge', 'add_evidence', 'request_promotion', 'apply_promotion',
                       'lineage', 'remember', 'memories', 'reference_common', 'resolve_reference', 'request_approval', 'decide_approval', 'revoke_approval',
                       'register_skill', 'create_plan', 'scheduler_tick', 'execution_detail',
                       'cancel_execution', 'create_checkpoint', 'verify_checkpoint', 'recovery_context',
                       'recover', 'diagnostics', 'record_error', 'error_cases', 'save_resolution',
                       'metrics', 'record_model_invocation'}
            if args.action not in allowed:
                raise ValueError('Unknown workspace action')
            arguments = json.loads(args.arguments)
            if not isinstance(arguments, dict) or 'actor' in arguments:
                raise ValueError('Named arguments object required; use trusted --actor')
            result = getattr(Workspace(args.config), args.action)(args.actor, **arguments)
        elif args.command == 'doctor': result = core.health()
        elif args.command == 'backup': result = core.backup(args.destination)
        elif args.command == 'projects': result = core.list_projects(args.actor)
        else: result = core.create_project(args.actor, args.key, args.name, args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, LookupError, sqlite3.DatabaseError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
