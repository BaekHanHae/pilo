import json
import math
import unittest
from unittest.mock import patch
import test_workspace as fixtures
from pilo_core.core import AccessDenied
from pilo_core.extensions import vectors
from pilo_core.mcp_server import Server
from pilo_core.operator import provision

class ExtensionTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    dbconn=fixtures.WorkspaceTests.dbconn
    def configure(self):
        self.core.config['extensions']={'enabled':True,'generation_model':'fixture','embedding_model':'fixture'}
        provision(self.core,'system',['ai.run','model.record','vector.read','graph.read'],self.p)
    def test_embedding_validation(self):
        for value in ([[0,0]],[[float('nan'),1]],[[True,1]],[[1],[1,2]],[]):
            with self.assertRaises(ValueError):vectors({'embeddings':value},1)
        self.assertEqual(vectors({'embeddings':[[3,4]]},1),[[.6,.8]])
    def test_semantic_snapshot_and_revision(self):
        self.configure();self.core.scan('system',self.p)
        with patch('pilo_core.extensions.ollama',return_value={'embeddings':[[1,0],[1,0]]}):
            result=self.core.semantic_context('system',self.p,'different words')
        self.assertIn('atomic snapshot',result['content'])
        (self.project/'readme.md').write_text('changed');self.core.scan('system',self.p)
        self.assertEqual(self.core.snapshot('system',result['snapshot_id'])['content'],result['content'])
    def test_no_unauthorized_model_calls(self):
        self.core.config['extensions']={'enabled':True,'embedding_model':'fixture'};self.core.scan('system',self.p)
        with patch('pilo_core.extensions.ollama') as call:
            with self.assertRaises(AccessDenied):self.core.semantic_context('system',self.p,'anything')
            call.assert_not_called()
    def test_ai_records_usage_and_artifact(self):
        self.configure();self.core.scan('system',self.p);snap=self.core.retrieve('system',self.p,'snapshot')
        response={'response':json.dumps({'answer':'Evidence','citations':['readme.md']}),'done':True,'prompt_eval_count':12,'eval_count':4,'total_duration':1}
        with patch('pilo_core.extensions.ollama',return_value=response):
            result=self.core.analyze_snapshot('system',self.p,snap['snapshot_id'],'explain')
        self.assertEqual(result['validation'],'UNREVIEWED_MODEL_OUTPUT')
        self.assertEqual(json.loads(self.core.store.get(result['artifact_ref']))['answer'],'Evidence')
        with self.dbconn() as db:self.assertEqual(db.execute('SELECT context_snapshot_id FROM ModelInvocation WHERE invocation_id=?',(result['invocation_id'],)).fetchone()[0],snap['snapshot_id'])
    def test_ai_cross_project_and_incomplete_rejected(self):
        self.configure();self.core.scan('system',self.p);snap=self.core.retrieve('system',self.p,'snapshot')
        with patch('pilo_core.extensions.ollama') as call:
            with self.assertRaises(AccessDenied):self.core.analyze_snapshot('system','other',snap['snapshot_id'],'explain')
            call.assert_not_called()
        with patch('pilo_core.extensions.ollama',return_value={'done':False,'response':'partial'}):
            with self.assertRaises(ValueError):self.core.analyze_snapshot('system',self.p,snap['snapshot_id'],'explain')
    def test_revocation_after_inference(self):
        self.configure();self.core.scan('system',self.p);snap=self.core.retrieve('system',self.p,'snapshot')
        def infer(*args,**kwargs):
            with self.dbconn() as db:db.execute("UPDATE Principal SET status='DISABLED' WHERE principal_id='system'")
            return {'done':True,'response':json.dumps({'answer':'answer','citations':['readme.md']}),'prompt_eval_count':1,'eval_count':1}
        with patch('pilo_core.extensions.ollama',side_effect=infer):
            with self.assertRaises(AccessDenied):self.core.analyze_snapshot('system',self.p,snap['snapshot_id'],'explain')
    def test_mcp_extensions_discovered_and_failure_safe(self):
        self.core.config['mcp_principal']='system';server=Server(self.core)
        names=[t['name'] for t in server.handle('tools/list',{})['tools']]
        self.assertTrue({'pilo_semantic_context','pilo_analyze_snapshot','pilo_graph_project'}<=set(names))
        result=server.handle('tools/call',{'name':'pilo_semantic_context','arguments':{'project_id':self.p,'query':'x'}})
        self.assertTrue(result['isError']);self.assertNotIn(str(self.root),str(result))
    def test_graph_real_python_evidence(self):
        from pathlib import Path
        executable=Path(fixtures.ROOT/'extensions/graphify-env/bin/python')
        if not executable.is_file():
            import importlib.util,sys
            if importlib.util.find_spec('graphify') is None:self.skipTest('Graphify optional environment unavailable')
            executable=Path(sys.executable)
        self.configure();self.core.config['extensions']['graphify_python']=str(executable)
        (self.project/'module.py').write_text('def helper():\n return 1\ndef run():\n return helper()\n')
        self.core.scan('system',self.p);result=self.core.graph_project('system',self.p,'helper')
        self.assertGreater(result['node_count'],0);self.assertGreater(result['edge_count'],0)
        self.assertTrue(result['nodes'])
        self.assertTrue(any(e.get('relation')=='calls' and 'helper' in e.get('target','') for e in result['edges']))
        for node in result['nodes']:
            if node.get('source_file'):self.assertIn('content_hash',node['evidence'])
        artifact=json.loads(self.core.store.get(result['artifact_ref']))
        self.assertNotIn(str(self.root),json.dumps(artifact))
        self.assertEqual(set(artifact['sources']),{'module.py'})
    def test_graph_denied_before_subprocess(self):
        self.core.config['extensions']={'enabled':True,'graphify_python':'/usr/bin/python3'}
        with patch('pilo_core.extensions.subprocess.run') as call:
            with self.assertRaises(AccessDenied):self.core.graph_project('system',self.p)
            call.assert_not_called()
    def test_model_connection_failure_preserves_snapshot(self):
        self.configure();self.core.scan('system',self.p);snap=self.core.retrieve('system',self.p,'snapshot')
        with patch('pilo_core.extensions.ollama',side_effect=TimeoutError('unavailable')):
            with self.assertRaises(TimeoutError):self.core.analyze_snapshot('system',self.p,snap['snapshot_id'],'explain')
        self.assertEqual(self.core.snapshot('system',snap['snapshot_id'])['content'],snap['content'])

    def test_modern_catalog_cache_contract(self):
        from pilo_core.mcp_server import MODERN,META
        self.core.config['mcp_principal']='system';server=Server(self.core)
        result=server.dispatch({'jsonrpc':'2.0','id':1,'method':'tools/list','params':{'_meta':{META+'protocolVersion':MODERN,META+'clientCapabilities':{}}}})
        self.assertEqual(result['ttlMs'],0);self.assertEqual(result['cacheScope'],'private')
    def test_ai_invalid_citation_and_truncation(self):
        self.configure();self.core.scan('system',self.p);snap=self.core.retrieve('system',self.p,'snapshot')
        for citations,reason in [(['invented.md'],'stop'),(['readme.md'],'length')]:
            response={'done':True,'done_reason':reason,'response':json.dumps({'answer':'answer','citations':citations}),'prompt_eval_count':1,'eval_count':1}
            with patch('pilo_core.extensions.ollama',return_value=response):
                with self.assertRaises(ValueError):self.core.analyze_snapshot('system',self.p,snap['snapshot_id'],'explain')
    def test_mcp_server_enforces_allowlist(self):
        from pilo_core.mcp_server import ProtocolError
        self.core.config.update(mcp_principal='system',mcp_enabled_tools=['pilo_list_projects']);server=Server(self.core)
        self.assertEqual([x['name'] for x in server.handle('tools/list',{})['tools']],['pilo_list_projects'])
        with self.assertRaises(ProtocolError):server.handle('tools/call',{'name':'pilo_scan_project','arguments':{'project_id':self.p}})
