from dataclasses import dataclass
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .db import connect, one
from .security import decode_token
bearer=HTTPBearer(auto_error=False)
@dataclass
class CurrentUser: id:str; email:str; is_superadmin:bool
def current_user(creds:HTTPAuthorizationCredentials|None=Depends(bearer)):
    if not creds: raise HTTPException(401, detail={'code':'unauthorized','message':'Нужен Bearer-токен'})
    try: payload=decode_token(creds.credentials)
    except Exception: raise HTTPException(401, detail={'code':'unauthorized','message':'Токен недействителен или истёк'})
    with connect() as c: u=one(c,"SELECT * FROM users WHERE id=? AND status='active'",(payload['sub'],))
    if not u: raise HTTPException(401, detail={'code':'unauthorized','message':'Пользователь не найден'})
    return CurrentUser(u['id'],u['email'],bool(u['is_superadmin']))
def require_member(tenant_id, user, roles=None):
    with connect() as c: m=one(c,"SELECT * FROM organization_members WHERE tenant_id=? AND user_id=? AND status='active'",(tenant_id,user.id))
    if not m and not user.is_superadmin: raise HTTPException(403, detail={'code':'forbidden','message':'Нет доступа к этому тенанту'})
    role='superadmin' if user.is_superadmin and not m else m['role']
    if roles and role not in roles and role!='superadmin': raise HTTPException(403, detail={'code':'forbidden','message':'Недостаточно прав'})
    return role
