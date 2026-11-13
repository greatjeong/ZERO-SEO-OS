"""Read-only authentication check independent of ZERO connector transport."""
import base64
import json
import re
import secrets
import urllib.error
import urllib.request

BASE = 'https://a.webcreatorlabs.com'


def read_password():
    # Native masked entry supports ordinary Windows Ctrl+V without console key handling.
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        print('INPUT_WINDOW_ERROR: Python Tk window could not open. Nothing sent.')
        raise EOFError from None
    root.title('ZERO SEO OS - Application Password')
    root.resizable(False, False)
    root.attributes('-topmost', True)
    tk.Label(root, text='Paste the Application Password (not its name).', padx=20, pady=10).pack()
    value = tk.StringVar(root)
    entry = tk.Entry(root, textvariable=value, show='*', width=42)
    entry.pack(padx=20, pady=5)
    count = tk.StringVar(root)
    tk.Label(root, textvariable=count).pack(padx=20, pady=5)
    message = tk.StringVar(root, value='Expected: 24 letters / digits, spaces allowed.')
    tk.Label(root, textvariable=message).pack(padx=20, pady=5)
    result = []

    def update_count(*_args):
        compact = re.sub(r'\s+', '', value.get())
        count.set('Characters without spaces: ' + str(len(compact)) + ' / 24')

    def submit(_event=None):
        compact = re.sub(r'\s+', '', value.get())
        if re.fullmatch(r'[a-zA-Z0-9]{24}', compact) is None:
            message.set('Not 24 letters / digits yet. Clear the box and paste once.')
            return
        result.append(compact)
        value.set('')
        root.destroy()

    value.trace_add('write', update_count)
    update_count()
    tk.Button(root, text='Continue', command=submit).pack(padx=20, pady=12)
    root.bind('<Return>', submit)
    entry.focus_set()
    root.mainloop()
    if not result:
        raise EOFError('Cancelled')
    return result.pop()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(opener, label, endpoint, authorization=None):
    sep = '&' if '?' in endpoint else '?'
    headers = {'Accept': 'application/json', 'Cache-Control': 'no-cache',
               'User-Agent': 'ZERO-SEO-OS-ReadOnly-Check/1.0'}
    if authorization:
        headers['Authorization'] = authorization
    request = urllib.request.Request(BASE + endpoint + sep + '_zero_check=' + secrets.token_hex(6),
                                     headers=headers, method='GET')
    try:
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.status
            raw = response.read(1048577)
        data = json.loads(raw) if len(raw) <= 1048576 else None
        if not isinstance(data, dict):
            print(f'{label}: HTTP={status} JSON=False')
            return None
        code = data.get('code')
        code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', code) else 'NONE'
        authenticated = status == 200 and type(data.get('id')) is int and data['id'] > 0
        print(f'{label}: HTTP={status} CODE={code} AUTHENTICATED={authenticated}')
        return data if status == 200 else None
    except Exception:
        print(f'{label}: NETWORK_TLS_OR_JSON_ERROR')
        return None


def main():
    print('Read-only check: ' + BASE)
    print('No posts, settings, files, or server records will be changed.')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    root = check(opener, 'DISCOVERY', '/wp-json/')
    auth = root.get('authentication') if isinstance(root, dict) else None
    advertised = isinstance(auth, dict) and 'application-passwords' in auth
    print('APPLICATION_PASSWORDS_ADVERTISED=' + str(advertised))
    username = input('WordPress username: ').strip()
    print('A masked password window will open. Paste once and click Continue.')
    password = read_password()
    if not username or not password or ':' in username or any(c in username + password for c in '\r\n'):
        print('INPUT_ERROR: Missing or invalid credentials. Nothing sent.')
        return
    compact = re.sub(r'\s+', '', password)
    expected = re.fullmatch(r'[a-zA-Z0-9]{24}', compact) is not None
    print('INPUT_PASSWORD_SHAPE_EXPECTED=' + str(expected))
    if not expected:
        print('INPUT_ERROR: Expected a 24-character WordPress Application Password. Nothing sent.')
        return
    authorization = 'Basic ' + base64.b64encode(f'{username}:{compact}'.encode('utf-8')).decode('ascii')
    check(opener, 'ANONYMOUS', '/wp-json/wp/v2/users/me')
    check(opener, 'AUTH_VIEW', '/wp-json/wp/v2/users/me', authorization)
    identity = check(opener, 'AUTH_EDIT', '/wp-json/wp/v2/users/me?context=edit', authorization)
    if isinstance(identity, dict) and type(identity.get('id')) is int and identity['id'] > 0:
        print('USERNAME_MATCHES_CONNECTOR=' + str(identity.get('username') == username))
        caps = identity.get('capabilities')
        print('EDIT_POSTS=' + str(isinstance(caps, dict) and caps.get('edit_posts') is True))
    print('Done. Share only DISCOVERY / APPLICATION / INPUT_PASSWORD_SHAPE / ANONYMOUS / AUTH / USERNAME / EDIT result lines.')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled.')
    except Exception:
        print('CHECK_FAILED: Do not share credentials.')
