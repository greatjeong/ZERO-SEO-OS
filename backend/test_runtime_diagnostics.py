import unittest
from central_runtime_diagnostics import runtime_summary

class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_classifies_missing_blank_reference_and_present_without_values(self):
        result = runtime_summary({'DATABASE_URL': '', 'PORT': '8080',
            'ZERO_CENTRAL_ORIGIN': '${{some.reference}}',
            'ZERO_OWNER_PASSWORD': 'never-print-this-password', 'UNRELATED': 'another-secret'})
        self.assertIn('"DATABASE_URL": "empty"', result)
        self.assertIn('"PORT": "present"', result)
        self.assertIn('"ZERO_OWNER_PASSWORD_HASH": "absent"', result)
        self.assertIn('"ZERO_CENTRAL_ORIGIN": "unresolved_reference"', result)
        for secret in ('8080', 'never-print-this-password', 'another-secret', 'some.reference', 'UNRELATED'):
            self.assertNotIn(secret, result)

    def test_missing_and_whitespace_are_distinct(self):
        self.assertIn('"DATABASE_URL": "absent"', runtime_summary({}))
        self.assertIn('"DATABASE_URL": "empty"', runtime_summary({'DATABASE_URL': '  '}))
