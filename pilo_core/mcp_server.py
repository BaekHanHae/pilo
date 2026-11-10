"""Local stdio MCP adapter. Identity is fixed by trusted server configuration."""
from concurrent.futures import ThreadPoolExecutor
import threading
import argparse
import json
import sys
from .workspace import Workspace
from . import __version__
from .core import AccessDenied,canonical

MODERN='2026-07-28'
LEGACY='2025-11-25'
LEGACY_COMPAT='2025-06-18'
SUPPORTED_VERSIONS=[MODERN,LEGACY,LEGACY_COMPAT]
META='io.modelcontextprotocol/'

def schema(properties,required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
STR={'type':'string','minLength':1,'maxLength':1000}
PROJECT={'project_id':STR}
TOOLS={
 'pilo_semantic_context':('Search authorized evidence using local embeddings',schema(dict(PROJECT,query=STR,max_tokens={'type':'integer','minimum':1,'maximum':16000}),('project_id','query')),'semantic_context',False),
 'pilo_analyze_snapshot':('Analyze preserved evidence with local Ollama; output requires review',schema(dict(PROJECT,snapshot_id=STR,question=STR),('project_id','snapshot_id','question')),'analyze_snapshot',False),
 'pilo_graph_project':('Extract structural Python relations using local Graphify',schema(dict(PROJECT,query={'type':'string','maxLength':1000}),PROJECT),'graph_project',False),
 'pilo_list_projects':('List only projects currently readable by this server identity',schema({}),'accessible_projects',False),
 'pilo_get_project':('Read one authorized project',schema(PROJECT,PROJECT),'get_project',False),
 'pilo_scan_project':('Scan allowed text files and update derived context',schema(PROJECT,PROJECT),'scan',True),
 'pilo_get_context':('Build authorized immutable context',schema(dict(PROJECT,query=STR,max_tokens={'type':'integer','minimum':1,'maximum':32768},idempotency_key=STR,execution_id=STR),('project_id','query')),'retrieve',False),
 'pilo_get_snapshot':('Read preserved context using current permissions',schema({'snapshot_id':STR},('snapshot_id',)),'snapshot',False),
 'pilo_get_execution':('Read an authorized execution',schema({'execution_id':STR},('execution_id',)),'execution_detail',False),
 'pilo_scheduler_tick':('Run at most one approved CODE step',schema({'execution_id':STR},('execution_id',)),'scheduler_tick',True),
 'pilo_cancel_execution':('Cancel an execution and fence old workers',schema({'execution_id':STR},('execution_id',)),'cancel_execution',True),
 'pilo_run_diagnostics':('Run a predefined diagnostic profile',schema(dict(PROJECT,profile={'type':'string','enum':['database','content-integrity','environment']}),PROJECT),'diagnostics',False),
 'pilo_search_errors':('Search authorized redacted error occurrences',schema(dict(PROJECT,query={'type':'string','maxLength':1000}),PROJECT),'error_cases',False),
 'pilo_create_checkpoint':('Preserve a clean-worktree checkpoint',schema(PROJECT,PROJECT),'create_checkpoint',True),
 'pilo_verify_checkpoint':('Verify checkpoint manifest and objects',schema({'checkpoint_id':STR},('checkpoint_id',)),'verify_checkpoint',False),
}

class ProtocolError(Exception):
    def __init__(self,code,message,data=None):self.code,self.message,self.data=code,message,data

def validate(arguments,definition):
    if not isinstance(arguments,dict) or set(arguments)-set(definition['properties']) or set(definition['required'])-set(arguments):raise ProtocolError(-32602,'Invalid tool arguments')
    for key,value in arguments.items():
        rules=definition['properties'][key]
        if rules['type']=='string' and (not isinstance(value,str) or len(value)<rules.get('minLength',0) or len(value)>rules.get('maxLength',10000)):raise ProtocolError(-32602,'Invalid string argument')
        if rules['type']=='integer' and (isinstance(value,bool) or not isinstance(value,int) or not rules.get('minimum',0)<=value<=rules.get('maximum',32768)):raise ProtocolError(-32602,'Invalid integer argument')
        if 'enum' in rules and value not in rules['enum']:raise ProtocolError(-32602,'Invalid enum argument')

class Server:
    def __init__(self,workspace):
        self.workspace=workspace;self.actor=workspace.config.get('mcp_principal');self.legacy_initialized=False
        if not self.actor:raise ValueError('Set trusted mcp_principal in operator configuration')
    def dispatch(self,message):
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or not isinstance(message.get('method'),str):raise ProtocolError(-32600,'Invalid JSON-RPC request')
        if 'id' not in message:return None
        request_id=message['id']
        if isinstance(request_id,bool) or not isinstance(request_id,(str,int)):raise ProtocolError(-32600,'Invalid request ID')
        method=message['method'];params=message.get('params',{})
        if not isinstance(params,dict):raise ProtocolError(-32602,'Parameters must be an object')
        meta=params.get('_meta',{})
        if not isinstance(meta,dict):raise ProtocolError(-32602,'Invalid request metadata')
        version=meta.get(META+'protocolVersion')
        modern=version is not None
        if modern:
            if version!=MODERN:raise ProtocolError(-32022,'Unsupported protocol version',{'supported':SUPPORTED_VERSIONS,'requested':version})
            if not isinstance(meta.get(META+'clientCapabilities'),dict):raise ProtocolError(-32602,'Client capabilities metadata required')
        elif method=='initialize':
            requested=params.get('protocolVersion')
            if not isinstance(requested,str):raise ProtocolError(-32602,'protocolVersion must be a string')
            negotiated=requested if requested in (LEGACY,LEGACY_COMPAT) else LEGACY
            self.legacy_initialized=True
            return {'protocolVersion':negotiated,'capabilities':{'tools':{},'resources':{},'prompts':{}},'serverInfo':{'name':'pilo-local','version':__version__}}
        elif not self.legacy_initialized:raise ProtocolError(-32600,'Initialize or modern metadata required')
        result=self.handle(method,params)
        if modern:
            result=dict(result,resultType='complete')
            if method in ('tools/list','resources/list','resources/templates/list','prompts/list'):
                result.update(cacheScope='private',ttlMs=0)
        return result
    def handle(self,method,params):
        if method=='server/discover':return {'supportedVersions':SUPPORTED_VERSIONS,'capabilities':{'tools':{},'resources':{},'prompts':{}},'_meta':{META+'serverInfo':{'name':'pilo-local','version':__version__}}}
        if method=='ping':return {}
        if method=='tools/list':
            return {'tools':[{'name':name,'description':item[0],'inputSchema':item[1],'annotations':{'readOnlyHint':not item[3],'openWorldHint':False}} for name,item in sorted(TOOLS.items()) if name in self.workspace.config.get('mcp_enabled_tools',TOOLS)]}
        if method=='tools/call':
            if set(params)-{'name','arguments','_meta'}:raise ProtocolError(-32602,'Unknown call property')
            name=params.get('name');arguments=params.get('arguments',{})
            if name not in TOOLS or name not in self.workspace.config.get('mcp_enabled_tools',TOOLS):raise ProtocolError(-32602,'Unknown tool')
            _,definition,target,writes=TOOLS[name];validate(arguments,definition)
            if writes and self.workspace.config.get('mcp_allow_writes') is not True:
                return {'content':[{'type':'text','text':'Applying tools disabled by operator configuration'}],'isError':True}
            remap={'project_id':'project','execution_id':'execution','checkpoint_id':'checkpoint'}
            if target in ('retrieve','snapshot'):remap={'project_id':'project'}
            values={remap.get(k,k):v for k,v in arguments.items()}
            try:
                value=getattr(self.workspace,target)(self.actor,**values)
                if value is None:value={'status':'COMPLETED'}
                if not isinstance(value,dict):value={'items':value}
                return {'content':[{'type':'text','text':canonical(value)}],'structuredContent':value,'isError':False}
            except (PermissionError,LookupError,ValueError,RuntimeError,OSError) as exc:
                # Domain failure details stay local; no source snippets or filesystem paths in errors.
                return {'content':[{'type':'text','text':type(exc).__name__}],'structuredContent':{'code':type(exc).__name__,'retryable':False},'isError':True}
        if method=='resources/list':return {'resources':[]}
        if method=='resources/templates/list':return {'resourceTemplates':[{'uriTemplate':'pilo://project/{project_id}','name':'Project overview','mimeType':'application/json'}]}
        if method=='resources/read':
            uri=params.get('uri','');prefix='pilo://project/'
            if not isinstance(uri,str) or not uri.startswith(prefix):raise ProtocolError(-32602,'Unknown resource')
            project=uri[len(prefix):]
            if not project or '/' in project or '?' in project:raise ProtocolError(-32602,'Invalid project resource')
            value=self.workspace.get_project(self.actor,project)
            return {'contents':[{'uri':uri,'mimeType':'application/json','text':canonical(value)}]}
        if method=='prompts/list':return {'prompts':[{'name':'pilo-start-task','description':'Retrieve fresh authorized project context before working','arguments':[{'name':'project_id','required':True}]}]}
        if method=='prompts/get':
            if params.get('name')!='pilo-start-task':raise ProtocolError(-32602,'Unknown prompt')
            arguments=params.get('arguments',{});validate(arguments,schema(PROJECT,PROJECT))
            self.workspace.get_project(self.actor,arguments['project_id'])
            return {'messages':[{'role':'user','content':{'type':'text','text':'Use pilo_get_context for project '+arguments['project_id']+'; preserve source references and disclose insufficient context.'}}]}
        raise ProtocolError(-32601,'Method not found')

def serve(config,source=sys.stdin,target=sys.stdout):
    server=Server(Workspace(config));lock=threading.Lock();active={}
    def respond(message,cancelled=None):
        try:
            result=server.dispatch(message)
            if result is None:return
            response={'jsonrpc':'2.0','id':message['id'],'result':result}
        except ProtocolError as exc:
            if isinstance(message,dict) and 'id' not in message:return
            response={'jsonrpc':'2.0','error':{'code':exc.code,'message':exc.message}}
            if isinstance(message,dict) and 'id' in message:response['id']=message['id']
            if exc.data is not None:response['error']['data']=exc.data
        except Exception:
            response={'jsonrpc':'2.0','id':message.get('id') if isinstance(message,dict) else None,'error':{'code':-32603,'message':'Internal error'}}
        with lock:
            if cancelled is None or not cancelled.is_set():target.write(canonical(response)+'\n');target.flush()
            if cancelled is not None and isinstance(message,dict):
                entry=active.get(message.get('id'))
                if entry and entry[0] is cancelled:active.pop(message['id'],None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            raw=source.readline(1_048_577)
            if not raw:break
            if len(raw.encode())>1_048_576:
                target.write(canonical({'jsonrpc':'2.0','error':{'code':-32600,'message':'Message too large'}})+'\n');target.flush();break
            try:message=json.loads(raw)
            except json.JSONDecodeError:
                with lock:target.write(canonical({'jsonrpc':'2.0','error':{'code':-32700,'message':'Parse error'}})+'\n');target.flush()
                continue
            if isinstance(message,dict) and message.get('method')=='notifications/cancelled' and 'id' not in message:
                params=message.get('params',{});request_id=params.get('requestId') if isinstance(params,dict) else None
                with lock:
                    entry=active.get(request_id) if isinstance(request_id,(str,int)) else None
                    if entry:entry[0].set()
                if entry:
                    original=entry[1].get('params',{})
                    if original.get('name')=='pilo_scheduler_tick':
                        try:server.workspace.cancel_execution(server.actor,original.get('arguments',{}).get('execution_id'))
                        except Exception:pass
                continue
            if isinstance(message,dict) and message.get('method')=='tools/call' and isinstance(message.get('id'),(str,int)):
                event=threading.Event();request_id=message['id']
                with lock:
                    # A completed request may reuse its id; outstanding requests may not.
                    previous=active.get(request_id)
                    if previous and not previous[2].done():
                        target.write(canonical({'jsonrpc':'2.0','id':request_id,'error':{'code':-32600,'message':'Duplicate outstanding request ID'}})+'\n');target.flush();continue
                    future=pool.submit(respond,message,event);active[request_id]=(event,message,future)
            else:respond(message)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args();serve(args.config)
