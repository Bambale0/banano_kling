import base64, hashlib, hmac, os, time, uuid, jwt
from cryptography.fernet import Fernet
from .settings import get_settings
def hash_password(p):
    salt=os.urandom(16); d=hashlib.pbkdf2_hmac('sha256',p.encode(),salt,200000)
    return 'pbkdf2$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(d).decode()
def verify_password(p, enc):
    try:
        _,s,d=enc.split('$',2); got=hashlib.pbkdf2_hmac('sha256',p.encode(),base64.b64decode(s),200000)
        return hmac.compare_digest(got,base64.b64decode(d))
    except Exception: return False
def create_token(uid, typ='access', ttl=3600):
    now=int(time.time()); return jwt.encode({'sub':uid,'type':typ,'iat':now,'exp':now+ttl,'jti':str(uuid.uuid4())}, get_settings().jwt_secret, algorithm='HS256')
def decode_token(t): return jwt.decode(t, get_settings().jwt_secret, algorithms=['HS256'])
def _fernet():
    key=get_settings().encryption_key or base64.urlsafe_b64encode(hashlib.sha256(get_settings().jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode())
def encrypt_secret(v): return _fernet().encrypt(v.encode()).decode()
def decrypt_secret(v): return _fernet().decrypt(v.encode()).decode()
def fingerprint(v): return hmac.new(get_settings().jwt_secret.encode(),v.encode(),hashlib.sha256).hexdigest()
