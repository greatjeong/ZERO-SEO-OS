"""Read-only diagnostics sharing the connector's URL, TLS, and SSRF protections."""
import getpass
from server import normalize_url, request_identity


def main():
    url = normalize_url(input('WordPress HTTPS URL: '))
    username = input('WP username: ').strip()
    password = getpass.getpass('Application Password (hidden): ')
    if not username or not password or ':' in username or any(c in username + password for c in '\r\n'):
        print('RESULT: INVALID_CONFIGURATION')
        return
    try:
        request_identity(url, username, password)
        print('RESULT: AUTHENTICATED_USER=True')
    except Exception:
        print('RESULT: AUTHENTICATION_OR_NETWORK_FAILURE')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, ValueError):
        print('Cancelled or invalid URL.')
