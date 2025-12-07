const state = {
  games: [],
  selected: null,
  currencyFilter: "ALL",
  view: "gallery",
  canEdit: false,
};

const IMAGE_FILES = {
  "림버스 컴퍼니": { dir: "LIMBUSCOMPANY", icon: "icon.webp", profile: "profile.png" },
  "소녀전선2 망명": { dir: "GIRLSFRONTLINE", icon: "icon.webp", profile: "profile.png" },
  "명일방주": { dir: "ARKNIGHT", icon: "icon.jpg", profile: "profile.png" },
  "브라운더스트 2": { dir: "BROWNDUST", icon: "icon.webp", profile: "profile.png" },
  "스텔라 소라": { dir: "STELLASORA", icon: "icon.jpg", profile: "profile.png" },
  "니케": { dir: "NIKKE", icon: "icon.jpg", profile: "profile.png" },
  "던파 모바일": { dir: "MDNF", icon: "icon.jpg", profile: "profile.png" },
  "헤이즈 리버브": { dir: "HAZREVERB", icon: "icon.webp", profile: "profile.png" },
};

function imagePath(title, type) {
  const info = IMAGE_FILES[title];
  if (!info) return null;
  const file = type === "icon" ? info.icon : info.profile;
  return `/assets/${info.dir}/${file}`;
}

const el = (id) => document.getElementById(id);

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function renderGallery() {
  const gallery = el("gallery");
  gallery.innerHTML = "";
  const tpl = el("game-card-template");
  state.games.forEach((g) => {
    const node = tpl.content.firstElementChild.cloneNode(true);
    const profile = imagePath(g.title, "profile");
    const icon = imagePath(g.title, "icon");
    const thumb = node.querySelector(".thumb");
    if (profile) {
      thumb.style.backgroundImage = `linear-gradient(180deg, rgba(0,0,0,0.16), rgba(0,0,0,0.32)), url(${profile})`;
      thumb.style.backgroundColor = "#0b1220";
    } else {
      thumb.style.backgroundImage = "none";
    }
    const iconEl = node.querySelector(".game-icon");
    if (icon) {
      iconEl.src = icon;
      iconEl.alt = `${g.title} icon`;
      iconEl.classList.remove("hidden");
    } else {
      iconEl.classList.add("hidden");
    }
    node.querySelector(".card-title").textContent = g.title;
    node.querySelector(".pill").textContent = g.playtime_label;
    node.addEventListener("click", () => selectGame(g.id));
    gallery.appendChild(node);
  });
}

async function loadGames() {
  const games = await fetchJSON("/games?during_play_only=false&include_stopped=false");
  state.games = games;
  renderGallery();
  showView("gallery");
}

function showDetailSkeleton() {
  el("detail-empty").classList.add("hidden");
  el("detail-content").classList.remove("hidden");
  el("detail-title").textContent = "";
  el("detail-playtime").textContent = "";
  el("detail-dates").textContent = "";
  el("game-info").innerHTML = "";
  el("spending-list").innerHTML = "";
  el("currency-list").innerHTML = "";
  el("event-list").innerHTML = "";
  el("character-list").innerHTML = "";
  el("gacha-message").textContent = "";
}

function badgeByRepay(text) {
  if (text === "갱신필요") return "danger";
  if (text === "유의") return "warn";
  return "good";
}

async function selectGame(gameId) {
  const game = state.games.find((g) => g.id === gameId);
  if (!game) return;
  state.selected = game;
   state.currencyFilter = "ALL";
  showView("detail");
  showDetailSkeleton();

  el("detail-title").textContent = game.title;
  const detailIcon = el("detail-icon");
  const gameIcon = imagePath(game.title, "icon");
  if (gameIcon) {
    detailIcon.src = gameIcon;
    detailIcon.alt = `${game.title} icon`;
    detailIcon.classList.remove("hidden");
  } else {
    detailIcon.classList.add("hidden");
  }
  el("detail-playtime").textContent = `${game.playtime_label} / UID ${game.uid ?? "-"}`;
  el("detail-dates").textContent = `시작: ${game.start_date} • 종료: ${
    game.end_date ?? "-"
  }`;

  const info = el("game-info");
  const entries = [
    { label: "게임 시작일", value: game.start_date },
    { label: "진행 날짜", value: game.playtime_label },
    { label: "UID", value: game.uid ?? "-" },
    { label: "쿠폰", value: game.coupon_url ?? "-" },
  ];
  info.innerHTML = entries
    .map(
      (e) =>
        `<div class="info-tile"><h4>${e.label}</h4><p>${e.value || "-"}</p></div>`
    )
    .join("");

  const couponLink = el("detail-coupon");
  if (game.coupon_url) {
    couponLink.classList.remove("hidden");
    couponLink.href = game.coupon_url;
  } else {
    couponLink.classList.add("hidden");
  }
  const gachaMessage = el("gacha-message");
  if (game.gacha_pull_message) {
    gachaMessage.textContent = game.gacha_pull_message;
    gachaMessage.classList.remove("hidden");
  } else {
    gachaMessage.textContent = "";
    gachaMessage.classList.add("hidden");
  }

  await Promise.all([
    loadSpending(gameId),
    loadCurrencies(gameId),
    loadEvents(gameId),
    loadCharacters(gameId),
  ]);
  applyEditState();
}

async function loadSpending(gameId) {
  const list = el("spending-list");
  list.innerHTML = "로딩 중...";
  const spendings = await fetchJSON(`/games/${gameId}/spendings`);
  list.innerHTML = "";
  spendings.forEach((s) => {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <h4>${s.title}</h4>
      <p class="meta">${s.paying} • ${s.type}</p>
      <p class="meta">남은 ${s.remain_date}일 / ${s.is_repaying}</p>
      <div class="row">
        <input type="date" value="${s.paying_date}" data-id="${s.id}">
        <button data-id="${s.id}">상품 추가구매</button>
      </div>
    `;
    const actionBtn = item.querySelector("button");
    if (!state.canEdit) actionBtn.classList.add("disabled-btn");
    actionBtn.addEventListener("click", async (e) => {
      if (!state.canEdit) {
        alert("뷰어 권한입니다.");
        return;
      }
      const date = item.querySelector("input").value;
      try {
        const updated = await fetchJSON(`/spendings/${s.id}/renew`, {
          method: "POST",
          body: JSON.stringify({ paying_date: date }),
        });
        e.target.textContent = "완료!";
        setTimeout(() => (e.target.textContent = "상품 추가구매"), 1200);
        item.querySelector(".meta:nth-child(3)").textContent = `남은 ${updated.remain_date}일 / ${updated.is_repaying}`;
      } catch (err) {
        alert("갱신 실패");
      }
    });
    list.appendChild(item);
  });
}

async function loadCurrencies(gameId) {
  const list = el("currency-list");
  list.innerHTML = "로딩 중...";
  const currencies = await fetchJSON(`/games/${gameId}/currencies`);
  list.innerHTML = "";
  renderCurrencyFilters(currencies);
  loadCurrencyChart(gameId);
  currencies.forEach((c) => {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <h4>${c.title}</h4>
      <p class="meta">보유량 ${c.counts.toLocaleString()}</p>
      <div class="row">
        <input type="number" value="${c.counts}" step="1">
        <button>재화 갱신</button>
      </div>
    `;
    const btn = item.querySelector("button");
    if (!state.canEdit) btn.classList.add("disabled-btn");
    btn.addEventListener("click", async () => {
      if (!state.canEdit) {
        alert("뷰어 권한입니다.");
        return;
      }
      const counts = Number(item.querySelector("input").value || 0);
      try {
        const updated = await fetchJSON(`/currencies/${c.id}/adjust`, {
          method: "POST",
          body: JSON.stringify({ counts }),
        });
        item.querySelector(".meta").textContent = `보유량 ${updated.counts.toLocaleString()}`;
        await loadCurrencies(gameId);
      } catch {
        alert("재화 갱신 실패");
      }
    });
    list.appendChild(item);
  });
}

function renderCurrencyFilters(currencies) {
  const row = el("currency-filters");
  row.innerHTML = "";
  const allChip = document.createElement("button");
  allChip.className = "chip" + (state.currencyFilter === "ALL" ? " active" : "");
  allChip.textContent = "전체";
  allChip.onclick = () => {
    state.currencyFilter = "ALL";
    renderCurrencyFilters(currencies);
    if (state.selected) loadCurrencyChart(state.selected.id);
  };
  row.appendChild(allChip);
  currencies.forEach((c) => {
    const chip = document.createElement("button");
    chip.className = "chip" + (state.currencyFilter === c.title ? " active" : "");
    chip.textContent = c.title;
    chip.onclick = () => {
      state.currencyFilter = c.title;
      renderCurrencyFilters(currencies);
      if (state.selected) loadCurrencyChart(state.selected.id);
    };
    row.appendChild(chip);
  });
}

async function loadCurrencyChart(gameId) {
  const params = new URLSearchParams();
  if (state.currencyFilter !== "ALL") params.append("title", state.currencyFilter);
  params.append("weekly", "true");
  params.append("weeks", "8");
  const qs = params.toString() ? `?${params.toString()}` : "";
  const data = await fetchJSON(`/games/${gameId}/currencies/timeseries${qs}`);
  drawChart(el("currency-chart"), data.buckets);
}

function drawChart(canvas, buckets) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth;
  const h = canvas.height = 200;
  ctx.clearRect(0,0,w,h);
  if (!buckets || buckets.length === 0) return;
  const counts = buckets.map(b => b.count);
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts, 0);
  const pad = 24;
  const stepX = (w - pad * 2) / Math.max(1, buckets.length - 1);
  ctx.strokeStyle = "#d1d5db";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, pad);
  ctx.lineTo(pad, h - pad);
  ctx.lineTo(w - pad, h - pad);
  ctx.stroke();
  ctx.strokeStyle = "#4338ca";
  ctx.lineWidth = 2;
  ctx.beginPath();
  const points = [];
  buckets.forEach((b, i) => {
    const x = pad + stepX * i;
    const norm = (b.count - min) / (max - min || 1);
    const y = h - pad - norm * (h - pad * 2);
    points.push({ x, y, bucket: b });
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#4338ca";
  points.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  attachChartTooltip(canvas, points);
}

function attachChartTooltip(canvas, points) {
  const container = canvas.parentElement;
  if (!container) return;
  container.style.position = container.style.position || "relative";
  let tooltip = container.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip hidden";
    container.appendChild(tooltip);
  }
  const show = (point, rect) => {
    tooltip.textContent = `${point.bucket.date} • ${point.bucket.count.toLocaleString()}`;
    const containerRect = container.getBoundingClientRect();
    tooltip.style.left = `${point.x + rect.left - containerRect.left}px`;
    tooltip.style.top = `${point.y + rect.top - containerRect.top}px`;
    tooltip.classList.remove("hidden");
  };
  const hide = () => tooltip.classList.add("hidden");
  const handleMove = (clientX, clientY) => {
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    let nearest = null;
    let dist = Infinity;
    points.forEach((p) => {
      const d = Math.hypot(p.x - x, p.y - y);
      if (d < dist) {
        nearest = p;
        dist = d;
      }
    });
    if (!nearest || dist > 12) return hide();
    show(nearest, rect);
  };
  canvas.onmousemove = (e) => handleMove(e.clientX, e.clientY);
  canvas.ontouchmove = (e) => {
    const t = e.touches[0];
    if (t) handleMove(t.clientX, t.clientY);
  };
  canvas.onmouseleave = hide;
  canvas.ontouchend = hide;
}

async function loadEvents(gameId) {
  const list = el("event-list");
  list.innerHTML = "로딩 중...";
  const events = await fetchJSON(`/games/${gameId}/events`);
  list.innerHTML = "";
  events.forEach((ev) => {
    const item = document.createElement("div");
    item.className = "list-item";
    const period =
      ev.end_date ? `${ev.start_date} ~ ${ev.end_date}` : `${ev.start_date} ~ 진행중`;
    item.innerHTML = `
      <h4>${ev.title}</h4>
      <p class="meta">${ev.type} • ${ev.priority} • ${period}</p>
      <span class="badge">${ev.state}</span>
    `;
    list.appendChild(item);
  });
}

async function loadCharacters(gameId) {
  const list = el("character-list");
  list.innerHTML = "로딩 중...";
  const chars = await fetchJSON(`/games/${gameId}/characters`);
  list.innerHTML = "";
  const gradeOptions = Array.from(
    new Set(chars.map((c) => c.grade).filter(Boolean))
  );
  chars.forEach((ch) => {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <h4>${ch.title}</h4>
      <p class="meta">Lv ${ch.level ?? "-"} • ${ch.grade ?? "-"} • 돌파 ${ch.overpower ?? 0} • ${ch.position ?? "-"}</p>
      <div class="row">
        <input type="number" value="${ch.level ?? 0}" placeholder="레벨">
        <select class="grade"></select>
      </div>
      <div class="row">
        <select class="overpower"></select>
        <label><input type="checkbox" ${ch.is_have ? "checked" : ""}> 보유</label>
        <button>변경</button>
      </div>
    `;
    const levelInput = item.querySelectorAll(".row:first-child input")[0];
    const gradeSelect = item.querySelector("select.grade");
    const overpowerSelect = item.querySelector("select.overpower");
    const haveInput = item.querySelector('input[type="checkbox"]');

    // grade select options
    const grades = [...new Set([ch.grade, ...gradeOptions].filter(Boolean))];
    gradeSelect.innerHTML =
      `<option value="">등급 선택</option>` +
      grades.map((g) => `<option value="${g}" ${g === ch.grade ? "selected" : ""}>${g}</option>`).join("");

    // overpower select options (0-10)
    const powOptions = Array.from({ length: 11 }, (_, i) => i);
    overpowerSelect.innerHTML = powOptions
      .map((v) => `<option value="${v}" ${v === (ch.overpower ?? 0) ? "selected" : ""}>돌파 ${v}</option>`)
      .join("");

    const btn = item.querySelector("button");
    if (!state.canEdit) btn.classList.add("disabled-btn");
    btn.addEventListener("click", async () => {
      if (!state.canEdit) {
        alert("뷰어 권한입니다.");
        return;
      }
      try {
        await fetchJSON(`/characters/${ch.id}/update`, {
          method: "POST",
          body: JSON.stringify({
            level: Number(levelInput.value),
            grade: gradeSelect.value || null,
            overpower: Number(overpowerSelect.value),
            is_have: haveInput.checked,
          }),
        });
      } catch {
        alert("변경 실패");
      }
    });
    list.appendChild(item);
  });
}

function wireActions() {
  el("btn-back-main").addEventListener("click", () => {
    showView("gallery");
  });

  const settingsBtn = el("btn-settings");
  const panel = el("settings-panel");
  const applyBtn = el("btn-apply-pass");
  const passInput = el("input-pass");
  settingsBtn.addEventListener("click", () => {
    panel.classList.toggle("hidden");
    if (!panel.classList.contains("hidden")) passInput.focus();
  });
  applyBtn.addEventListener("click", () => {
    const val = passInput.value.trim();
    const can = val === "0690";
    setEditMode(can);
    if (!can) alert("암호가 올바르지 않습니다. 뷰어 권한으로 전환됩니다.");
    panel.classList.add("hidden");
    passInput.value = "";
  });

  el("btn-end-game").addEventListener("click", async () => {
    if (!state.canEdit) {
      alert("뷰어 권한입니다.");
      return;
    }
    if (!state.selected) return;
    if (!confirm("이 게임을 종료 처리할까요?")) return;
    try {
      await fetchJSON(`/games/${state.selected.id}/end`, { method: "POST", body: "{}" });
      await loadGames();
      selectGame(state.selected.id);
    } catch {
      alert("종료 처리 실패");
    }
  });

  el("event-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.selected) return;
    if (!state.canEdit) {
      alert("뷰어 권한입니다.");
      return;
    }
    const form = new FormData(e.target);
    const payload = Object.fromEntries(
      Array.from(form.entries()).filter(([, v]) => v !== "")
    );
    if (!payload.start_date) return;
    try {
      await fetchJSON(`/games/${state.selected.id}/events`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      e.target.reset();
      await loadEvents(state.selected.id);
    } catch {
      alert("이벤트 추가 실패");
    }
  });
}

async function init() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch((err) => {
      console.error("SW register failed", err);
    });
  }
  restoreAuth();
  wireActions();
  await loadGames();
  applyEditState();
}

init().catch((err) => {
  console.error(err);
  alert("데이터를 불러오는 중 오류가 발생했습니다.");
});

function showView(view) {
  state.view = view;
  const gallery = el("gallery");
  const detail = el("detail");
  const backBtn = el("btn-back-main");
  if (view === "gallery") {
    gallery.classList.remove("hidden");
    detail.classList.add("hidden");
    backBtn.classList.add("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else {
    gallery.classList.add("hidden");
    detail.classList.remove("hidden");
    backBtn.classList.remove("hidden");
  }
}

function setEditMode(canEdit) {
  state.canEdit = canEdit;
  localStorage.setItem("dashboard-can-edit", canEdit ? "1" : "0");
  applyEditState();
}

function restoreAuth() {
  const stored = localStorage.getItem("dashboard-can-edit") === "1";
  state.canEdit = stored;
  applyEditState();
}

function applyEditState() {
  const chip = el("auth-chip");
  if (state.canEdit) {
    chip.textContent = "편집";
    chip.classList.remove("muted");
  } else {
    chip.textContent = "뷰어";
    chip.classList.add("muted");
  }
  // disable/enable global buttons
  const endBtn = el("btn-end-game");
  if (state.canEdit) {
    endBtn.removeAttribute("disabled");
    endBtn.classList.remove("disabled-btn");
  } else {
    endBtn.setAttribute("disabled", "true");
    endBtn.classList.add("disabled-btn");
  }
  // event form submit button
  const eventSubmit = el("event-form")?.querySelector("button[type=\"submit\"]");
  if (eventSubmit) {
    if (state.canEdit) {
      eventSubmit.removeAttribute("disabled");
      eventSubmit.classList.remove("disabled-btn");
    } else {
      eventSubmit.setAttribute("disabled", "true");
      eventSubmit.classList.add("disabled-btn");
    }
  }
  // detail action buttons already marked during render; toggle if needed
  document.querySelectorAll(".list-item button").forEach((btn) => {
    if (state.canEdit) {
      btn.removeAttribute("disabled");
      btn.classList.remove("disabled-btn");
    } else {
      btn.setAttribute("disabled", "true");
      btn.classList.add("disabled-btn");
    }
  });
}
