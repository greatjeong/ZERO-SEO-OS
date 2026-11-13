import contextlib
import io
import os
import unittest
from unittest.mock import patch
import check_wordpress
import start_connector


class LauncherTests(unittest.TestCase):
    def test_dialog_password_reaches_only_child_environment(self):
        original = dict(os.environ)
        password = 'Ab12' * 6
        captured = {}
        def run(command, *, env):
            captured.update(env)
            self.assertEqual(command[1], '-u')
            return 0
        out = io.StringIO()
        with patch('builtins.input', side_effect=['https://example.com', 'editor', '']), patch.object(check_wordpress, 'read_password', return_value=password) as dialog, patch.object(start_connector.subprocess, 'call', side_effect=run) as launch, contextlib.redirect_stdout(out):
            self.assertEqual(start_connector.main(), 0)
        dialog.assert_called_once()
        self.assertEqual(captured['ZERO_WP_A1_APP_PASSWORD'], password)
        self.assertEqual(captured['ZERO_WP_A1_USER'], 'editor')
        self.assertEqual(launch.call_args.kwargs['env'], {})
        self.assertEqual(dict(os.environ), original)
        self.assertNotIn(password, out.getvalue())

    def test_dialog_cancel_never_starts_server(self):
        with patch('builtins.input', side_effect=['https://example.com', 'editor']), patch.object(check_wordpress, 'read_password', side_effect=EOFError), patch.object(start_connector.subprocess, 'call') as launch, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(EOFError):
                start_connector.main()
        launch.assert_not_called()
