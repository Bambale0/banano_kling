#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="2loop.chillcreative.ru"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIAPP_DIR="$PROJECT_ROOT/miniapp"
STATIC_MINIAPP_DIR="$PROJECT_ROOT/static/miniapp"
DATA_DIR="${TWOLOOP_DATA_DIR:-/root/2loop/data}"
UPLOAD_DIR="$PROJECT_ROOT/static/uploads/2loop"
MAIN_PY="$PROJECT_ROOT/bot/main.py"
NGINX_AVAILABLE="/etc/nginx/sites-available/$DOMAIN"
NGINX_ENABLED="/etc/nginx/sites-enabled/$DOMAIN"

log() { printf '\033[1;36m[2loop]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[2loop][warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[2loop][error]\033[0m %s\n' "$*"; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Command not found: $1"
}

patch_main_py() {
  log "Patching bot/main.py for Mini App API routes..."
  [[ -f "$MAIN_PY" ]] || fail "bot/main.py not found: $MAIN_PY"

  python3 - <<'PY'
from pathlib import Path
p = Path('bot/main.py')
s = p.read_text(encoding='utf-8')

if 'from bot.miniapp_api import setup_miniapp_routes' not in s:
    marker = 'from bot.services.preset_manager import preset_manager\n'
    if marker not in s:
        raise SystemExit('Import marker not found in bot/main.py')
    s = s.replace(marker, marker + 'from bot.miniapp_api import setup_miniapp_routes\n')

if 'setup_miniapp_routes(app)' not in s:
    candidates = [
        'app = web.Application()\n',
        'app = web.Application(client_max_size=1024**3)\n',
        'app = web.Application(client_max_size=1024 * 1024 * 1024)\n',
    ]
    for c in candidates:
        if c in s:
            s = s.replace(c, c + '    setup_miniapp_routes(app)\n', 1)
            break
    else:
        # Fallback: inject immediately before first app.router.add_* usage inside main setup.
        marker = 'app.router.'
        idx = s.find(marker)
        if idx == -1:
            raise SystemExit('Could not find web.Application or app.router marker in bot/main.py')
        line_start = s.rfind('\n', 0, idx) + 1
        indent = s[line_start:idx]
        s = s[:line_start] + indent + 'setup_miniapp_routes(app)\n' + s[line_start:]

if 'app.router.add_static("/static/", path="static", name="static")' not in s and "app.router.add_static('/static/', path='static', name='static')" not in s:
    marker = 'setup_miniapp_routes(app)\n'
    if marker in s:
        s = s.replace(marker, marker + '    app.router.add_static("/static/", path="static", name="static")\n', 1)

p.write_text(s, encoding='utf-8')
PY
}

write_miniapp() {
  log "Creating Mini App frontend in miniapp/..."
  mkdir -p "$MINIAPP_DIR/src" "$STATIC_MINIAPP_DIR" "$UPLOAD_DIR" "$DATA_DIR"

  cat > "$MINIAPP_DIR/package.json" <<'JSON'
{
  "name": "2loop-miniapp",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 0.0.0.0",
    "build": "vite build",
    "preview": "vite preview --host 0.0.0.0"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "typescript": "latest",
    "react": "latest",
    "react-dom": "latest",
    "framer-motion": "latest"
  },
  "devDependencies": {}
}
JSON

  cat > "$MINIAPP_DIR/index.html" <<'HTML'
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#0D0F14" />
    <title>2loop</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
HTML

  cat > "$MINIAPP_DIR/src/api.js" <<'JS'
const API_BASE = '/api/miniapp';

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const tg = window.Telegram?.WebApp;
  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed: ${response.status}`);
  return data;
}

export const api = {
  health: () => request('/health'),
  products: (includeInactive = false) => request(`/products${includeInactive ? '?include_inactive=1' : ''}`),
  product: (id) => request(`/products/${id}`),
  createProduct: (payload) => request('/products', { method: 'POST', body: payload }),
  updateProduct: (id, payload) => request(`/products/${id}`, { method: 'PUT', body: payload }),
  deleteProduct: (id) => request(`/products/${id}`, { method: 'DELETE' }),
  uploadImage: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return request(`/products/${id}/images`, { method: 'POST', body: form });
  },
  settings: () => request('/settings'),
  updateSettings: (payload) => request('/settings', { method: 'PUT', body: payload }),
  promo: (payload) => request('/promo', { method: 'POST', body: payload }),
  createOrder: (payload) => request('/orders', { method: 'POST', body: payload }),
  orders: () => request('/orders'),
};
JS

  cat > "$MINIAPP_DIR/src/main.jsx" <<'JS'
import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from './api.js';
import './styles.css';

const fallbackProducts = [
  {
    id: 1,
    article: '2LOOP-001',
    name: 'Crystal Hair Loop',
    category: 'Hair',
    price: 2900,
    stock: 12,
    badge: 'Bestseller',
    description: 'A refined crystal hair accessory for competition-ready styling.',
    details: 'Hand-finished shine, lightweight hold, suitable for competition hairstyles.',
    images: ['https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=900&q=80'],
    mainImageIndex: 0,
    active: true,
  },
];

const categories = ['All', 'Hair', 'Gloves', 'Bags', 'Blade Care', 'Gifts', 'Competition'];
const nav = ['Home', 'Catalog', 'Saved', 'Cart', 'Profile', 'Admin'];

function fmt(value) { return `${Number(value || 0).toLocaleString('ru-RU')} ₽`; }
function mainImage(product) { return product.images?.[product.mainImageIndex || 0] || product.images?.[0] || ''; }
function icon(label) {
  const map = { Home: '✦', Catalog: '⌕', Saved: '♡', Cart: '◈', Profile: '◌', Admin: '⚙' };
  return map[label] || '•';
}

function App() {
  const tg = window.Telegram?.WebApp;
  const [tab, setTab] = useState('Home');
  const [theme, setTheme] = useState('dark');
  const [products, setProducts] = useState(fallbackProducts);
  const [cart, setCart] = useState([]);
  const [gallery, setGallery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    tg?.ready?.();
    tg?.expand?.();
    Promise.allSettled([api.products(true), api.settings()])
      .then(([productsResult, settingsResult]) => {
        if (productsResult.status === 'fulfilled') setProducts(productsResult.value.products || []);
        if (settingsResult.status === 'fulfilled') setTheme(settingsResult.value.settings?.theme || 'dark');
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const cartCount = cart.reduce((sum, item) => sum + item.qty, 0);
  const cartItems = cart.map((item) => ({ ...products.find((p) => p.id === item.productId), qty: item.qty })).filter(Boolean);

  async function refreshProducts(includeInactive = tab === 'Admin') {
    const data = await api.products(includeInactive);
    setProducts(data.products || []);
  }

  async function saveTheme(nextTheme) {
    setTheme(nextTheme);
    await api.updateSettings({ theme: nextTheme });
  }

  function addToCart(product) {
    setCart((current) => {
      const exists = current.find((item) => item.productId === product.id);
      if (exists) return current.map((item) => item.productId === product.id ? { ...item, qty: item.qty + 1 } : item);
      return [...current, { productId: product.id, qty: 1 }];
    });
    tg?.HapticFeedback?.impactOccurred?.('light');
  }

  return (
    <div className={`app ${theme}`}>
      <div className="glow g1" /><div className="glow g2" />
      <main className="shell">
        <header className="header">
          <div><div className="eyebrow">Figure Skating Boutique</div><h1>2loop</h1></div>
          <div className="head-actions">
            <button onClick={() => saveTheme(theme === 'dark' ? 'light' : 'dark')} className="circle">{theme === 'dark' ? '☀' : '☾'}</button>
            <button onClick={() => setTab('Cart')} className="circle accent">◈{cartCount ? <b>{cartCount}</b> : null}</button>
          </div>
        </header>

        {loading ? <Empty title="Loading storefront" text="Preparing catalog..." /> : null}
        {error ? <Empty title="API warning" text={error} /> : null}
        {!loading && tab === 'Home' ? <Home products={products.filter(p => p.active !== false)} setTab={setTab} openGallery={setGallery} addToCart={addToCart} /> : null}
        {!loading && tab === 'Catalog' ? <Catalog products={products.filter(p => p.active !== false)} openGallery={setGallery} addToCart={addToCart} /> : null}
        {!loading && tab === 'Saved' ? <Saved products={products.filter(p => p.active !== false).slice(0, 3)} openGallery={setGallery} addToCart={addToCart} /> : null}
        {!loading && tab === 'Cart' ? <Cart items={cartItems} setCart={setCart} tg={tg} /> : null}
        {!loading && tab === 'Profile' ? <Profile tg={tg} /> : null}
        {!loading && tab === 'Admin' ? <Admin products={products} setProducts={setProducts} refreshProducts={refreshProducts} theme={theme} saveTheme={saveTheme} /> : null}

        <nav className="bottom-nav">
          {nav.map((item) => <button key={item} onClick={() => setTab(item)} className={tab === item ? 'active' : ''}><span>{icon(item)}</span>{item}{item === 'Cart' && cartCount ? <i>{cartCount}</i> : null}</button>)}
        </nav>
      </main>
      <Gallery gallery={gallery} onClose={() => setGallery(null)} addToCart={addToCart} />
    </div>
  );
}

function Home({ products, setTab, openGallery, addToCart }) {
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}}>
    <div className="hero"><div className="pill">✦ New season edit</div><h2>Graceful details for every performance.</h2><p>Premium accessories selected for training, competition and the skating lifestyle.</p><button onClick={() => setTab('Catalog')} className="primary">Shop collection →</button></div>
    <Section title="Curated collections"><div className="collections"><Card title="Competition Day" text="Elegant details for the big performance" /><Card title="Training Essentials" text="Daily accessories selected for comfort" /><Card title="Gift Picks" text="Beautiful choices for young skaters" /></div></Section>
    <Section title="New arrivals"><div className="grid">{products.slice(0,4).map((p,i)=><Product key={p.id} product={p} index={i} openGallery={openGallery} addToCart={addToCart}/>)}</div></Section>
    <div className="ai"><b>AI stylist picks</b><p>Get a refined set of accessories for training, competitions or a gift.</p><button>Create selection →</button></div>
  </motion.section>;
}

function Catalog({ products, openGallery, addToCart }) {
  const [cat, setCat] = useState('All'); const [q, setQ] = useState('');
  const shown = useMemo(() => products.filter(p => (cat === 'All' || p.category === cat) && `${p.name} ${p.category}`.toLowerCase().includes(q.toLowerCase())), [products, cat, q]);
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><h2>Catalog</h2><p>Find refined accessories for training, competitions and gifts.</p><input className="search" value={q} onChange={e=>setQ(e.target.value)} placeholder="Search accessories"/><div className="chips">{categories.map(c=><button key={c} onClick={()=>setCat(c)} className={cat===c?'on':''}>{c}</button>)}</div>{shown.length?<div className="grid">{shown.map((p,i)=><Product key={p.id} product={p} index={i} openGallery={openGallery} addToCart={addToCart}/>)}</div>:<Empty title="Nothing found" text="Try another category."/>}</motion.section>;
}

function Saved(props) { return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><h2>Saved</h2><p>Your favorite pieces for later decisions and gift planning.</p><div className="grid">{props.products.map((p,i)=><Product key={p.id} product={p} index={i} {...props}/>)}</div></motion.section>; }

function Cart({ items, setCart, tg }) {
  const subtotal = items.reduce((s,i)=>s+i.price*i.qty,0); const delivery = subtotal >= 5000 ? 0 : 350; const total = subtotal + delivery;
  function qty(id, d){ setCart(cur=>cur.map(i=>i.productId===id?{...i,qty:Math.max(1,i.qty+d)}:i)); }
  async function checkout(){ const order = await api.createOrder({ telegramUser: tg?.initDataUnsafe?.user, items: items.map(i=>({productId:i.id,qty:i.qty})) }); alert(`Заказ #${order.order.id} создан`); }
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><h2>Cart</h2>{!items.length?<Empty title="Cart is empty" text="Add something beautiful."/>:<>{items.map(i=><div className="cart-row" key={i.id}><img src={mainImage(i)}/><div><b>{i.name}</b><p>{fmt(i.price)}</p><div><button onClick={()=>qty(i.id,-1)}>-</button><span>{i.qty}</span><button onClick={()=>qty(i.id,1)}>+</button></div></div></div>)}<div className="summary"><p><span>Subtotal</span><b>{fmt(subtotal)}</b></p><p><span>Delivery</span><b>{delivery?fmt(delivery):'Free'}</b></p><h3><span>Total</span><b>{fmt(total)}</b></h3><button onClick={checkout} className="primary wide">Checkout</button></div></>}</motion.section>;
}

function Profile({ tg }) { const user = tg?.initDataUnsafe?.user; return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><div className="profile"><div className="avatar">◌</div><div><span>2loop member</span><h2>{user?.first_name || 'Skater Profile'}</h2><p>360 bonus points</p></div></div><Menu title="Orders" text="Track purchases and history"/><Menu title="Delivery" text="Addresses and shipping options"/><Menu title="Loyalty" text="Bonuses, gifts and offers"/><Menu title="Support" text="Telegram help and returns"/></motion.section>; }

function Admin({ products, setProducts, refreshProducts, theme, saveTheme }) {
  const [selectedId, setSelectedId] = useState(products[0]?.id); const selected = products.find(p=>p.id===selectedId) || products[0];
  async function add(){ const r = await api.createProduct({ name:'New Product', category:'Hair', price:2500, stock:1, badge:'Draft', active:true, images:[] }); await refreshProducts(true); setSelectedId(r.product.id); }
  async function patch(payload){ const r = await api.updateProduct(selected.id, payload); setProducts(cur=>cur.map(p=>p.id===selected.id?r.product:p)); }
  async function upload(file){ if(!file) return; const r = await api.uploadImage(selected.id, file); setProducts(cur=>cur.map(p=>p.id===selected.id?r.product:p)); }
  if(!selected) return <Empty title="No products" text="Create first product."/>;
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><div className="admin-head"><div><h2>Admin</h2><p>Products, photos, stock and theme.</p></div><button onClick={add} className="primary">Add</button></div><div className="admin-stats"><Card title={products.length} text="Products"/><Card title={products.reduce((s,p)=>s+Number(p.stock||0),0)} text="Stock"/><Card title={products.filter(p=>Number(p.stock||0)<=5).length} text="Low"/></div><div className="editor"><label>Theme <button onClick={()=>saveTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?'Switch light':'Switch dark'}</button></label></div><div className="strip">{products.map(p=><button key={p.id} onClick={()=>setSelectedId(p.id)} className={p.id===selected.id?'sel':''}><img src={mainImage(p)}/><b>{p.name}</b><small>{p.stock} pcs · {fmt(p.price)}</small></button>)}</div><div className="editor"><Field label="Name" value={selected.name} on={v=>patch({name:v})}/><Field label="Category" value={selected.category} on={v=>patch({category:v})}/><Field label="Badge" value={selected.badge} on={v=>patch({badge:v})}/><Field label="Price" type="number" value={selected.price} on={v=>patch({price:Number(v)})}/><Field label="Stock" type="number" value={selected.stock} on={v=>patch({stock:Number(v)})}/><Area label="Description" value={selected.description} on={v=>patch({description:v})}/><Area label="Details" value={selected.details} on={v=>patch({details:v})}/><label className="upload">Upload photo<input type="file" accept="image/*" onChange={e=>upload(e.target.files?.[0])}/></label><div className="photos">{(selected.images||[]).map((img,idx)=><div key={img+idx}><img src={img}/><button onClick={()=>patch({mainImageIndex:idx})}>{selected.mainImageIndex===idx?'✓ Main':'Set main'}</button><button onClick={()=>patch({images:selected.images.filter((_,i)=>i!==idx),mainImageIndex:0})}>Remove</button></div>)}</div></div></motion.section>;
}

function Product({ product, index, openGallery, addToCart }) { return <motion.div initial={{opacity:0,y:16}} animate={{opacity:1,y:0}} transition={{delay:index*.04}} className="product"><button onClick={()=>openGallery({product,index:product.mainImageIndex||0})}><img src={mainImage(product)} /><span>{product.badge}</span><em>{product.stock} in stock</em></button><div><small>{product.category}</small><h3>{product.name}</h3><p>{fmt(product.price)}</p><button onClick={()=>addToCart(product)}>Add</button></div></motion.div>; }
function Gallery({ gallery, onClose, addToCart }) { const [idx,setIdx]=useState(gallery?.index||0); useEffect(()=>setIdx(gallery?.index||0),[gallery]); if(!gallery) return null; const p=gallery.product; const imgs=p.images?.length?p.images:[mainImage(p)]; const move=d=>setIdx((idx+d+imgs.length)%imgs.length); return <AnimatePresence><motion.div className="modal" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}><div className="modal-head"><div><small>{p.category}</small><h3>{p.name}</h3></div><button onClick={onClose}>×</button></div><div className="photo"><img src={imgs[idx]}/>{imgs.length>1?<><button className="prev" onClick={()=>move(-1)}>‹</button><button className="next" onClick={()=>move(1)}>›</button></>:null}<span>{idx+1}/{imgs.length}</span></div><div className="thumbs">{imgs.map((img,i)=><button key={img+i} onClick={()=>setIdx(i)} className={i===idx?'on':''}><img src={img}/></button>)}</div><div className="modal-card"><div><b>{fmt(p.price)}</b><p>{p.description}</p></div><button onClick={()=>addToCart(p)}>Add</button></div></motion.div></AnimatePresence>; }
function Section({title,children}){return <section><h2>{title}</h2>{children}</section>}
function Card({title,text}){return <div className="card"><b>{title}</b><p>{text}</p></div>}
function Empty({title,text}){return <div className="empty"><b>{title}</b><p>{text}</p></div>}
function Menu({title,text}){return <div className="menu"><b>{title}</b><p>{text}</p><span>→</span></div>}
function Field({label,value,on,type='text'}){return <label>{label}<input type={type} value={value ?? ''} onChange={e=>on(e.target.value)}/></label>}
function Area({label,value,on}){return <label>{label}<textarea value={value ?? ''} onChange={e=>on(e.target.value)}/></label>}

createRoot(document.getElementById('root')).render(<App />);
JS

  cat > "$MINIAPP_DIR/src/styles.css" <<'CSS'
*{box-sizing:border-box} body{margin:0;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d0f14} button,input,textarea{font:inherit}.app{min-height:100vh;color:var(--text);background:var(--bg);--bg:#0d0f14;--surface:#151922;--soft:rgba(255,255,255,.055);--text:#f7f9fc;--sub:#c8d0da;--muted:#8c95a3;--border:rgba(255,255,255,.1);--accent:#a9d7f3;--contrast:#0d0f14}.app.light{--bg:#f4f7fb;--surface:#fff;--soft:rgba(255,255,255,.78);--text:#111827;--sub:#4b5563;--muted:#7b8494;--border:rgba(17,24,39,.1);--accent:#7dbee4;--contrast:#07131c}.shell{position:relative;max-width:430px;min-height:100vh;margin:0 auto;padding-bottom:105px}.glow{position:fixed;border-radius:999px;filter:blur(90px);pointer-events:none}.g1{top:-120px;left:30%;width:280px;height:280px;background:rgba(169,215,243,.2)}.g2{bottom:-120px;right:-80px;width:260px;height:260px;background:rgba(216,211,232,.16)}.header{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--bg) 84%,transparent);backdrop-filter:blur(22px)}.eyebrow,small{font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}h1,h2,h3,p{margin:0}h1{font-size:25px}.head-actions{display:flex;gap:8px}.circle{position:relative;display:grid;place-items:center;width:40px;height:40px;border-radius:999px;border:1px solid var(--border);background:var(--soft);color:var(--text)}.circle.accent{background:var(--accent);color:var(--contrast);font-weight:900}.circle b,.bottom-nav i{position:absolute;right:-3px;top:-4px;display:grid;place-items:center;min-width:18px;height:18px;border-radius:999px;background:var(--text);color:var(--bg);font-size:10px}.hero{margin:20px;padding:24px;border:1px solid var(--border);border-radius:34px;background:radial-gradient(circle at 30% 20%,rgba(169,215,243,.22),transparent 34%),var(--surface);box-shadow:0 24px 90px rgba(0,0,0,.24)}.pill{display:inline-flex;margin-bottom:18px;padding:8px 12px;border-radius:999px;border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);font-size:12px;font-weight:700}.hero h2{max-width:300px;font-size:34px;line-height:.98;letter-spacing:-.04em}.hero p,.screen>p,.ai p,.card p,.empty p,.menu p{margin-top:10px;color:var(--sub);font-size:14px;line-height:1.55}.primary{border:0;border-radius:999px;background:var(--accent);color:var(--contrast);padding:12px 18px;font-weight:800}.hero .primary{margin-top:22px;background:var(--text);color:var(--bg)}section,.screen{padding:0 20px;margin-top:24px}.screen h2{font-size:30px;letter-spacing:-.04em}.collections,.strip{display:flex;gap:12px;overflow:auto;margin:14px -20px 0;padding:0 20px 4px;scrollbar-width:none}.card{min-width:230px;padding:18px;border:1px solid var(--border);border-radius:28px;background:var(--soft)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}.product{overflow:hidden;border:1px solid var(--border);border-radius:28px;background:var(--soft)}.product>button{position:relative;display:block;width:100%;aspect-ratio:4/5;border:0;background:var(--surface);padding:0;overflow:hidden;border-radius:26px}.product img{width:100%;height:100%;object-fit:cover}.product>button:after{content:'';position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.72),transparent 55%)}.product span,.product em{position:absolute;z-index:2;left:12px;border-radius:999px;background:rgba(0,0,0,.38);color:white;padding:5px 10px;font-size:11px;font-style:normal;backdrop-filter:blur(8px)}.product span{bottom:12px}.product em{top:12px}.product>div{padding:13px}.product h3{margin-top:5px;font-size:15px}.product p{margin-top:6px;color:var(--accent);font-weight:800}.product div button{margin-top:10px;width:100%;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:9px}.ai,.summary,.editor,.profile,.empty{margin:20px;border:1px solid var(--border);border-radius:30px;background:var(--soft);padding:20px}.ai b{font-size:18px}.ai button,.modal-card button{margin-top:14px;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:10px 14px}.search{width:100%;margin-top:18px;border:1px solid var(--border);border-radius:24px;background:var(--soft);color:var(--text);padding:14px 16px;outline:none}.chips{display:flex;gap:8px;overflow:auto;margin:14px -20px 0;padding:0 20px 4px;scrollbar-width:none}.chips button{white-space:nowrap;border:1px solid var(--border);border-radius:999px;background:var(--soft);color:var(--sub);padding:9px 14px}.chips .on{background:var(--accent);color:var(--contrast)}.cart-row{display:flex;gap:14px;margin-top:12px;border:1px solid var(--border);border-radius:28px;background:var(--soft);padding:12px}.cart-row img{width:92px;height:92px;object-fit:cover;border-radius:22px}.cart-row p{color:var(--accent);font-weight:800;margin-top:5px}.cart-row button{width:30px;height:30px;border-radius:999px;border:1px solid var(--border);background:var(--surface);color:var(--text)}.cart-row span{display:inline-block;width:28px;text-align:center}.summary{margin:18px 0 0}.summary p,.summary h3{display:flex;justify-content:space-between;padding:8px 0}.wide{width:100%;margin-top:16px}.profile{display:flex;align-items:center;gap:14px}.avatar{display:grid;place-items:center;width:64px;height:64px;border-radius:24px;background:var(--accent);color:var(--contrast);font-size:26px}.profile span{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}.menu{position:relative;margin-top:12px;border:1px solid var(--border);border-radius:26px;background:var(--soft);padding:16px}.menu span{position:absolute;right:18px;top:22px;color:var(--muted)}.bottom-nav{position:fixed;left:50%;bottom:14px;z-index:30;display:grid;grid-template-columns:repeat(6,1fr);gap:3px;width:calc(100% - 28px);max-width:402px;transform:translateX(-50%);padding:8px;border:1px solid var(--border);border-radius:28px;background:color-mix(in srgb,var(--surface) 88%,transparent);backdrop-filter:blur(22px);box-shadow:0 20px 80px rgba(0,0,0,.28)}.bottom-nav button{position:relative;border:0;border-radius:18px;background:transparent;color:var(--muted);padding:7px 2px;font-size:9px;font-weight:700}.bottom-nav span{display:block;font-size:15px}.bottom-nav .active{background:var(--accent);color:var(--contrast)}.modal{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.88);padding:16px;color:white;backdrop-filter:blur(18px)}.modal-head{max-width:430px;margin:0 auto 14px;display:flex;justify-content:space-between;align-items:center}.modal-head button{width:42px;height:42px;border-radius:999px;border:0;background:rgba(255,255,255,.1);color:white;font-size:26px}.photo{position:relative;max-width:430px;margin:0 auto;border-radius:34px;overflow:hidden;background:rgba(255,255,255,.05)}.photo img{width:100%;height:min(68vh,520px);object-fit:cover}.prev,.next{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;border:0;border-radius:999px;background:rgba(0,0,0,.36);color:white;font-size:30px}.prev{left:12px}.next{right:12px}.photo span{position:absolute;left:14px;bottom:14px;border-radius:999px;background:rgba(0,0,0,.42);padding:6px 10px;font-size:12px}.thumbs{max-width:430px;margin:12px auto;display:flex;gap:8px;overflow:auto}.thumbs button{width:68px;height:68px;border-radius:18px;border:1px solid rgba(255,255,255,.16);background:transparent;padding:3px}.thumbs .on{border-color:#a9d7f3}.thumbs img{width:100%;height:100%;object-fit:cover;border-radius:14px}.modal-card{max-width:430px;margin:0 auto;display:flex;justify-content:space-between;gap:12px;border:1px solid rgba(255,255,255,.12);border-radius:26px;background:rgba(255,255,255,.1);padding:16px}.admin-head{display:flex;justify-content:space-between;gap:12px}.admin-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.strip button{min-width:150px;border:1px solid var(--border);border-radius:24px;background:var(--soft);padding:8px;text-align:left;color:var(--text)}.strip .sel{border-color:var(--accent)}.strip img{width:100%;height:96px;object-fit:cover;border-radius:18px}.strip b,.strip small{display:block;margin-top:6px}.editor{display:grid;gap:12px}.editor label{display:grid;gap:6px;color:var(--muted);font-size:12px}.editor input,.editor textarea{border:1px solid var(--border);border-radius:18px;background:var(--surface);color:var(--text);padding:12px;outline:none}.editor textarea{min-height:82px;resize:vertical}.upload{border:1px dashed var(--border);border-radius:20px;padding:16px;text-align:center}.upload input{display:none}.photos{display:grid;grid-template-columns:1fr 1fr;gap:10px}.photos img{width:100%;height:120px;object-fit:cover;border-radius:18px}.photos button{width:100%;margin-top:6px;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:8px;font-size:12px}
CSS
}

build_miniapp() {
  log "Building Mini App to static/miniapp..."
  need_cmd node
  need_cmd npm
  cd "$MINIAPP_DIR"
  npm install
  npm run build
  rm -rf "$STATIC_MINIAPP_DIR"
  mkdir -p "$STATIC_MINIAPP_DIR"
  cp -a dist/. "$STATIC_MINIAPP_DIR/"
  cd "$PROJECT_ROOT"
}

write_env() {
  log "Ensuring 2loop env variables in .env..."
  touch "$PROJECT_ROOT/.env"
  grep -q '^TWOLOOP_DATA_DIR=' "$PROJECT_ROOT/.env" || echo "TWOLOOP_DATA_DIR=$DATA_DIR" >> "$PROJECT_ROOT/.env"
  grep -q '^TWOLOOP_UPLOAD_DIR=' "$PROJECT_ROOT/.env" || echo "TWOLOOP_UPLOAD_DIR=static/uploads/2loop" >> "$PROJECT_ROOT/.env"
}

write_nginx() {
  if [[ $EUID -ne 0 ]]; then
    warn "Not root: skipping nginx config. Run with sudo if you want nginx auto-config."
    return 0
  fi
  if ! command -v nginx >/dev/null 2>&1; then
    warn "nginx is not installed: skipping nginx config."
    return 0
  fi

  log "Writing nginx config for $DOMAIN..."
  cat > "$NGINX_AVAILABLE" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 64M;

    location / {
        root $PROJECT_ROOT/static/miniapp;
        try_files \$uri \$uri/ /index.html;
    }

    location /api/miniapp/ {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        alias $PROJECT_ROOT/static/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
    }
}
NGINX
  ln -sfn "$NGINX_AVAILABLE" "$NGINX_ENABLED"
  nginx -t
  systemctl reload nginx || service nginx reload || true

  if command -v certbot >/dev/null 2>&1; then
    log "Trying certbot HTTPS setup for $DOMAIN..."
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@$DOMAIN" || warn "Certbot failed. Check DNS and run manually: certbot --nginx -d $DOMAIN"
  else
    warn "certbot not installed. HTTPS can be added later: certbot --nginx -d $DOMAIN"
  fi
}

smoke_test() {
  log "Smoke test files..."
  [[ -f "$STATIC_MINIAPP_DIR/index.html" ]] || fail "Mini App build missing index.html"
  [[ -f "$PROJECT_ROOT/bot/miniapp_api.py" ]] || fail "bot/miniapp_api.py missing. Pull latest 2loop_dev first."
  python3 -m py_compile "$PROJECT_ROOT/bot/miniapp_api.py"
  python3 - <<'PY'
from pathlib import Path
s = Path('bot/main.py').read_text(encoding='utf-8')
assert 'setup_miniapp_routes(app)' in s, 'setup_miniapp_routes(app) not found in bot/main.py'
assert 'from bot.miniapp_api import setup_miniapp_routes' in s, 'miniapp import not found in bot/main.py'
print('main.py miniapp patch OK')
PY
}

main() {
  cd "$PROJECT_ROOT"
  log "Project root: $PROJECT_ROOT"
  need_cmd python3
  patch_main_py
  write_env
  write_miniapp
  build_miniapp
  write_nginx
  smoke_test
  log "Done. Mini App URL: https://$DOMAIN/"
  log "After this, run: ./stop.sh && ./start.sh"
}

main "$@"
