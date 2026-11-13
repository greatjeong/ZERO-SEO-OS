import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch
import check_wordpress as check


class ReadOnlyCheckTests(unittest.TestCase):
    def test_get_only_and_no_private_output(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = b'{"id":1,"email":"private@example.com","secret":"do-not-print"}'
        opener = MagicMock()
        opener.open.return_value = response
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            check.check(opener, 'AUTH_VIEW', '/wp-json/wp/v2/users/me', 'Basic test-only')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Authorization'), 'Basic test-only')
        self.assertNotIn('private@example.com', output.getvalue())
        self.assertNotIn('do-not-print', output.getvalue())
        self.assertIn('AUTHENTICATED=True', output.getvalue())

    def test_no_redirect(self):
        self.assertIsNone(check.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_invalid_password_not_sent(self):
        output = io.StringIO()
        with patch.object(check, 'check', return_value=None) as request, patch('builtins.input', return_value='editor'), patch.object(check, 'read_password', return_value='not-app-password'), contextlib.redirect_stdout(output):
            check.main()
        self.assertEqual(request.call_count, 1)  # Public discovery only.
        self.assertNotIn('not-app-password', output.getvalue())


    def test_valid_input_sent_only_to_fixed_target_without_logging(self):
        password = 'Ab12' * 6
        output = io.StringIO()
        with patch.object(check, 'check', return_value=None) as request, patch('builtins.input', return_value='editor'), patch.object(check, 'read_password', return_value=password), contextlib.redirect_stdout(output):
            check.main()
        self.assertEqual(request.call_count, 4)
        self.assertNotIn(password, output.getvalue())
        self.assertTrue(request.call_args_list[2].args[3].startswith('Basic '))

    def test_cancel_window_never_sends_credentials(self):
        with patch.object(check, 'check', return_value=None) as request, patch('builtins.input', return_value='editor'), patch.object(check, 'read_password', side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(EOFError):
                check.main()
        self.assertEqual(request.call_count, 1)
