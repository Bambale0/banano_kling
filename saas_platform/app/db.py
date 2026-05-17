import json, sqlite3, uuid
from contextlib import contextmanager
from pathlib import Path
from .settings import get_settings
def new_id(): return str(uuid.uuid4())
def dumps(v): return json.dumps(v if v is not None else {}, ensure_ascii=False)
def loads(v, default=None):
    if v in (None,''): return {} if default is None else default
    return json.loads(v) if isinstance(v,str) else v
def _path():
    url=get_settings().database_url
    if url.startswith('sqlite:///'): return url[10:]
    if url.startswith('sqlite://'): return url[9:]
    return './saas.db'
@contextmanager
def connect():
    path=_path()
    if path != ':memory:': Path(path).parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(path, check_same_thread=False); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
    try: yield c; c.commit()
    except Exception: c.rollback(); raise
    finally: c.close()
def one(c, sql, params=()):
    r=c.execute(sql, tuple(params)).fetchone(); return dict(r) if r else None
def many(c, sql, params=()): return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]
def seed(c):
    for code,name,price,goe,limits,features,order in [
        ('free','Free',0,100,{'max_bots':1,'max_products':20,'monthly_generations':50},{'shop':True,'analytics':True},1),
        ('pro','Pro',4990,5000,{'max_bots':10,'max_products':1000,'monthly_generations':5000},{'shop':True,'analytics':True,'custom_branding':True},2)]:
        c.execute('INSERT OR IGNORE INTO plans(id,code,name,description,price_amount,included_goe,limits,features,sort_order) VALUES(?,?,?,?,?,?,?,?,?)',(new_id(),code,name,'Тариф 2Loop SaaS',price,goe,dumps(limits),dumps(features),order))
def init_db():
    with connect() as c:
        c.executescript((Path(__file__).resolve().parent.parent/'sql/sqlite_schema.sql').read_text()); seed(c)
