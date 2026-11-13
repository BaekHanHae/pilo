"""Evidence verification tests independent of storage provider."""
import hashlib
import unittest

from pilo_core.ai_evidence import EvidenceRejected, verify_evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.data = b"trusted evidence bytes"
        self.digest = hashlib.sha256(self.data).hexdigest()

    def test_matching_bytes(self):
        result = verify_evidence("cas:one", self.digest, lambda ref: self.data)
        self.assertEqual(result.size_bytes, len(self.data))
        self.assertEqual(result.sha256, self.digest)

    def test_digest_mismatch(self):
        with self.assertRaises(EvidenceRejected):
            verify_evidence("cas:one", "0" * 64, lambda ref: self.data)

    def test_missing_reference(self):
        with self.assertRaises(EvidenceRejected):
            verify_evidence("", self.digest, lambda ref: self.data)

    def test_invalid_digest(self):
        with self.assertRaises(EvidenceRejected):
            verify_evidence("cas:one", "invalid", lambda ref: self.data)

    def test_reader_must_return_bytes(self):
        with self.assertRaises(EvidenceRejected):
            verify_evidence("cas:one", self.digest, lambda ref: "text")

    def test_size_limit(self):
        with self.assertRaises(EvidenceRejected):
            verify_evidence("cas:one", self.digest, lambda ref: self.data, max_bytes=2)

    def test_invalid_size_limit(self):
        with self.assertRaises(EvidenceRejected):
            verify_evidence("cas:one", self.digest, lambda ref: self.data, max_bytes=True)


if __name__ == "__main__":
    unittest.main()
