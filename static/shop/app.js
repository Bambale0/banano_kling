const tg = window.Telegram?.WebApp;

const state = {
  products: [],
  categories: [],
  category: "all",
  query: "",
  sort: "popular",
  cart: new Map(),
  meta: {},
};

const els = {
  grid: document.querySelector("#productGrid"),
  template: document.querySelector("#productTemplate"),
  chips: document.querySelector("#categoryChips"),
  search: document.querySelector("#searchInput"),
  sort: document.querySelector("#sortSelect"),
  status: document.querySelector("#statusLine"),
  wbLink: document.querySelector("#wbLink"),
  promoButton: document.querySelector("#promoButton"),
  shareButton: document.querySelector("#shareButton"),
  cartDock: document.querySelector("#cartDock"),
  cartCount: document.querySelector("#cartCount"),
  cartTotal: document.querySelector("#cartTotal"),
  openCartButton: document.querySelector("#openCartButton"),
  closeCartButton: document.querySelector("#closeCartButton"),
  checkoutSheet: document.querySelector("#checkoutSheet"),
  cartList: document.querySelector("#cartList"),
  checkoutForm: document.querySelector("#checkoutForm"),
  checkoutButton: document.querySelector("#checkoutButton"),
  galleryViewer: document.querySelector("#galleryViewer"),
  galleryImage: document.querySelector("#galleryImage"),
  galleryTitle: document.querySelector("#galleryTitle"),
  galleryCounter: document.querySelector("#galleryCounter"),
  galleryDots: document.querySelector("#galleryDots"),
  galleryClose: document.querySelector("#galleryClose"),
  galleryPrev: document.querySelector("#galleryPrev"),
  galleryNext: document.querySelector("#galleryNext"),
};

const gallery = {
  product: null,
  images: [],
  index: 0,
};

function money(value) {
  return new Intl.NumberFormat("ru-RU").format(value || 0) + " ₽";
}

function categoryIcon(category) {
  const name = category.toLowerCase();
  if (name.includes("футбол")) return "T";
  if (name.includes("сум")) return "B";
  if (name.includes("гетр")) return "G";
  if (name.includes("чех")) return "C";
  if (name.includes("акс")) return "A";
  return "2L";
}

function productMatches(product) {
  const query = state.query.trim().toLowerCase();
  const inCategory = state.category === "all" || product.category === state.category;
  if (!query) return inCategory;

  const haystack = [
    product.name,
    product.category,
    product.wbArticle,
    product.sellerArticle,
    product.barcode,
  ]
    .join(" ")
    .toLowerCase();
  return inCategory && haystack.includes(query);
}

function sortedProducts(products) {
  const list = [...products];
  if (state.sort === "price-asc") {
    list.sort((a, b) => a.price - b.price);
  } else if (state.sort === "price-desc") {
    list.sort((a, b) => b.price - a.price);
  } else if (state.sort === "name") {
    list.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  } else {
    list.sort((a, b) => Number(b.available) - Number(a.available) || a.category.localeCompare(b.category, "ru"));
  }
  return list;
}

function renderChips() {
  els.chips.replaceChildren();

  const all = document.createElement("button");
  all.className = "chip" + (state.category === "all" ? " active" : "");
  all.type = "button";
  all.textContent = "Все";
  all.addEventListener("click", () => {
    state.category = "all";
    render();
  });
  els.chips.append(all);

  state.categories.forEach((category) => {
    const chip = document.createElement("button");
    chip.className = "chip" + (state.category === category ? " active" : "");
    chip.type = "button";
    chip.textContent = category;
    chip.addEventListener("click", () => {
      state.category = category;
      render();
    });
    els.chips.append(chip);
  });
}

function renderProduct(product) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  const visual = node.querySelector(".product-visual");
  const mark = node.querySelector(".category-mark");
  const images = product.images?.length
    ? product.images
    : product.imageUrl
      ? [{ url: product.imageUrl }]
      : [];
  mark.textContent = categoryIcon(product.category);
  if (product.imageUrl) {
    visual.classList.add("has-image");
    visual.style.backgroundImage = `url("${product.imageUrl}")`;
    mark.remove();
  }
  const photoCount = node.querySelector(".photo-count");
  if (images.length > 1) {
    photoCount.textContent = `${images.length} фото`;
  } else {
    photoCount.remove();
  }
  visual.disabled = images.length === 0;
  visual.addEventListener("click", () => openGallery(product, 0));
  node.querySelector(".category").textContent = product.category;
  node.querySelector("h2").textContent = product.name;
  node.querySelector(".article").textContent = `WB ${product.wbArticle}`;
  node.querySelector(".price").textContent = money(product.price);

  const stock = node.querySelector(".stock");
  stock.textContent = product.available ? `В наличии ${product.stockTotal}` : "Нет в наличии";
  stock.classList.toggle("empty", !product.available);

  const oldPrice = node.querySelector(".old-price");
  if (product.currentPrice && product.currentPrice > product.price) {
    oldPrice.textContent = money(product.currentPrice);
  } else {
    oldPrice.remove();
  }

  const wbLink = node.querySelector(".ghost-link");
  wbLink.href = product.wbUrl;

  const add = node.querySelector(".add-button");
  add.disabled = !product.available;
  add.textContent = product.available ? "В корзину" : "Недоступно";
  add.addEventListener("click", () => addToCart(product));

  return node;
}

function renderGallery() {
  if (!gallery.images.length) return;
  const image = gallery.images[gallery.index];
  els.galleryImage.src = image.url;
  els.galleryImage.alt = gallery.product?.name || "Фото товара";
  els.galleryTitle.textContent = gallery.product?.name || "";
  els.galleryCounter.textContent = `${gallery.index + 1} / ${gallery.images.length}`;
  els.galleryDots.replaceChildren(
    ...gallery.images.map((_, index) => {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "gallery-dot" + (index === gallery.index ? " active" : "");
      dot.addEventListener("click", () => {
        gallery.index = index;
        renderGallery();
      });
      return dot;
    })
  );
}

function openGallery(product, startIndex = 0) {
  const images = product.images?.length
    ? product.images
    : product.imageUrl
      ? [{ url: product.imageUrl }]
      : [];
  if (!images.length) return;
  gallery.product = product;
  gallery.images = images;
  gallery.index = Math.max(0, Math.min(startIndex, images.length - 1));
  els.galleryViewer.classList.add("visible");
  renderGallery();
  tg?.HapticFeedback?.impactOccurred("light");
}

function closeGallery() {
  els.galleryViewer.classList.remove("visible");
}

function shiftGallery(delta) {
  if (!gallery.images.length) return;
  gallery.index = (gallery.index + delta + gallery.images.length) % gallery.images.length;
  renderGallery();
}

function renderCartList() {
  els.cartList.replaceChildren();
  state.cart.forEach(({ product, qty }) => {
    const row = document.createElement("div");
    row.className = "cart-item";

    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = product.name;
    const meta = document.createElement("span");
    meta.textContent = `WB ${product.wbArticle} · ${money(product.price)} · ${money(product.price * qty)}`;
    info.append(title, meta);

    const controls = document.createElement("div");
    controls.className = "qty-controls";
    const minus = document.createElement("button");
    minus.type = "button";
    minus.textContent = "−";
    minus.addEventListener("click", () => changeQty(product.id, -1));
    const count = document.createElement("strong");
    count.textContent = qty;
    const plus = document.createElement("button");
    plus.type = "button";
    plus.textContent = "+";
    plus.addEventListener("click", () => changeQty(product.id, 1));
    controls.append(minus, count, plus);

    row.append(info, controls);
    els.cartList.append(row);
  });
}

function renderCart() {
  let count = 0;
  let total = 0;

  state.cart.forEach((item) => {
    count += item.qty;
    total += item.qty * item.product.price;
  });

  els.cartDock.classList.toggle("visible", count > 0);
  els.cartCount.textContent = `${count} ${count === 1 ? "товар" : "товаров"}`;
  els.cartTotal.textContent = money(total);
  renderCartList();

  if (tg) {
    tg.MainButton.setText(count > 0 ? `Корзина ${money(total)}` : "Выберите товары");
    if (count > 0) tg.MainButton.show();
    else tg.MainButton.hide();
  }
}

function render() {
  renderChips();
  const filtered = sortedProducts(state.products.filter(productMatches));
  els.grid.replaceChildren(...filtered.map(renderProduct));
  els.status.textContent = filtered.length
    ? `Найдено: ${filtered.length}. Промокод: ${state.meta.promoCode || "2LOOP"}`
    : "Ничего не найдено. Попробуйте другой артикул или категорию.";
  renderCart();
}

function addToCart(product) {
  const current = state.cart.get(product.id);
  state.cart.set(product.id, {
    product,
    qty: current ? current.qty + 1 : 1,
  });
  renderCart();
  tg?.HapticFeedback?.impactOccurred("light");
}

function changeQty(productId, delta) {
  const current = state.cart.get(productId);
  if (!current) return;
  const next = current.qty + delta;
  if (next <= 0) state.cart.delete(productId);
  else state.cart.set(productId, { ...current, qty: next });
  renderCart();
}

function openCart() {
  if (!state.cart.size) return;
  els.checkoutSheet.classList.add("visible");
}

function closeCart() {
  els.checkoutSheet.classList.remove("visible");
}

function setCheckoutLoading(isLoading) {
  els.checkoutButton.disabled = isLoading;
  els.checkoutButton.textContent = isLoading ? "Оформляем..." : "Оформить заказ";
}

function showOrderSuccess(orderId, message) {
  state.cart.clear();
  renderCart();
  closeCart();
  els.status.innerHTML = `✅ Заказ <strong>${orderId}</strong> оформлен. ${message || "Менеджер 2Loop свяжется для подтверждения."}`;
  tg?.HapticFeedback?.notificationOccurred("success");
  tg?.MainButton?.hide();
}

function showOrderError(message) {
  els.status.textContent = message || "Не удалось оформить заказ. Проверьте данные и попробуйте ещё раз.";
  tg?.HapticFeedback?.notificationOccurred("error");
}

async function checkout(event) {
  event?.preventDefault();
  const items = Array.from(state.cart.values());
  if (!items.length) return;
  const form = new FormData(els.checkoutForm);
  const customer = {
    name: String(form.get("name") || "").trim(),
    phone: String(form.get("phone") || "").trim(),
    comment: String(form.get("comment") || "").trim(),
  };
  const delivery = {
    method: String(form.get("deliveryMethod") || "manual"),
    city: String(form.get("city") || "").trim(),
    address: String(form.get("address") || "").trim(),
    price: 0,
  };
  if (!customer.name || !customer.phone || !delivery.city || !delivery.address) {
    tg?.HapticFeedback?.notificationOccurred("error");
    return;
  }

  const lines = items.map(({ product, qty }) => `${product.name} / WB ${product.wbArticle} × ${qty}`);
  const total = items.reduce((sum, item) => sum + item.product.price * item.qty, 0);
  const payload = {
    type: "catalog_order",
    items: items.map(({ product, qty }) => ({
      wbArticle: product.wbArticle,
      name: product.name,
      price: product.price,
      qty,
    })),
    total,
    promoCode: state.meta.promoCode || "2LOOP",
    customer,
    delivery,
    telegramUser: tg?.initDataUnsafe?.user || null,
  };

  setCheckoutLoading(true);
  try {
    const response = await fetch("/api/shop/order", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      throw new Error(result.message || "order api failed");
    }
    showOrderSuccess(result.orderId, result.message);
  } catch (error) {
    showOrderError("Не удалось сохранить заказ. Напишите в поддержку, пожалуйста.");
    const text = encodeURIComponent(
      `Здравствуйте! Хочу оформить заказ 2Loop:\n\n${lines.join("\n")}\n\nИтого: ${money(total)}\nПромокод: ${payload.promoCode}\n\nИмя: ${customer.name}\nТелефон: ${customer.phone}\nДоставка: ${delivery.city}, ${delivery.address}\nСпособ: ${delivery.method}\nКомментарий: ${customer.comment || "-"}`
    );
    window.open(`https://t.me/${state.meta.supportUsername || "design_2Loop7222"}?text=${text}`, "_blank");
  } finally {
    setCheckoutLoading(false);
  }
}

async function loadCatalog() {
  const response = await fetch("/api/catalog", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("catalog api failed");
  const data = await response.json();
  state.products = data.products || [];
  state.categories = data.categories || [];
  state.meta = data;
  els.wbLink.href = data.wildberriesBrandUrl || "#";
}

function bindEvents() {
  els.search.addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });

  els.sort.addEventListener("change", (event) => {
    state.sort = event.target.value;
    render();
  });

  els.checkoutForm.addEventListener("submit", checkout);
  els.openCartButton.addEventListener("click", openCart);
  els.closeCartButton.addEventListener("click", closeCart);
  els.checkoutSheet.addEventListener("click", (event) => {
    if (event.target === els.checkoutSheet) closeCart();
  });
  els.galleryClose.addEventListener("click", closeGallery);
  els.galleryPrev.addEventListener("click", () => shiftGallery(-1));
  els.galleryNext.addEventListener("click", () => shiftGallery(1));
  els.galleryViewer.addEventListener("click", (event) => {
    if (event.target === els.galleryViewer) closeGallery();
  });
  window.addEventListener("keydown", (event) => {
    if (!els.galleryViewer.classList.contains("visible")) return;
    if (event.key === "Escape") closeGallery();
    if (event.key === "ArrowLeft") shiftGallery(-1);
    if (event.key === "ArrowRight") shiftGallery(1);
  });
  els.promoButton.addEventListener("click", () => {
    navigator.clipboard?.writeText(state.meta.promoCode || "2LOOP");
    tg?.HapticFeedback?.notificationOccurred("success");
  });

  els.shareButton.addEventListener("click", () => {
    const url = encodeURIComponent(state.meta.shopUrl || window.location.href);
    const text = encodeURIComponent("Каталог 2Loop для фигурного катания");
    window.open(`https://t.me/share/url?url=${url}&text=${text}`, "_blank");
  });

  tg?.MainButton?.onClick(openCart);
}

async function init() {
  tg?.ready();
  tg?.expand();
  bindEvents();
  try {
    await loadCatalog();
    render();
  } catch (error) {
    els.status.textContent = "Не удалось загрузить каталог. Попробуйте позже.";
  }
}

init();
