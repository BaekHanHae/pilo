"""Fake CLI compatibility; no real agent, credential or production dispatch."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pilo_core.ai_cli_contract import AdapterContract, prepare_invocation, dispatch_ai


class CLIContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work = self.root / 'work'; self.work.mkdir()
        self.runtime = self.root / 'runtime'; self.runtime.mkdir(mode=0o700)
        self.fake = self.root / 'fake.py'
        self.fake.write_text('''import json,os,sys
payload=sys.stdin.buffer.read(2000001)
assert 'PILO_TEST_SECRET' not in os.environ
assert os.getcwd()==sys.argv[1]
assert os.environ['HOME']==sys.argv[2]
sys.stdout.buffer.write(payload)
''')
        binary = str(Path(sys.executable).resolve())
        self.contract = AdapterContract('fake-json', binary,
            hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            (str(self.fake), str(self.work.resolve()), str(self.runtime.resolve())))

    def prepare(self, **updates):
        return prepare_invocation(self.contract, **(dict(workspace=self.work,
            runtime_directory=self.runtime, payload=b'{"request":"test"}') | updates))

    def test_fake_json_and_text_cli_stdin_no_shell_or_inherited_secrets(self):
        from dataclasses import replace
        for fmt, payload in (('json-stdin-v1', b'{"request":"$(echo literal)"}'),
                             ('text-stdin-v1', b'literal $HOME; no shell')):
            self.contract = replace(self.contract, input_format=fmt)
            prepared = self.prepare(payload=payload)
            result = subprocess.run(prepared.argv, cwd=prepared.cwd,
                env=dict(prepared.environment), input=prepared.stdin,
                capture_output=True, timeout=prepared.timeout_seconds, check=True)
            self.assertEqual(result.stdout, payload)
            self.assertLessEqual(len(result.stdout), prepared.output_limit)

    def test_executable_substitution_and_budget_denied(self):
        from dataclasses import replace
        self.contract = replace(self.contract, executable_sha256='0'*64)
        with self.assertRaises(ValueError): self.prepare()

    def test_invalid_budgets_runtime_and_payload(self):
        for change in (dict(timeout_seconds=True), dict(output_limit=0),
                       dict(payload=b'x'*2_000_001), dict(payload=b'invalid json'),
                       dict(runtime_directory=self.work)):
            with self.assertRaises(ValueError): self.prepare(**change)

    def test_dispatch_is_unconditionally_disabled(self):
        with self.assertRaises(PermissionError): dispatch_ai(self.prepare())
