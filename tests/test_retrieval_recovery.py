"""Real Core/SQLite retrieval quality, source integrity and on-demand contracts."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

from pilo_core import AccessDenied, ConfigurationError
from pilo_core.bootstrap import initialize
from pilo_core.operator import provision, register_project
from pilo_core.setup import add_project
from pilo_core.workspace import Workspace
from pilo_core.retrieval import rank_rows, diversified, excerpt


class RetrievalRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.source = self.root/'source'; self.source.mkdir()
        self.state = self.root/'state'

    def install(self, files):
        for name, text in files.items():
            path = self.source/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text)
        initialize(self.state); self.config = self.state/'database_config.json'
        registered = add_project(self.config,'sample','Sample',self.source)
        self.core = Workspace(self.config); self.project = registered['project_id']
        return registered

    def rescan(self):
        provision(self.core,'indexer',['files.scan'],self.project)
        self.core.scan('indexer',self.project)

    def search(self, query, **kwargs):
        return self.core.search_evidence('pilo-reader',self.project,query,**kwargs)

    def get(self, units, query='needle', **kwargs):
        return self.core.get_evidence('pilo-reader',self.project,units,query,**kwargs)

    def test_reference_survives_many_large_reports_under_budget(self):
        self.install({'reference/architecture.md':'Snapshot contract authoritative definition',
            **{f'reports/{n:02}.md':('Snapshot repeated report data.\n'*1800) for n in range(8)}})
        result = self.core.retrieve('pilo-reader',self.project,'Snapshot',max_tokens=4096)
        self.assertIn('[reference/architecture.md]',result['content'])
        self.assertLessEqual(result['context_bytes'],4096)
        self.assertEqual(self.core.snapshot('pilo-reader',result['snapshot_id'])['content'],result['content'])
        self.assertEqual(self.search('Snapshot',limit=1)['items'][0]['source'],'reference/architecture.md')

    def test_query_terms_find_noncontiguous_identifiers_and_frontend(self):
        self.install({'ui/view.tsx':'function renderPage() { return provider_config; }',
                      'unrelated.py':'pass'})
        for query in ('render page','provider config','ui/view.tsx'):
            self.assertEqual(self.search(query,limit=1)['items'][0]['source'],'ui/view.tsx')
        self.assertEqual(self.search('nonexistent')['items'],[])

    def test_frontend_ingestion_preserves_secret_binary_symlink_exclusions(self):
        self.install({'ui/a.ts':'needle types','ui/b.tsx':'needle view','ui/c.js':'needle js',
            'ui/d.jsx':'needle jsx','ui/e.css':'needle css','ui/f.html':'needle markup',
            'ui/g.svg':'<svg>needle</svg>','ui/secret.ts':'api_key=abcdefghijklmno',
            'node_modules/vendor.ts':'needle vendor'})
        (self.source/'bad.ts').write_bytes(b'\xff\x00')
        (self.source/'link.ts').symlink_to(self.root/'outside.ts')
        self.rescan()
        with self.core.connection() as db:
            paths={r[0] for r in db.execute("SELECT logical_path FROM FileAsset WHERE status='ACTIVE'")}
        self.assertEqual(len(paths),7)
        self.assertFalse(any('secret' in path or 'vendor' in path or 'link' in path or 'bad' in path for path in paths))

    def test_source_diversity_then_multiple_units_from_same_source(self):
        self.install({'a.md':'needle '+('x'*1993)+'\nneedle '+('y'*1980), 'b.md':'needle b'})
        result = self.core.retrieve('pilo-reader',self.project,'needle',max_tokens=8192)
        sources=[row['source'] for row in result['evidence']]
        self.assertEqual(set(sources[:2]),{'a.md','b.md'})
        self.assertGreater(sources.count('a.md'),1)

    def test_stable_rank_ignores_random_ids_and_input_order(self):
        rows=[('z','s','needle','hash1','source.py',None,0),
              ('a','s','needle','hash2','source.py',None,1)]
        self.assertEqual(rank_rows(rows,'needle'),['z','a'])
        self.assertEqual(rank_rows(list(reversed(rows)),'needle'),['z','a'])
        self.assertEqual(diversified(['z','a'],{r[0]:r for r in rows}),['z','a'])

    def test_explicit_path_ranks_ahead_of_mentions(self):
        self.install({'README.md':'See ui/view.tsx. '*100,'ui/view.tsx':'actual implementation'})
        self.assertEqual(self.search('ui/view.tsx',limit=1)['items'][0]['source'],'ui/view.tsx')

    def test_read_only_search_returns_no_body_or_snapshot_and_does_not_write(self):
        self.install({'main.py':'needle confidential source body'})
        with self.core.connection() as db:
            before=db.execute('SELECT count(*) FROM AuditEvent').fetchone()[0]
        found=self.search('needle'); self.assertFalse(found['content_included'])
        self.assertNotIn('confidential',json.dumps(found)); self.assertNotIn('content',found)
        with self.core.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM AuditEvent').fetchone()[0],before)
            self.assertEqual(db.execute('SELECT count(*) FROM ContextSnapshot').fetchone()[0],0)

    def test_small_utf8_evidence_has_exact_offsets_hashes_and_replays_after_rescan(self):
        text='앞문장\n'*350+'needle 실제 근거\n'+('뒤문장\n'*300)
        self.install({'large.py':text})
        found=self.search('needle',limit=1)['items'][0]
        result=self.get([found['unit_id']],max_bytes=512)
        self.assertIn('needle',result['content']); self.assertLessEqual(result['context_bytes'],512)
        evidence=result['evidence'][0]
        self.assertEqual(evidence['source_sha256'],hashlib.sha256(text.encode()).hexdigest())
        selected=text[evidence['char_start']:evidence['char_end']]
        self.assertIn(selected,result['content'])
        (self.source/'large.py').write_text('changed current source');self.rescan()
        self.assertEqual(self.core.snapshot('pilo-reader',result['snapshot_id'])['content'],result['content'])
        with self.assertRaises(AccessDenied):self.get([found['unit_id']])

    def test_source_cas_corruption_rejected_even_with_intact_snapshot_body(self):
        self.install({'source.py':'needle trustworthy source'})
        handle=self.search('needle')['items'][0]; saved=self.get([handle['unit_id']])
        (self.core.store.root/handle['source_sha256']).write_bytes(b'substituted source')
        with self.assertRaises(ConfigurationError):self.core.snapshot('pilo-reader',saved['snapshot_id'])

    def test_handles_never_cross_projects_and_revoked_permission_blocks_replay(self):
        self.install({'a.py':'needle evidence'})
        handle=self.search('needle')['items'][0]; saved=self.get([handle['unit_id']])
        other=self.root/'other';other.mkdir()
        project=register_project(self.core,'other','Other',other)['project_id']
        provision(self.core,'other-reader',['project.read','context.read'],project)
        with self.assertRaises(AccessDenied):self.core.get_evidence('other-reader',project,[handle['unit_id']],'needle')
        with self.core.connection(write=True) as db:
            db.execute("UPDATE Principal SET status='DISABLED' WHERE principal_id='pilo-reader'")
        with self.assertRaises(AccessDenied):self.core.snapshot('pilo-reader',saved['snapshot_id'])

    def test_mandatory_units_are_never_silently_dropped_or_truncated(self):
        self.install({'a.py':'needle'})
        provision(self.core,'writer',['knowledge.write','knowledge.approve'],self.project)
        draft=self.core.save_knowledge('writer',self.project,'Rule',('mandatory rule '*800),'RULE')
        self.core.activate_knowledge('writer',draft['version_id'])
        handle=self.search('needle')['items'][0]
        with self.assertRaises(ValueError):self.get([handle['unit_id']],max_bytes=256)
        with self.core.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ContextSnapshot').fetchone()[0],0)

    def test_budget_and_handle_validation_and_query_punctuation(self):
        self.install({'a.py':'needle source'})
        handle=self.search('needle')['items'][0]['unit_id']
        for size in (True,0,255,8193):
            with self.assertRaises(ValueError):self.get([handle],max_bytes=size)
        for ids in ([],[handle,handle],['unknown']):
            with self.assertRaises((ValueError,AccessDenied)):self.get(ids)
        self.assertIsInstance(self.search('needle " OR --')['items'],list)
        with self.assertRaises(ValueError):self.core.retrieve('pilo-reader',self.project,'needle',max_tokens=True)

    def test_excerpt_never_splits_utf8_and_uses_real_character_offsets(self):
        text='한글\n'*100+'needle\n'+'尾'*200
        piece,start,end=excerpt(text,'needle',64)
        self.assertEqual(piece,text[start:end]);self.assertIn('needle',piece)
        self.assertLessEqual(len(piece.encode()),64)

    def test_actual_cli_and_mcp_on_demand_contracts(self):
        self.install({'frontend.ts':'needle source'})
        def cli(*args):
            result=subprocess.run([sys.executable,'-m','pilo_core','--config',str(self.config),*args],
                                  capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);return json.loads(result.stdout)
        search=cli('evidence-search','--project','sample','--query','needle')
        handle=search['items'][0]['unit_id']
        evidence=cli('evidence','--project','sample','--query','needle','--unit-id',handle,'--max-bytes','512')
        self.assertIn('needle',evidence['content'])
        from pilo_core.mcp_server import Server,ProtocolError,META,MODERN
        server=Server(self.core);meta={META+'protocolVersion':MODERN,META+'clientCapabilities':{}}
        def call(name,arguments):
            return server.dispatch({'jsonrpc':'2.0','id':1,'method':'tools/call',
                'params':dict(name=name,arguments=arguments,_meta=meta)})
        self.assertFalse(call('pilo_search_evidence',dict(project_id=self.project,query='needle'))['isError'])
        self.assertFalse(call('pilo_get_evidence',dict(project_id=self.project,query='needle',unit_ids=[handle]))['isError'])
        with self.assertRaises(ProtocolError):call('pilo_get_evidence',dict(project_id=self.project,query='needle',unit_ids=[{}]))

    def test_old_cache_is_not_reused_and_new_cache_order_is_repeatable(self):
        self.install({'reference.md':'needle trusted text','other.md':'needle other text'})
        first=self.core.retrieve('pilo-reader',self.project,'needle')
        second=self.core.retrieve('pilo-reader',self.project,'needle')
        self.assertTrue(second['cache_hit']);self.assertEqual(first['content'],second['content'])
        with self.core.connection() as db:
            payloads=[json.loads(row[0]) for row in db.execute('SELECT candidates FROM QueryCache')]
        self.assertTrue(payloads)
        from unittest.mock import patch
        with patch('pilo_core.workspace.RANKER_VERSION','different-version'):
            third=self.core.retrieve('pilo-reader',self.project,'needle')
        self.assertFalse(third['cache_hit']);self.assertEqual(first['content'],third['content'])

    def test_many_mandatory_units_are_not_limited_by_candidate_prefix(self):
        rows=[(str(i),'space','rule','hash'+str(i),'Rule '+str(i),'RULE',i) for i in range(130)]
        self.assertEqual(len(rank_rows(rows,'unrelated query')),130)
        selected=diversified(rank_rows(rows,'unrelated query'),{row[0]:row for row in rows})
        self.assertEqual(len(selected),130)

    def test_evidence_metadata_and_snapshot_items_are_immutable(self):
        import sqlite3
        self.install({'a.py':'needle preserved source'})
        handle=self.search('needle')['items'][0]; saved=self.get([handle['unit_id']])
        with self.core.connection(write=True) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM ContextSnapshotItem WHERE snapshot_id=?',(saved['snapshot_id'],))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE ContextSnapshot SET context_hash=? WHERE snapshot_id=?',('0'*64,saved['snapshot_id']))
        self.assertEqual(self.core.health()['status'],'ok')
