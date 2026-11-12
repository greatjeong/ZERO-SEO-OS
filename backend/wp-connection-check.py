"""Read-only WordPress authentication diagnostics; no credential storage."""
import base64
import getpass
import json
import re
import urllib.error
import urllib.request

BASE = 'https://a.webcreatorlabs.com'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    print('WordPress read-only connection check')
    username = input('WP username: ').strip()
    password = getpass.getpass('Application Password (hidden): ').strip()
    if not username or not password:
        print('RESULT: MISSING_USERNAME_OR_PASSWORD')
        return
    auth = base64.b64encode((username + ':' + password).encode()).decode('ascii')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for label, endpoint in [
        ('USER_VIEW', '/wp-json/wp/v2/users/me'),
        ('USER_EDIT', '/wp-json/wp/v2/users/me?context=edit'),
    ]:
        req = urllib.request.Request(BASE + endpoint, headers={
            'Authorization': 'Basic ' + auth,
            'Accept': 'application/json',
            'User-Agent': 'ZERO-SEO-OS/0.2.0',
        })
        try:
            response = opener.open(req, timeout=12)
        except urllib.error.HTTPError as error:
            response = error
        except Exception:
            print(label + ': NETWORK_OR_TLS_ERROR')
            continue
        with response:
            status = response.status
            raw = response.read(262145)
        try:
            data = json.loads(raw) if len(raw) <= 262144 else None
        except (ValueError, UnicodeError):
            data = None
        if not isinstance(data, dict):
            print(f'{label}: HTTP {status}; NON_JSON_RESPONSE')
            continue
        code = data.get('code')
        safe_code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', code) else 'NONE'
        valid_user = type(data.get('id')) is int and data['id'] > 0
        print(f'{label}: HTTP {status}; WP_CODE={safe_code}; AUTHENTICATED_USER={valid_user}')
    print('Done. Share only the USER_VIEW and USER_EDIT result lines.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled.')
