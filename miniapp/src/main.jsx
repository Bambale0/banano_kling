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
const defaultProductImage = fallbackProducts[0].images[0];
const nav = [
  ['home', 'Главная', '✦'],
  ['catalog', 'Каталог', '⌕'],
  ['saved', 'Избранное', '♡'],
  ['cart', 'Корзина', '◈'],
  ['profile', 'Профиль', '◌'],
  ['admin', 'Админ', '⚙'],
];

function fmt(value) { return `${Number(value || 0).toLocaleString('ru-RU')} ₽`; }
function mainImage(product) { return product.images?.[product.mainImageIndex || 0] || product.images?.[0] || defaultProductImage; }
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
    Promise.allSettled([api.me(), api.settings()])
      .then(async ([meResult, settingsResult]) => {
        const nextMe = meResult.status === 'fulfilled' ? meResult.value : { user: null, isAdmin: false };
        setMe(nextMe);
        if (settingsResult.status === 'fulfilled') setTheme(settingsResult.value.settings?.theme || 'dark');
        try {
          const productsResult = await api.products(Boolean(nextMe?.isAdmin));
          setProducts(safeProducts(productsResult.products || []));
        } catch (error) {
          showToast(error.message || 'Не удалось загрузить каталог', 'warn');
        }
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
