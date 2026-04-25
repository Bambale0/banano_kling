#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIAPP_DIR="$PROJECT_ROOT/miniapp"
STATIC_MINIAPP_DIR="$PROJECT_ROOT/static/miniapp"
PUBLIC_ROOT="${TWOLOOP_PUBLIC_ROOT:-/var/www/2loop}"
PUBLIC_STATIC="$PUBLIC_ROOT/static"

log() { printf '\033[1;36m[2loop-upgrade]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[2loop-upgrade][error]\033[0m %s\n' "$*"; exit 1; }

[[ -d "$MINIAPP_DIR" ]] || fail "miniapp directory not found. Run setup_2loop_miniapp.sh first."
command -v node >/dev/null 2>&1 || fail "node not found"
command -v npm >/dev/null 2>&1 || fail "npm not found"

log "Writing production RU Mini App frontend"
mkdir -p "$MINIAPP_DIR/src"

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
    category: 'Украшения',
    price: 2900,
    stock: 12,
    badge: 'Хит',
    description: 'Аккуратное украшение для причёски на выступление.',
    details: 'Лёгкая фиксация, деликатный блеск, подходит для соревнований и фотосессий.',
    images: ['https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=900&q=80'],
    mainImageIndex: 0,
    active: true,
  },
];

const categoryLabels = ['Все', 'Украшения', 'Перчатки', 'Сумки', 'Уход за лезвиями', 'Подарки', 'Соревнования'];
const nav = [
  ['home', 'Главная', '✦'],
  ['catalog', 'Каталог', '⌕'],
  ['saved', 'Избранное', '♡'],
  ['cart', 'Корзина', '◈'],
  ['profile', 'Профиль', '◌'],
  ['admin', 'Админ', '⚙'],
];

function fmt(value) { return `${Number(value || 0).toLocaleString('ru-RU')} ₽`; }
function mainImage(product) { return product.images?.[product.mainImageIndex || 0] || product.images?.[0] || ''; }
function safeProducts(products) { return products.filter(Boolean).map((p) => ({ ...p, images: Array.isArray(p.images) ? p.images : [] })); }

function App() {
  const tg = window.Telegram?.WebApp;
  const [tab, setTab] = useState('home');
  const [theme, setTheme] = useState('dark');
  const [products, setProducts] = useState(fallbackProducts);
  const [cart, setCart] = useState(() => loadCart());
  const [gallery, setGallery] = useState(null);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);
  const [me, setMe] = useState({ user: null, isAdmin: false });

  useEffect(() => {
    tg?.ready?.();
    tg?.expand?.();
    Promise.allSettled([api.products(true), api.settings(), api.me?.()])
      .then(([productsResult, settingsResult, meResult]) => {
        if (productsResult.status === 'fulfilled') setProducts(safeProducts(productsResult.value.products || []));
        if (settingsResult.status === 'fulfilled') setTheme(settingsResult.value.settings?.theme || 'dark');
        if (meResult?.status === 'fulfilled') setMe(meResult.value || { user: null, isAdmin: false });
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => saveCart(cart), [cart]);

  const visibleProducts = useMemo(() => products.filter((p) => p.active !== false), [products]);
  const cartItems = useMemo(() => cart.map((item) => ({ ...products.find((p) => p.id === item.productId), qty: item.qty })).filter((item) => item.id), [cart, products]);
  const cartCount = cart.reduce((sum, item) => sum + item.qty, 0);

  function showToast(message, type = 'ok') {
    setToast({ message, type });
    setTimeout(() => setToast(null), 2800);
  }

  async function refreshProducts(includeInactive = me.isAdmin) {
    const data = await api.products(includeInactive);
    setProducts(safeProducts(data.products || []));
  }

  async function saveTheme(nextTheme) {
    setTheme(nextTheme);
    try { await api.updateSettings({ theme: nextTheme }); }
    catch { showToast('Тему можно менять только администратору', 'warn'); }
  }

  function addToCart(product, qty = 1) {
    if (!product.stock || product.stock <= 0) return showToast('Товара нет в наличии', 'warn');
    setCart((current) => {
      const exists = current.find((item) => item.productId === product.id);
      if (exists) return current.map((item) => item.productId === product.id ? { ...item, qty: Math.min(product.stock, item.qty + qty) } : item);
      return [...current, { productId: product.id, qty: Math.min(product.stock, qty) }];
    });
    tg?.HapticFeedback?.impactOccurred?.('light');
    showToast('Добавлено в корзину');
  }

  return (
    <div className={`app ${theme}`}>
      <div className="glow g1" /><div className="glow g2" />
      <main className="shell">
        <Header theme={theme} saveTheme={saveTheme} cartCount={cartCount} setTab={setTab} />
        {loading ? <Empty title="Загружаем магазин" text="Подготавливаем каталог и настройки." /> : null}
        {!loading && tab === 'home' ? <Home products={visibleProducts} setTab={setTab} openGallery={setGallery} addToCart={addToCart} /> : null}
        {!loading && tab === 'catalog' ? <Catalog products={visibleProducts} openGallery={setGallery} addToCart={addToCart} /> : null}
        {!loading && tab === 'saved' ? <Saved products={visibleProducts.slice(0, 4)} openGallery={setGallery} addToCart={addToCart} /> : null}
        {!loading && tab === 'cart' ? <Cart items={cartItems} setCart={setCart} tg={tg} showToast={showToast} setTab={setTab} /> : null}
        {!loading && tab === 'profile' ? <Profile tg={tg} /> : null}
        {!loading && tab === 'admin' ? <Admin products={products} setProducts={setProducts} refreshProducts={refreshProducts} theme={theme} saveTheme={saveTheme} isAdmin={me.isAdmin} showToast={showToast} /> : null}
        <BottomNav active={tab} setTab={setTab} cartCount={cartCount} isAdmin={me.isAdmin} />
      </main>
      <Gallery gallery={gallery} onClose={() => setGallery(null)} addToCart={addToCart} />
      <Toast toast={toast} />
    </div>
  );
}

function loadCart() { try { return JSON.parse(localStorage.getItem('2loop_cart') || '[]'); } catch { return []; } }
function saveCart(cart) { localStorage.setItem('2loop_cart', JSON.stringify(cart)); }

function Header({ theme, saveTheme, cartCount, setTab }) {
  return <header className="header"><div><div className="eyebrow">Бутик аксессуаров для фигурного катания</div><h1>2loop</h1></div><div className="head-actions"><button onClick={() => saveTheme(theme === 'dark' ? 'light' : 'dark')} className="circle" aria-label="Сменить тему">{theme === 'dark' ? '☀' : '☾'}</button><button onClick={() => setTab('cart')} className="circle accent" aria-label="Корзина">◈{cartCount ? <b>{cartCount}</b> : null}</button></div></header>;
}

function Home({ products, setTab, openGallery, addToCart }) {
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}}><div className="hero"><div className="pill">✦ Новая подборка сезона</div><h2>Детали, которые красиво смотрятся на льду.</h2><p>Аксессуары для тренировок, соревнований, подарков и образов фигуристок.</p><button onClick={() => setTab('catalog')} className="primary">Перейти в каталог →</button></div><Section title="Подборки"><div className="collections"><Card title="День соревнований" text="Украшения и аксессуары для выступления" /><Card title="Для тренировок" text="Практичные вещи на каждый день" /><Card title="Подарки" text="Аккуратные идеи для фигуристки и тренера" /></div></Section><Section title="Новинки"><ProductGrid products={products.slice(0, 4)} openGallery={openGallery} addToCart={addToCart} /></Section><div className="ai"><b>AI-подбор аксессуаров</b><p>Поможем подобрать комплект для тренировки, соревнований или подарка.</p><button onClick={() => setTab('catalog')}>Выбрать товары →</button></div></motion.section>;
}

function Catalog({ products, openGallery, addToCart }) {
  const [cat, setCat] = useState('Все');
  const [q, setQ] = useState('');
  const shown = useMemo(() => products.filter((p) => (cat === 'Все' || p.category === cat) && `${p.name} ${p.category} ${p.description}`.toLowerCase().includes(q.toLowerCase())), [products, cat, q]);
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><h2>Каталог</h2><p>Выберите аксессуары для тренировок, соревнований и подарков.</p><input className="search" value={q} onChange={(e)=>setQ(e.target.value)} placeholder="Поиск по товарам"/><div className="chips">{categoryLabels.map((c)=><button key={c} onClick={()=>setCat(c)} className={cat===c?'on':''}>{c}</button>)}</div>{shown.length ? <ProductGrid products={shown} openGallery={openGallery} addToCart={addToCart} /> : <Empty title="Ничего не найдено" text="Попробуйте другую категорию или запрос."/>}</motion.section>;
}

function ProductGrid({ products, openGallery, addToCart }) { return <div className="grid">{products.map((p,i)=><Product key={p.id} product={p} index={i} openGallery={openGallery} addToCart={addToCart}/>)}</div>; }

function Product({ product, index, openGallery, addToCart }) {
  return <motion.div initial={{opacity:0,y:16}} animate={{opacity:1,y:0}} transition={{delay:index*.035}} className="product"><button onClick={()=>openGallery({product,index:product.mainImageIndex||0})}><img src={mainImage(product)} /><span>{product.badge || '2loop'}</span><em>{product.stock > 0 ? `${product.stock} шт.` : 'Нет в наличии'}</em></button><div><small>{product.category}</small><h3>{product.name}</h3><p>{fmt(product.price)}</p><button disabled={!product.stock} onClick={()=>addToCart(product)}>{product.stock > 0 ? 'В корзину' : 'Нет в наличии'}</button></div></motion.div>;
}

function Saved(props) { return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><h2>Избранное</h2><p>Сохранённые идеи для покупки, подарка или согласования с тренером.</p><ProductGrid products={props.products} openGallery={props.openGallery} addToCart={props.addToCart} /></motion.section>; }

function Cart({ items, setCart, tg, showToast, setTab }) {
  const [step, setStep] = useState('cart');
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState(() => ({ name: tg?.initDataUnsafe?.user?.first_name || '', phone: '', city: '', address: '', deliveryMethod: 'Курьер', comment: '' }));
  const subtotal = items.reduce((s,i)=>s+i.price*i.qty,0);
  const delivery = subtotal >= 5000 ? 0 : 350;
  const total = subtotal + delivery;
  function qty(id, d){ setCart(cur=>cur.map(i=>i.productId===id?{...i,qty:Math.max(1,i.qty+d)}:i)); }
  function remove(id){ setCart(cur=>cur.filter(i=>i.productId!==id)); }
  function validate(){ if(!items.length) return 'Корзина пустая'; if(!form.name.trim()) return 'Укажите имя'; if(!form.phone.trim()) return 'Укажите телефон'; if(!form.city.trim()) return 'Укажите город'; if(!form.address.trim()) return 'Укажите адрес доставки'; return ''; }
  async function checkout(){ const error = validate(); if(error) return showToast(error, 'warn'); setSubmitting(true); try { const payload = { telegramUser: tg?.initDataUnsafe?.user, customer: { name: form.name, phone: form.phone }, delivery: { city: form.city, address: form.address, method: form.deliveryMethod }, comment: form.comment, items: items.map(i=>({ productId:i.id, qty:i.qty })) }; const result = await api.createOrder(payload); localStorage.removeItem('2loop_cart'); setCart([]); setStep('success'); showToast(`Заказ №${result.order.id} создан`); } catch(err) { showToast(err.message || 'Не удалось создать заказ', 'warn'); } finally { setSubmitting(false); } }
  if(step === 'success') return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><div className="success"><div>✓</div><h2>Заказ создан</h2><p>Мы получили заказ и скоро свяжемся с вами в Telegram или по телефону для подтверждения доставки.</p><button className="primary wide" onClick={()=>setTab('catalog')}>Вернуться в каталог</button></div></motion.section>;
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><h2>Корзина</h2>{!items.length ? <Empty title="Корзина пустая" text="Добавьте товары из каталога."/> : <>{step==='cart'?<><p>Проверьте товары перед оформлением.</p>{items.map(i=><div className="cart-row" key={i.id}><img src={mainImage(i)}/><div><b>{i.name}</b><p>{fmt(i.price)}</p><div className="qty"><button onClick={()=>qty(i.id,-1)}>-</button><span>{i.qty}</span><button onClick={()=>qty(i.id,1)}>+</button><button className="remove" onClick={()=>remove(i.id)}>Удалить</button></div></div></div>)}<OrderSummary subtotal={subtotal} delivery={delivery} total={total} /><button className="primary wide" onClick={()=>setStep('checkout')}>Оформить заказ</button></>:<><p>Укажите контакты и адрес доставки.</p><div className="checkout-form"><Field label="Имя" value={form.name} on={v=>setForm({...form,name:v})}/><Field label="Телефон" value={form.phone} on={v=>setForm({...form,phone:v})} placeholder="+7..."/><Field label="Город" value={form.city} on={v=>setForm({...form,city:v})}/><Field label="Адрес" value={form.address} on={v=>setForm({...form,address:v})}/><label>Способ доставки<select value={form.deliveryMethod} onChange={e=>setForm({...form,deliveryMethod:e.target.value})}><option>Курьер</option><option>СДЭК</option><option>Почта России</option><option>Самовывоз</option></select></label><Area label="Комментарий" value={form.comment} on={v=>setForm({...form,comment:v})}/></div><OrderSummary subtotal={subtotal} delivery={delivery} total={total} /><div className="row-actions"><button onClick={()=>setStep('cart')}>Назад</button><button disabled={submitting} className="primary" onClick={checkout}>{submitting ? 'Создаём...' : 'Подтвердить заказ'}</button></div></>}</>}</motion.section>;
}

function OrderSummary({ subtotal, delivery, total }) { return <div className="summary"><p><span>Товары</span><b>{fmt(subtotal)}</b></p><p><span>Доставка</span><b>{delivery ? fmt(delivery) : 'Бесплатно'}</b></p><h3><span>Итого</span><b>{fmt(total)}</b></h3></div>; }

function Profile({ tg }) { const user = tg?.initDataUnsafe?.user; return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><div className="profile"><div className="avatar">◌</div><div><span>Клиент 2loop</span><h2>{user?.first_name || 'Профиль'}</h2><p>Бонусная программа скоро появится</p></div></div><Menu title="Мои заказы" text="История и статусы заказов"/><Menu title="Доставка" text="Адреса и способы доставки"/><Menu title="Поддержка" text="Связь с магазином в Telegram"/></motion.section>; }

function Admin({ products, setProducts, refreshProducts, theme, saveTheme, isAdmin, showToast }) {
  const [selectedId, setSelectedId] = useState(products[0]?.id);
  const selected = products.find(p=>p.id===selectedId) || products[0];
  async function add(){ try { const r = await api.createProduct({ name:'Новый товар', category:'Украшения', price:2500, stock:1, badge:'Новинка', description:'Описание товара', details:'Информация о товаре', active:true, images:[] }); await refreshProducts(true); setSelectedId(r.product.id); showToast('Товар создан'); } catch(e){ showToast(e.message, 'warn'); } }
  async function patch(payload){ try { const r = await api.updateProduct(selected.id, payload); setProducts(cur=>cur.map(p=>p.id===selected.id?r.product:p)); } catch(e){ showToast(e.message, 'warn'); } }
  async function upload(file){ if(!file) return; try { const r = await api.uploadImage(selected.id, file); setProducts(cur=>cur.map(p=>p.id===selected.id?r.product:p)); showToast('Фото загружено'); } catch(e){ showToast(e.message, 'warn'); } }
  if(!isAdmin) return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen"><Empty title="Доступ только администратору" text="Откройте мини-приложение из Telegram аккаунта администратора."/></motion.section>;
  if(!selected) return <motion.section className="screen"><button onClick={add} className="primary wide">Создать первый товар</button></motion.section>;
  return <motion.section initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} className="screen admin-screen"><div className="admin-head"><div><h2>Админка</h2><p>Товары, фото, остатки и оформление магазина.</p></div><button onClick={add} className="primary">Добавить</button></div><div className="admin-stats"><Card title={products.length} text="Товаров"/><Card title={products.reduce((s,p)=>s+Number(p.stock||0),0)} text="Остаток"/><Card title={products.filter(p=>Number(p.stock||0)<=5).length} text="Мало"/></div><div className="editor compact"><label>Тема магазина <button onClick={()=>saveTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?'Светлая':'Тёмная'}</button></label></div><div className="strip">{products.map(p=><button key={p.id} onClick={()=>setSelectedId(p.id)} className={p.id===selected.id?'sel':''}><img src={mainImage(p)}/><b>{p.name}</b><small>{p.stock} шт. · {fmt(p.price)}</small></button>)}</div><div className="editor"><h3>Редактирование товара</h3><Field label="Название" value={selected.name} on={v=>patch({name:v})}/><div className="two"><Field label="Категория" value={selected.category} on={v=>patch({category:v})}/><Field label="Бейдж" value={selected.badge} on={v=>patch({badge:v})}/></div><div className="two"><Field label="Цена" type="number" value={selected.price} on={v=>patch({price:Number(v)})}/><Field label="Остаток" type="number" value={selected.stock} on={v=>patch({stock:Number(v)})}/></div><label className="switch"><input type="checkbox" checked={selected.active !== false} onChange={e=>patch({active:e.target.checked})}/><span>Показывать товар в магазине</span></label><Area label="Краткое описание" value={selected.description} on={v=>patch({description:v})}/><Area label="Информация о товаре" value={selected.details} on={v=>patch({details:v})}/><label className="upload">Загрузить фото<input type="file" accept="image/*" onChange={e=>upload(e.target.files?.[0])}/></label><div className="photos">{(selected.images||[]).map((img,idx)=><div key={img+idx}><img src={img}/><button onClick={()=>patch({mainImageIndex:idx})}>{selected.mainImageIndex===idx?'✓ Главное':'Сделать главным'}</button><button onClick={()=>patch({images:selected.images.filter((_,i)=>i!==idx),mainImageIndex:0})}>Удалить</button></div>)}</div></div></motion.section>;
}

function Gallery({ gallery, onClose, addToCart }) { const [idx,setIdx]=useState(gallery?.index||0); useEffect(()=>setIdx(gallery?.index||0),[gallery]); if(!gallery) return null; const p=gallery.product; const imgs=p.images?.length?p.images:[mainImage(p)]; const move=d=>setIdx((idx+d+imgs.length)%imgs.length); return <AnimatePresence><motion.div className="modal" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}><div className="modal-head"><div><small>{p.category}</small><h3>{p.name}</h3></div><button onClick={onClose}>×</button></div><div className="photo"><img src={imgs[idx]}/>{imgs.length>1?<><button className="prev" onClick={()=>move(-1)}>‹</button><button className="next" onClick={()=>move(1)}>›</button></>:null}<span>{idx+1}/{imgs.length}</span></div><div className="thumbs">{imgs.map((img,i)=><button key={img+i} onClick={()=>setIdx(i)} className={i===idx?'on':''}><img src={img}/></button>)}</div><div className="modal-card"><div><b>{fmt(p.price)}</b><p>{p.description}</p></div><button onClick={()=>addToCart(p)}>В корзину</button></div></motion.div></AnimatePresence>; }

function BottomNav({ active, setTab, cartCount, isAdmin }) { return <nav className="bottom-nav">{nav.filter(([k]) => isAdmin || k !== 'admin').map(([key,label,ic])=><button key={key} onClick={()=>setTab(key)} className={active===key?'active':''}><span>{ic}</span>{label}{key==='cart'&&cartCount?<i>{cartCount}</i>:null}</button>)}</nav>; }
function Section({title,children}){return <section><h2>{title}</h2>{children}</section>}
function Card({title,text}){return <div className="card"><b>{title}</b><p>{text}</p></div>}
function Empty({title,text}){return <div className="empty"><b>{title}</b><p>{text}</p></div>}
function Menu({title,text}){return <div className="menu"><b>{title}</b><p>{text}</p><span>→</span></div>}
function Field({label,value,on,type='text',placeholder=''}){return <label>{label}<input type={type} value={value ?? ''} placeholder={placeholder} onChange={e=>on(e.target.value)}/></label>}
function Area({label,value,on}){return <label>{label}<textarea value={value ?? ''} onChange={e=>on(e.target.value)}/></label>}
function Toast({ toast }) { return <AnimatePresence>{toast ? <motion.div className={`toast ${toast.type}`} initial={{opacity:0,y:20}} animate={{opacity:1,y:0}} exit={{opacity:0,y:20}}>{toast.message}</motion.div> : null}</AnimatePresence>; }

createRoot(document.getElementById('root')).render(<App />);
JS

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
  if (!response.ok) throw new Error(data.error || `Ошибка запроса: ${response.status}`);
  return data;
}

export const api = {
  me: () => request('/me'),
  products: (includeInactive = false) => request(`/products${includeInactive ? '?include_inactive=1' : ''}`),
  settings: () => request('/settings'),
  updateSettings: (payload) => request('/settings', { method: 'PUT', body: payload }),
  createProduct: (payload) => request('/products', { method: 'POST', body: payload }),
  updateProduct: (id, payload) => request(`/products/${id}`, { method: 'PUT', body: payload }),
  deleteProduct: (id) => request(`/products/${id}`, { method: 'DELETE' }),
  uploadImage: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return request(`/products/${id}/images`, { method: 'POST', body: form });
  },
  createOrder: (payload) => request('/orders', { method: 'POST', body: payload }),
  orders: () => request('/orders'),
};
JS

cat > "$MINIAPP_DIR/src/styles.css" <<'CSS'
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d0f14}button,input,textarea,select{font:inherit}button{cursor:pointer}.app{min-height:100vh;color:var(--text);background:var(--bg);--bg:#0d0f14;--surface:#151922;--soft:rgba(255,255,255,.055);--text:#f7f9fc;--sub:#c8d0da;--muted:#8c95a3;--border:rgba(255,255,255,.1);--accent:#a9d7f3;--contrast:#0d0f14}.app.light{--bg:#f4f7fb;--surface:#fff;--soft:rgba(255,255,255,.78);--text:#111827;--sub:#4b5563;--muted:#7b8494;--border:rgba(17,24,39,.1);--accent:#7dbee4;--contrast:#07131c}.shell{position:relative;max-width:430px;min-height:100vh;margin:0 auto;padding-bottom:108px}.glow{position:fixed;border-radius:999px;filter:blur(90px);pointer-events:none}.g1{top:-120px;left:30%;width:280px;height:280px;background:rgba(169,215,243,.2)}.g2{bottom:-120px;right:-80px;width:260px;height:260px;background:rgba(216,211,232,.16)}.header{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--bg) 84%,transparent);backdrop-filter:blur(22px)}.eyebrow,small{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}h1,h2,h3,p{margin:0}h1{font-size:24px}.head-actions{display:flex;gap:8px}.circle{position:relative;display:grid;place-items:center;width:40px;height:40px;border-radius:999px;border:1px solid var(--border);background:var(--soft);color:var(--text)}.circle.accent{background:var(--accent);color:var(--contrast);font-weight:900}.circle b,.bottom-nav i{position:absolute;right:-3px;top:-4px;display:grid;place-items:center;min-width:18px;height:18px;border-radius:999px;background:var(--text);color:var(--bg);font-size:10px}.hero{margin:16px;padding:22px;border:1px solid var(--border);border-radius:30px;background:radial-gradient(circle at 30% 20%,rgba(169,215,243,.22),transparent 34%),var(--surface);box-shadow:0 24px 90px rgba(0,0,0,.24)}.pill{display:inline-flex;margin-bottom:16px;padding:8px 12px;border-radius:999px;border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);font-size:12px;font-weight:700}.hero h2{max-width:310px;font-size:31px;line-height:1;letter-spacing:-.04em}.hero p,.screen>p,.ai p,.card p,.empty p,.menu p{margin-top:10px;color:var(--sub);font-size:14px;line-height:1.55}.primary{border:0;border-radius:999px;background:var(--accent);color:var(--contrast);padding:12px 16px;font-weight:800}.primary:disabled{opacity:.6}.hero .primary{margin-top:20px;background:var(--text);color:var(--bg)}section,.screen{padding:0 16px;margin-top:22px}.screen h2{font-size:28px;letter-spacing:-.04em}.collections,.strip{display:flex;gap:10px;overflow:auto;margin:12px -16px 0;padding:0 16px 4px;scrollbar-width:none}.card{min-width:210px;padding:16px;border:1px solid var(--border);border-radius:24px;background:var(--soft)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}.product{overflow:hidden;border:1px solid var(--border);border-radius:24px;background:var(--soft)}.product>button{position:relative;display:block;width:100%;aspect-ratio:4/5;border:0;background:var(--surface);padding:0;overflow:hidden;border-radius:22px}.product img{width:100%;height:100%;object-fit:cover}.product>button:after{content:'';position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.72),transparent 55%)}.product span,.product em{position:absolute;z-index:2;left:10px;border-radius:999px;background:rgba(0,0,0,.38);color:white;padding:5px 9px;font-size:10px;font-style:normal;backdrop-filter:blur(8px)}.product span{bottom:10px}.product em{top:10px}.product>div{padding:12px}.product h3{margin-top:5px;font-size:14px;line-height:1.25}.product p{margin-top:6px;color:var(--accent);font-weight:800}.product div button{margin-top:10px;width:100%;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:9px;font-size:13px}.ai,.summary,.editor,.profile,.empty,.success{margin:16px;border:1px solid var(--border);border-radius:26px;background:var(--soft);padding:18px}.ai b{font-size:18px}.ai button,.modal-card button{margin-top:14px;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:10px 14px}.search{width:100%;margin-top:16px;border:1px solid var(--border);border-radius:22px;background:var(--soft);color:var(--text);padding:14px 16px;outline:none}.chips{display:flex;gap:8px;overflow:auto;margin:12px -16px 0;padding:0 16px 4px;scrollbar-width:none}.chips button{white-space:nowrap;border:1px solid var(--border);border-radius:999px;background:var(--soft);color:var(--sub);padding:9px 13px;font-size:13px}.chips .on{background:var(--accent);color:var(--contrast)}.cart-row{display:flex;gap:12px;margin-top:12px;border:1px solid var(--border);border-radius:24px;background:var(--soft);padding:10px}.cart-row img{width:86px;height:86px;object-fit:cover;border-radius:20px}.cart-row p{color:var(--accent);font-weight:800;margin-top:5px}.qty{display:flex;align-items:center;gap:7px;margin-top:9px;flex-wrap:wrap}.qty button{min-width:30px;height:30px;border-radius:999px;border:1px solid var(--border);background:var(--surface);color:var(--text)}.qty .remove{width:auto;padding:0 10px;color:#ff9b9b}.cart-row span{display:inline-block;width:24px;text-align:center}.summary{margin:16px 0}.summary p,.summary h3{display:flex;justify-content:space-between;padding:8px 0}.wide{width:100%;margin-top:12px}.checkout-form{display:grid;gap:11px;margin-top:14px}.checkout-form label,.editor label{display:grid;gap:6px;color:var(--muted);font-size:12px}.checkout-form input,.checkout-form textarea,.checkout-form select,.editor input,.editor textarea,.editor select{width:100%;border:1px solid var(--border);border-radius:16px;background:var(--surface);color:var(--text);padding:12px;outline:none}.checkout-form textarea,.editor textarea{min-height:80px;resize:vertical}.row-actions{display:grid;grid-template-columns:1fr 1.4fr;gap:10px}.row-actions button{border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:12px;font-weight:800}.success{text-align:center}.success div{display:grid;place-items:center;margin:0 auto 12px;width:60px;height:60px;border-radius:22px;background:var(--accent);color:var(--contrast);font-size:28px;font-weight:900}.profile{display:flex;align-items:center;gap:14px}.avatar{display:grid;place-items:center;width:60px;height:60px;border-radius:22px;background:var(--accent);color:var(--contrast);font-size:26px}.profile span{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}.menu{position:relative;margin-top:12px;border:1px solid var(--border);border-radius:22px;background:var(--soft);padding:16px}.menu span{position:absolute;right:18px;top:22px;color:var(--muted)}.bottom-nav{position:fixed;left:50%;bottom:12px;z-index:30;display:grid;grid-template-columns:repeat(5,1fr);gap:3px;width:calc(100% - 24px);max-width:402px;transform:translateX(-50%);padding:7px;border:1px solid var(--border);border-radius:26px;background:color-mix(in srgb,var(--surface) 88%,transparent);backdrop-filter:blur(22px);box-shadow:0 20px 80px rgba(0,0,0,.28)}.bottom-nav:has(button:nth-child(6)){grid-template-columns:repeat(6,1fr)}.bottom-nav button{position:relative;border:0;border-radius:16px;background:transparent;color:var(--muted);padding:7px 2px;font-size:9px;font-weight:700}.bottom-nav span{display:block;font-size:15px}.bottom-nav .active{background:var(--accent);color:var(--contrast)}.modal{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.88);padding:14px;color:white;backdrop-filter:blur(18px)}.modal-head{max-width:430px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}.modal-head button{width:42px;height:42px;border-radius:999px;border:0;background:rgba(255,255,255,.1);color:white;font-size:26px}.photo{position:relative;max-width:430px;margin:0 auto;border-radius:30px;overflow:hidden;background:rgba(255,255,255,.05)}.photo img{width:100%;height:min(64vh,500px);object-fit:cover}.prev,.next{position:absolute;top:50%;transform:translateY(-50%);width:42px;height:42px;border:0;border-radius:999px;background:rgba(0,0,0,.36);color:white;font-size:30px}.prev{left:10px}.next{right:10px}.photo span{position:absolute;left:12px;bottom:12px;border-radius:999px;background:rgba(0,0,0,.42);padding:6px 10px;font-size:12px}.thumbs{max-width:430px;margin:10px auto;display:flex;gap:8px;overflow:auto}.thumbs button{width:64px;height:64px;border-radius:16px;border:1px solid rgba(255,255,255,.16);background:transparent;padding:3px}.thumbs .on{border-color:#a9d7f3}.thumbs img{width:100%;height:100%;object-fit:cover;border-radius:12px}.modal-card{max-width:430px;margin:0 auto;display:flex;justify-content:space-between;gap:12px;border:1px solid rgba(255,255,255,.12);border-radius:24px;background:rgba(255,255,255,.1);padding:14px}.modal-card p{margin-top:6px;color:rgba(255,255,255,.7);font-size:13px}.admin-screen{padding-bottom:12px}.admin-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.admin-head p{margin-top:6px}.admin-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}.admin-stats .card{min-width:0;padding:12px}.strip button{min-width:138px;border:1px solid var(--border);border-radius:22px;background:var(--soft);padding:8px;text-align:left;color:var(--text)}.strip .sel{border-color:var(--accent)}.strip img{width:100%;height:90px;object-fit:cover;border-radius:16px}.strip b,.strip small{display:block;margin-top:6px}.editor{display:grid;gap:12px;margin-left:0;margin-right:0}.editor h3{font-size:18px}.editor.compact{margin:14px 0 0}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}.switch{display:flex!important;align-items:center;gap:9px}.switch input{width:auto}.upload{border:1px dashed var(--border);border-radius:18px;padding:16px;text-align:center}.upload input{display:none}.photos{display:grid;grid-template-columns:1fr 1fr;gap:10px}.photos img{width:100%;height:118px;object-fit:cover;border-radius:16px}.photos button{width:100%;margin-top:6px;border:1px solid var(--border);border-radius:999px;background:var(--surface);color:var(--text);padding:8px;font-size:12px}.toast{position:fixed;left:50%;bottom:96px;z-index:80;transform:translateX(-50%);width:calc(100% - 32px);max-width:398px;border:1px solid var(--border);border-radius:18px;background:var(--surface);color:var(--text);padding:14px 16px;box-shadow:0 20px 70px rgba(0,0,0,.28);font-weight:700}.toast.warn{border-color:#e4c27d;color:#e4c27d}@media(max-width:370px){.hero h2{font-size:28px}.grid{gap:8px}.product>div{padding:10px}.bottom-nav button{font-size:8px}.two,.photos{grid-template-columns:1fr}.admin-stats{grid-template-columns:1fr 1fr}}
CSS

log "Installing dependencies and building"
cd "$MINIAPP_DIR"
npm install
npm run build

log "Updating project static build"
rm -rf "$STATIC_MINIAPP_DIR"
mkdir -p "$STATIC_MINIAPP_DIR"
cp -a dist/. "$STATIC_MINIAPP_DIR/"

if [[ -d "$PUBLIC_ROOT" ]]; then
  log "Updating public /var/www build"
  if [[ $EUID -eq 0 ]]; then
    rm -rf "$PUBLIC_STATIC"
    mkdir -p "$PUBLIC_STATIC"
    cp -a "$PROJECT_ROOT/static/." "$PUBLIC_STATIC/"
    chown -R www-data:www-data "$PUBLIC_ROOT"
    find "$PUBLIC_ROOT" -type d -exec chmod 755 {} \;
    find "$PUBLIC_ROOT" -type f -exec chmod 644 {} \;
    nginx -t && (systemctl reload nginx || service nginx reload || true)
  else
    log "Not root: skip /var/www sync. Run with sudo to update public build."
  fi
fi

log "Done. Open Mini App and hard refresh if needed."
