import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
import jwt

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310_000).hex()
    return f'pbkdf2_sha256$310000${salt}${digest}'

def verify_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split('$')
        value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(value, digest)
    except (ValueError, TypeError):
        return False

def token(user_id, settings):
    return jwt.encode({'sub': str(user_id), 'iat': datetime.now(timezone.utc), 'exp': datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)}, settings.jwt_secret, algorithm='HS256')
