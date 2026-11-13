"""Interactive local launcher; credentials never written to disk."""
import ast
import os
from pathlib import Path
import subprocess
import sys


def main():
    if sys.version_info < (3, 11):
        print('ERROR: Python 3.11 or newer is required.')
        return 1
    server = Path(__file__).resolve().with_name('server.py')
    if not server.is_file():
        print('ERROR: Put these launcher files in the backend folder beside server.py.')
        return 1
    ast.parse(server.read_text(encoding='utf-8-sig'))
    print('ZERO SEO OS - local WordPress connector')
    print('Use a WordPress Application Password. Do not share it in chat.')
    # Reuse the masked dialog already verified by the read-only diagnostic.
    from check_wordpress import read_password
    env = os.environ.copy()
    try:
        for slot in ('A1', 'A2'):
            url = input(f'{slot} HTTPS URL (blank = skip): ').strip()
            if not url:
                continue
            user = input(f'{slot} WordPress username: ').strip()
            print(f'{slot}: Paste the Application Password into the masked window, then Continue.')
            password = read_password()
            prefix = f'ZERO_WP_{slot}_'
            env.update({prefix + 'URL': url, prefix + 'USER': user,
                        prefix + 'APP_PASSWORD': password})
        print('Starting connector at http://127.0.0.1:8765 - keep this window open.', flush=True)
        return subprocess.call([sys.executable, '-u', str(server)], env=env)
    finally:
        # Credentials existed only in this process and its child.
        env.clear()


if __name__ == '__main__':
    try:
        code = main()
    except (KeyboardInterrupt, EOFError):
        print('\nStopped.')
        code = 0
    except Exception:
        # Avoid dumping entered values or environment data.
        print('ERROR: Launcher failed. Check Python 3.11+, server.py, and updated check_wordpress.py in backend.')
        code = 1
    sys.exit(code)
