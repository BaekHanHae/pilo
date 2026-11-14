"""Real SQLite/Core snapshot evaluation, evidence scoring and private export."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.practical_eval.harness import (aggregate, judge_answers, literal_context,
    retrieve_cases, scores, validate_tasks)


class PracticalEvaluationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.corpus = self.root / 'source'; self.corpus.mkdir()
        (self.corpus / 'service.py').write_text('def needle():\n    return "evidence"\n')
        (self.corpus / 'view.tsx').write_text('const frontendNeedle = "evidence";\n')
        (self.corpus / 'README.md').write_text('A disposable fixture.\n')
        self.tasks = [dict(id='T1', question='Find needle.', query='needle',
                           gold={'service.py': 'def needle():'}),
                      dict(id='T2', question='Find frontendNeedle.', query='frontendNeedle',
                           gold={'view.tsx': 'const frontendNeedle'})]

    def test_real_snapshot_replay_and_frontend_coverage(self):
        output = self.root / 'result'
        metadata = retrieve_cases(self.corpus, self.tasks, output)
        self.assertEqual(metadata['health'], 'ok')
        self.assertFalse(metadata['ai_execution_enabled'])
        with closing(sqlite3.connect(output / 'results.sqlite3')) as db:
            rows = db.execute("SELECT task_id,recall,snapshot_equal,evidence_valid,error FROM retrieval WHERE arm='pilo' ORDER BY task_id").fetchall()
            self.assertEqual(rows, [('T1',1.0,1,1,None), ('T2',1.0,1,1,None)])
        exported = aggregate(output / 'results.sqlite3')
        self.assertEqual(exported['literal']['mean_recall'], 1.0)
        self.assertNotIn('service.py', json.dumps(exported))
        self.assertNotIn('needle', json.dumps(exported))
        with self.assertRaises(FileExistsError): retrieve_cases(self.corpus, self.tasks, output)

    def test_literal_control_ignores_binary_cache_and_respects_byte_budget(self):
        cache = self.corpus / '__pycache__'; cache.mkdir()
        (cache / 'bad.pyc').write_bytes(b'\xff\x00')
        content, paths = literal_context(self.corpus, 'needle', 100)
        self.assertIn('service.py', paths)
        self.assertLessEqual(len(content.encode()), 100)
        content, paths = literal_context(self.corpus, 'needle', 1)
        self.assertEqual((content,paths), ('',[]))

    def test_exact_evidence_rejects_invention_missing_answers_and_traversal(self):
        valid = dict(task_id='T1',path='service.py',quote='def needle():')
        self.assertTrue(judge_answers([valid],self.tasks,self.corpus)[0]['evidence_success'])
        for change in (dict(quote='invented'), dict(path='../outside.py')):
            result = judge_answers([valid | change],self.tasks,self.corpus)
            self.assertFalse(result[0]['evidence_success'])
            self.assertFalse(result[1]['evidence_success'])
        with self.assertRaises(ValueError): judge_answers([valid,valid],self.tasks,self.corpus)

    def test_gold_must_match_snapshot_and_ids_be_unique(self):
        with self.assertRaises(ValueError): validate_tasks(self.tasks * 2,self.corpus)
        with self.assertRaises(ValueError): validate_tasks([self.tasks[0] | dict(gold={'service.py':'invented'})],self.corpus)
        self.assertEqual(scores(['other','service.py'], {'service.py':'anchor'})['reciprocal_rank'], 0.5)

    def test_patch_application_is_scoped_and_preserves_original(self):
        from tools.practical_eval.agents import apply_patch_copy
        before = (self.corpus / 'service.py').read_bytes()
        replacement = dict(path='service.py',old='return "evidence"',new='return "changed"')
        target = self.root / 'patched'
        result = apply_patch_copy(self.corpus,target,[replacement],{'service.py'})
        self.assertEqual(result['changed_files'],1)
        self.assertEqual((self.corpus / 'service.py').read_bytes(),before)
        self.assertIn('changed',(target / 'service.py').read_text())
        with self.assertRaises(ValueError):
            apply_patch_copy(self.corpus,self.root/'escaped',[replacement | dict(path='../secret.py')],{'service.py'})
        with self.assertRaises(ValueError):
            apply_patch_copy(self.corpus,self.root/'ambiguous',[replacement | dict(old='')],{'service.py'})

    def test_missing_agent_usage_remains_unknown_not_zero(self):
        from tools.practical_eval.agents import import_session
        from tools.practical_eval.harness import init_results
        dbpath = self.root / 'results.sqlite3'
        init_results(dbpath).close()
        events = self.root / 'events.jsonl'; events.write_text('{"type":"turn.failed"}\n')
        result = import_session(dbpath,arm='standard',events_path=events,
            answer_path=self.root/'missing.json',tasks=self.tasks,corpus=self.corpus)
        self.assertEqual(result['status'],'failed_or_incomplete')
        self.assertIsNone(result['usage'])
        with closing(sqlite3.connect(dbpath)) as db:
            self.assertEqual(db.execute('SELECT input_tokens,output_tokens FROM agent').fetchone(),(None,None))

    def test_session_preparation_keeps_gold_private_and_sources_identical(self):
        from tools.practical_eval.protocol import prepare_sessions
        contexts = {t['id']:dict(pilo='retrieved evidence') for t in self.tasks}
        output = prepare_sessions(self.corpus,self.tasks,contexts,self.root/'sessions')
        for arm in ('standard','pilo'):
            self.assertEqual((output/arm/'service.py').read_bytes(),(self.corpus/'service.py').read_bytes())
            self.assertNotIn('def needle():',(output/(arm+'.prompt.txt')).read_text())
        self.assertNotIn('retrieved evidence',(output/'standard.prompt.txt').read_text())
        self.assertNotIn('retrieved evidence',(output/'pilo.prompt.txt').read_text())
        legacy=prepare_sessions(self.corpus,self.tasks,contexts,self.root/'legacy',mode='legacy-bulk')
        self.assertIn('retrieved evidence',(legacy/'pilo.prompt.txt').read_text())

    def test_failed_test_summary_is_not_reported_as_green(self):
        from tools.practical_eval.agents import import_test_log
        from tools.practical_eval.harness import init_results
        db = self.root / 'tests.sqlite3'; init_results(db).close()
        log = self.root / 'test.log'; log.write_text('1 failed, 73 passed, 2 warnings in 4.29s\n')
        result = import_test_log(db,arm='pilo',scope='full',log_path=log)
        self.assertEqual(result,dict(passed=73,failed=1,complete=True))
        log.write_text('interrupted before summary\n')
        result = import_test_log(db,arm='pilo',scope='interrupted',log_path=log)
        self.assertIsNone(result['passed']); self.assertIsNone(result['failed'])
