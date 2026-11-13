"""Owner-only password hashes. No plaintext password is persisted."""
import hashlib
import hmac
import re
import secrets


def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('Use a password of 12 to 256 characters.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1,
                            maxmem=256 * 1024 * 1024, dklen=32)
    return 'scrypt$' + salt.hex() + '$' + digest.hex()


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r'scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}', value) is not None


def verify_password(password, encoded):
    if not valid_hash(encoded) or not isinstance(password, str) or not 1 <= len(password) <= 256:
        return False
    _, salt, expected = encoded.split('$')
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1,
                            maxmem=256 * 1024 * 1024, dklen=32)
    return hmac.compare_digest(digest.hex(), expected)


if __name__ == '__main__':
    import getpass
    password = getpass.getpass('New central owner password (hidden): ')
    confirmation = getpass.getpass('Confirm (hidden): ')
    if password != confirmation:
        raise SystemExit('Passwords did not match.')
    print(hash_password(password))
