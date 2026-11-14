"""Regression checks for AI gateway public annotation references.

These checks do not activate AI execution, schema migrations, or adapters.
"""
from __future__ import annotations

import unittest
from typing import get_type_hints

from pilo_core.ai_core_gate import AIBinding
from pilo_core.ai_finalize import finalize_ai_attempt


class AnnotationContractTests(unittest.TestCase):
    def test_finalize_public_hints_resolve(self) -> None:
        hints = get_type_hints(finalize_ai_attempt)
        self.assertEqual(hints["binding"], AIBinding | None)
        self.assertEqual(hints["return"], type(None))


if __name__ == "__main__":
    unittest.main()
