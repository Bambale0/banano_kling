import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from './api.js';
import './styles.css';

const flows = [
  { key: 'post', label: 'Пост / Контент', eyebrow: 'caption + CTA', price: 15, ratio: '1:1', icon: '✦', hint: 'готовый текст, хук, структура и hashtags' },
  { key: 'image', label: 'AI Визуал', eyebrow: 'image prompt', price: 30, ratio: '4:5', icon: '◐', hint: 'обложка, афиша, промо-креатив или мудборд' },
  { key: 'video', label: 'Reels / Stories', eyebrow: 'motion script', price: 60, ratio: '9:16', icon: '⌁', hint: 'сценарий кадра, движение, монтаж и голос' },
  { key: 'tryon', label: 'Look / примерка', eyebrow: 'style board', price: 45, ratio: '4:5', icon: '◇', hint: 'образ для выступления, аксессуары, референс' },
  { key: 'prompt', label: 'Prompt Lab', eyebrow: 'improve', price: 5, ratio: 'auto', icon: '⌘', hint: 'улучшает сырой запрос до AI-ready промпта' },
];

const presets = [
  'Фигуристка · соревнования',
  'Тренер / школа',
  'Бренд аксессуаров',
  'SMM прогрев',
  'Запуск коллекции',
];

const examples = [
  'Reels: 3 детали образа, которые делают выступление дороже',
  'Пост: как собрать ледовый look перед соревнованием',
  'Сторис-серия: новая коллекция 2Loop + опрос + CTA',
];

const fallbackProducts = [
  { id: 1, name: 'Ice Loop Set', category: 'Соревнования', price: 2900, stock: 8, badge: 'premium', description: 'Набор аксессуаров для чистого ледового образа.', images: ['/static/shop/products/401698072_bd0a44cf.jpg'] },
  { id: 2, name: 'Crystal Covers', category: 'Аксессуары', price: 1900, stock: 12, badge: '2Loop', description: 'Чехлы и детали для тренировок и выступлений.', images: ['/static/shop/products/459078071_b94d7b9f.jpg'] },
];

function fmt(value) {
  return `${Number(value || 0).toLocaleString('ru-RU')} GOE`;
}

function money(value) {
  return `${Number(value || 0).toLocaleString('ru-RU')} ₽`;
}

function loadLocal(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); } catch { return fallback; }
}

function saveLocal(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* noop */ }
}

function normalizeHistory(data) {
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.history)) return data.history;
  return [];
}

function resultText(data) {
  return data?.text || data?.result?.text || data?.result?.caption || data?.result?.description || data?.result?.url || data?.message || '';
}

function App() {
  const tg = window.Telegram?.WebApp;
  const [active, setActive] = useState('create');
  const [me, setMe] = useState({ user: null, isAdmin: false });
  const [wallet, setWallet] = useState({ balance: 0, tariff: 'Starter', spent: 0 });
  const [history, setHistory] = useState(() => loadLocal('2loop_content_history', []));
  const [products, setProducts] = useState(fallbackProducts);
  const [toast, setToast] = useState(null);
  const [booting, setBooting] = useState(true);
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    tg?.ready?.();
    tg?.expand?.();
    tg?.setHeaderColor?.('#f6eee6');
    tg?.setBackgroundColor?.('#f6eee6');
    Promise.allSettled([api.me(), api.goeBalance(), api.contentHistory(), api.products(false)])
      .then(([meRes, goeRes, histRes, productsRes]) => {
        if (meRes.status === 'fulfilled') setMe(meRes.value || { user: null, isAdmin: false });
        const needsTelegramAuth = [goeRes, histRes].some((result) => (
          result.status === 'rejected' && String(result.reason?.message || '').includes('auth_required')
        ));
        setAuthRequired(needsTelegramAuth);
        if (goeRes.status === 'fulfilled') setWallet({
          balance: goeRes.value.balance ?? goeRes.value.goe ?? 0,
          tariff: goeRes.value.tariff || 'Starter',
          spent: goeRes.value.spent || 0,
        });
        if (histRes.status === 'fulfilled') {
          const remote = normalizeHistory(histRes.value);
          if (remote.length) setHistory(remote);
        }
        if (productsRes.status === 'fulfilled' && Array.isArray(productsRes.value.products)) {
          setProducts(productsRes.value.products.filter(Boolean));
        }
      })
      .finally(() => setBooting(false));
  }, []);

  useEffect(() => saveLocal('2loop_content_history', history.slice(0, 50)), [history]);

  useEffect(() => {
    if (!booting && active === 'admin' && !me.isAdmin) setActive('create');
  }, [active, booting, me.isAdmin]);

  function notify(message, type = 'ok') {
    setToast({ message, type });
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => setToast(null), 3200);
  }

  return (
    <div className="app">
      <div className="aurora aurora-a" />
      <div className="aurora aurora-b" />
      <main className="phone-shell">
        <Topbar me={me} wallet={wallet} setActive={setActive} />
        {booting ? <Loading /> : null}
        {!booting && authRequired ? <AuthNotice /> : null}
        <AnimatePresence mode="wait">
          {!booting && active === 'create' ? <Create key="create" tg={tg} wallet={wallet} setWallet={setWallet} history={history} setHistory={setHistory} notify={notify} authRequired={authRequired} /> : null}
          {!booting && active === 'wallet' ? <Wallet key="wallet" wallet={wallet} setWallet={setWallet} setActive={setActive} notify={notify} /> : null}
          {!booting && active === 'history' ? <History key="history" history={history} setActive={setActive} /> : null}
          {!booting && active === 'catalog' ? <Catalog key="catalog" products={products} notify={notify} /> : null}
          {!booting && active === 'admin' && me.isAdmin ? <Admin key="admin" me={me} wallet={wallet} products={products} history={history} /> : null}
        </AnimatePresence>
        <BottomNav active={active} setActive={setActive} isAdmin={me.isAdmin} />
      </main>
      <Toast toast={toast} />
    </div>
  );
}

function Topbar({ me, wallet, setActive }) {
  const name = me?.user?.first_name || me?.user?.username || 'creator';
  return (
    <header className="topbar glass">
      <button className="brand-lockup" onClick={() => setActive('create')} aria-label="2Loop home">
        <span className="brand-mark">2</span>
        <span><b>2Loop</b><small>pastel grunge studio</small></span>
      </button>
      <button className="wallet-chip" onClick={() => setActive('wallet')}>
        <small>{name}</small>
        <b>{fmt(wallet.balance)}</b>
      </button>
    </header>
  );
}

function Loading() {
  return <section className="screen"><div className="loading-card glass"><div className="spinner" /><h2>Собираем atelier</h2><p>Синхронизируем GOE, дневник и доступные сценарии генерации.</p></div></section>;
}

function AuthNotice() {
  return (
    <section className="auth-notice glass" role="status">
      <b>Нужна авторизация Telegram</b>
      <p>Баланс GOE, история и генерации доступны после открытия Mini App внутри Telegram.</p>
      <a href="https://t.me/Two_loop_bot?startapp=app">Открыть в Telegram</a>
    </section>
  );
}

function Create({ tg, wallet, setWallet, history, setHistory, notify, authRequired }) {
  const [flow, setFlow] = useState(flows[0]);
  const [form, setForm] = useState({ preset: presets[0], prompt: '', tone: 'пастельный grunge', goal: 'продажи и вовлечение', references: 'без референса' });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const canGenerate = form.prompt.trim().length > 2 && !busy;
  const lowBalance = Number(wallet.balance || 0) < flow.price;

  async function generate() {
    if (!form.prompt.trim()) return notify('Добавьте задачу для генерации', 'warn');
    if (authRequired) return notify('Откройте Mini App внутри Telegram для генерации', 'warn');
    if (lowBalance) return notify(`Не хватает GOE: нужно ${flow.price}`, 'warn');
    setBusy(true);
    try {
      const payload = {
        type: flow.key,
        kind: flow.key,
        aspectRatio: flow.ratio,
        prompt: `[2Loop] ${flow.label}. Профиль: ${form.preset}. Задача: ${form.prompt}. Тон: ${form.tone}. Цель: ${form.goal}. Референсы: ${form.references}. Сформируй готовый результат без оператора.`,
        topic: form.prompt,
        audience: form.preset,
        tone: form.tone,
        goal: form.goal,
        cost: flow.price,
        telegramUser: tg?.initDataUnsafe?.user,
      };
      const data = await api.generateContent(payload);
      const output = resultText(data) || 'Задача создана. Результат появится в истории после обработки.';
      const next = {
        id: data.task?.taskId || `${Date.now()}-${flow.key}`,
        kind: flow.key,
        title: form.prompt,
        result: output,
        cost: data.cost ?? flow.price,
        createdAt: new Date().toISOString(),
        status: data.status || 'ready',
      };
      setResult(next);
      setHistory([next, ...history].slice(0, 50));
      setWallet((current) => ({ ...current, balance: data.balance ?? Math.max(0, Number(current.balance || 0) - flow.price), spent: Number(current.spent || 0) + flow.price }));
      tg?.HapticFeedback?.notificationOccurred?.('success');
      notify('Готово: 2Loop выполнил генерацию автоматически');
    } catch (error) {
      notify(error.message || 'Генерация недоступна', 'warn');
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.section className="screen create-screen" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <div className="hero-panel">
        <div className="hero-copy">
          <span className="pill">2LOOP PASTEL GRUNGE</span>
          <h1>Создать ледовый контент.</h1>
          <p>Выберите формат, опишите задачу — результат сохранится в дневник.</p>
        </div>
      </div>

      <section className="flow-section" id="generator">
        <div className="section-head"><small>Выбор ветки</small><h2>Что создаём?</h2></div>
        <div className="flow-grid">
          {flows.map((item) => (
            <button key={item.key} className={`flow-card ${flow.key === item.key ? 'active' : ''}`} onClick={() => { setFlow(item); setResult(null); }}>
              <span>{item.icon}</span><small>{item.eyebrow}</small><b>{item.label}</b><em>{item.price} GOE</em>
            </button>
          ))}
        </div>
      </section>

      <section className="composer glass">
        <div className="composer-head">
          <div><small>Автоматизированная вырезка</small><h2>{flow.label}</h2><p>{flow.hint}</p></div>
          <strong>{flow.price} GOE</strong>
        </div>
        <label>Профиль
          <select value={form.preset} onChange={(e) => setForm({ ...form, preset: e.target.value })}>{presets.map((x) => <option key={x}>{x}</option>)}</select>
        </label>
        <label>Входной материал
          <textarea value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} placeholder="Например: нужна сторис-серия для запуска коллекции чехлов, аудитория — родители юных фигуристок" />
        </label>
        {lowBalance ? <div className="low-balance">Нужно {fmt(flow.price)}, сейчас {fmt(wallet.balance)}. Пополните GOE или выберите Prompt Lab.</div> : null}
        <button className="generate-button" disabled={!canGenerate || lowBalance} onClick={generate}>{busy ? 'Собираем…' : `Собрать материал · ${flow.price} GOE`}</button>
      </section>

      {result ? <Result item={result} /> : null}
    </motion.section>
  );
}

function Result({ item }) {
  return (
    <section className="result glass">
      <div className="section-head"><small>{item.status || 'ready'} · {item.cost} GOE</small><h2>Готовый фрагмент</h2></div>
      <pre>{item.result}</pre>
      <button onClick={() => navigator.clipboard?.writeText(item.result)}>Скопировать</button>
    </section>
  );
}

function Wallet({ wallet, setWallet, setActive, notify }) {
  async function refresh() {
    try {
      const data = await api.goeBalance();
      setWallet({ balance: data.balance ?? data.goe ?? wallet.balance, tariff: data.tariff || wallet.tariff, spent: data.spent || wallet.spent });
      notify('GOE баланс обновлён');
    } catch {
      notify('Показываю локальный баланс GOE', 'warn');
    }
  }
  const packages = [
    ['START', 500, 'для пробных постов'],
    ['PRO', 2500, 'для недельного контент-плана'],
    ['ICE STUDIO', 7500, 'для постоянного SMM-цикла'],
  ];
  return (
    <motion.section className="screen" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <div className="wallet-hero glass"><small>Валюта продукта</small><h1>{fmt(wallet.balance)}</h1><p>GOE — внутренняя валюта 2Loop. Она списывается при генерации и помогает пользователю понимать стоимость до запуска.</p><button className="generate-button" onClick={() => setActive('create')}>Собрать контент</button><button className="ghost-wide" onClick={refresh}>Обновить баланс</button></div>
      <div className="package-grid">{packages.map(([name, amount, text]) => <article className="package-card glass" key={name}><small>{name}</small><b>{fmt(amount)}</b><p>{text}</p><button onClick={() => notify('Платёжный сценарий подключается через backend')}>Выбрать</button></article>)}</div>
      <div className="metric-grid"><Metric value={wallet.spent || 0} label="GOE потрачено" /><Metric value="24/7" label="автоматизация" /><Metric value="5+" label="веток генерации" /></div>
    </motion.section>
  );
}

function History({ history, setActive }) {
  return (
    <motion.section className="screen" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <div className="section-head wide"><small>Архив генераций</small><h1>Дневник 2Loop</h1><p>Результаты генераций, статусы задач и списания GOE доступны без участия оператора.</p></div>
      {!history.length ? <div className="empty glass"><h2>Пока пусто</h2><p>Создайте первый пост, визуал или SMM-сценарий.</p><button onClick={() => setActive('create')}>К генератору</button></div> : <div className="history-list">{history.map((item) => <article className="history-card glass" key={item.id || `${item.createdAt}-${item.title}`}><small>{item.kind || 'content'} · {item.createdAt ? new Date(item.createdAt).toLocaleString('ru-RU') : 'сейчас'} · {item.cost || 0} GOE</small><h2>{item.title || 'Генерация'}</h2><pre>{item.result || item.text || item.content || 'Результат обрабатывается'}</pre></article>)}</div>}
    </motion.section>
  );
}

function Catalog({ products, notify }) {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => products.filter((p) => `${p.name} ${p.category} ${p.description}`.toLowerCase().includes(query.toLowerCase())), [products, query]);
  return (
    <motion.section className="screen" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <div className="section-head wide"><small>Каталог + контент</small><h1>Ледовые вырезки</h1><p>Каталог остаётся рядом с генератором: карточки можно использовать как входной материал для постов и reels.</p></div>
      <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск по товарам" />
      <div className="product-grid">{visible.map((product) => <article className="product-card glass" key={product.id}><img src={product.images?.[0] || '/static/shop/products/401698072_bd0a44cf.jpg'} alt="" /><small>{product.category || '2Loop'}</small><h2>{product.name}</h2><p>{product.description}</p><div><b>{money(product.price)}</b><button onClick={() => notify('Добавлено в сценарий контента')}>В сценарий</button></div></article>)}</div>
    </motion.section>
  );
}

function Admin({ me, wallet, products, history }) {
  return (
    <motion.section className="screen" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <div className="section-head wide"><small>Admin overview</small><h1>Пульт 2Loop</h1><p>Админ управляет продуктом, но пользовательский путь остаётся полностью self-service.</p></div>
      {!me.isAdmin ? <div className="empty glass"><h2>Демо-структура</h2><p>Для реальных данных нужен Telegram admin-доступ или ключ backend.</p></div> : null}
      <div className="metric-grid"><Metric value={products.length} label="товаров" /><Metric value={history.length} label="генераций" /><Metric value={wallet.balance} label="GOE баланс" /></div>
      <div className="admin-modules glass"><h2>Модули</h2><p>Пользователи, GOE, генерации, история, каталог, заказы, аналитика, broadcast.</p></div>
    </motion.section>
  );
}

function Metric({ value, label }) {
  return <article className="metric glass"><b>{value}</b><small>{label}</small></article>;
}

function BottomNav({ active, setActive, isAdmin }) {
  const items = [
    ['create', 'Создать', '✦'],
    ['wallet', 'GOE', '◇'],
    ['history', 'История', '⌁'],
    ['catalog', 'Каталог', '◐'],
    ['admin', 'Админ', '⌘'],
  ].filter(([key]) => key !== 'admin' || isAdmin);
  return <nav className="bottom-nav glass">{items.map(([key, label, icon]) => <button key={key} className={active === key ? 'active' : ''} onClick={() => setActive(key)}><span>{icon}</span><small>{label}</small></button>)}</nav>;
}

function Toast({ toast }) {
  return <AnimatePresence>{toast ? <motion.div className={`toast ${toast.type}`} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 20 }}>{toast.message}</motion.div> : null}</AnimatePresence>;
}

createRoot(document.getElementById('root')).render(<App />);
