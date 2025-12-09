const state = {
  games: [],
  selected: null,
  currencyFilter: "ALL",
  view: "gallery",
  canEdit: false,
  alerts: null,
  tasks: null,
  eventEditId: null,
  characters: [],
  characterFilter: {
    level: "",
    grade: "",
    overpower: "",
    position: "",
  },
  characterOptions: { grades: [], positions: [] },
  currencies: [],
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
const WEEKDAY_LABEL = ["", "일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];

function weekdayLabel(day) {
  if (!day) return "-";
  return WEEKDAY_LABEL[day] || "-";
}

function formatTimeLabel(val) {
  if (!val) return "-";
  return val.toString().slice(0, 5);
}

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
    const titleEl = node.querySelector(".card-title");
    titleEl.textContent = g.title;
    if (g.stop_play) titleEl.classList.add("stopped");
    node.querySelector(".pill").textContent = g.playtime_label;
    node.addEventListener("click", () => selectGame(g.id));
    gallery.appendChild(node);
  });
}

async function loadAlerts() {
  try {
    const alerts = await fetchJSON("/dashboard/alerts");
    state.alerts = alerts;
    renderAlerts();
  } catch (err) {
    console.error("alert load failed", err);
  }
}

function renderAlerts() {
  const banner = el("alert-banner");
  if (!banner) return;
  if (!state.alerts) {
    banner.classList.add("hidden");
    return;
  }
  const { ongoing_count, ongoing_events, tomorrow_refresh_titles } = state.alerts;
  const line1 = el("alert-line1");
  const line2 = el("alert-line2");
  const line3 = el("alert-line3");
  if (line1) {
    line1.textContent =
      ongoing_count > 0
        ? `📢 현재 ${ongoing_count}개의 이벤트가 진행 중이에요!`
        : "오늘은 진행 중인 이벤트가 없어요.";
  }
  if (line2) {
    if (ongoing_count > 0 && ongoing_events?.length) {
      const list = ongoing_events
        .map((ev) => {
          const period = ev.end_date ? `${ev.start_date} ~ ${ev.end_date}` : `${ev.start_date} ~ 진행중`;
          return `${ev.title} • ${ev.type} • ${period}`;
        })
        .join(" / ");
      line2.textContent = list;
      line2.classList.remove("hidden");
    } else {
      line2.textContent = "";
      line2.classList.add("hidden");
    }
  }
  if (line3) {
    const refreshText =
      tomorrow_refresh_titles && tomorrow_refresh_titles.length
        ? `📢 내일은 ${tomorrow_refresh_titles.join(", ")} 주간 초기화되는 날! 숙제 확인!`
        : "내일은 주간 초기화되는 게임이 없어요.";
    line3.textContent = refreshText;
  }
  banner.classList.remove("hidden");
}

async function loadGames() {
  const games = await fetchJSON("/games?during_play_only=false&include_stopped=true");
  state.games = games;
  renderGallery();
  showView("gallery");
}

function showDetailSkeleton() {
  el("detail-empty").classList.add("hidden");
  el("detail-content").classList.remove("hidden");
  el("detail-title").textContent = "";
  el("detail-playtime").textContent = "";
  el("detail-dates").innerHTML = "";
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

function gradeScore(val) {
  if (val == null) return 0;
  const digits = String(val).match(/\d+/);
  if (digits) return parseInt(digits[0], 10);
  const stars = (String(val).match(/[★*]/g) || []).length;
  if (stars > 0) return stars;
  return 0;
}

function sortCharacters(list) {
  return [...list].sort((a, b) => {
    const gDiff = gradeScore(b.grade) - gradeScore(a.grade);
    if (gDiff) return gDiff;
    const oDiff = (b.overpower ?? 0) - (a.overpower ?? 0);
    if (oDiff) return oDiff;
    return (b.level ?? 0) - (a.level ?? 0);
  });
}

async function selectGame(gameId) {
  const game = state.games.find((g) => g.id === gameId);
  if (!game) return;
  state.selected = game;
  state.currencyFilter = "ALL";
  state.characterFilter = { level: "", grade: "", overpower: "", position: "" };
  state.characters = [];
  showView("detail");
  showDetailSkeleton();
  resetEventForm();

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
  el("detail-dates").innerHTML = `시작: ${game.start_date}<br>종료: ${
    game.end_date ?? "-"
  }`;
  const refreshLine = el("detail-refresh");
  const weeklyLabel = weekdayLabel(game.refresh_day);
  const dailyLabel = formatTimeLabel(game.refresh_time);
  refreshLine.innerHTML = `주간 초기화: ${weeklyLabel}<br>일일 초기화: ${dailyLabel}`;

  const info = el("game-info");
  const entries = [
    { label: "게임 시작일", value: game.start_date },
    { label: "진행 날짜", value: game.playtime_label },
    game.uid ? { label: "UID", value: game.uid } : null,
    game.coupon_url ? { label: "쿠폰", value: game.coupon_url } : null,
  ].filter(Boolean);
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
  const memoToggle = el("memo-toggle");
  const memoBox = el("memo-box");
  const memoBtn = el("btn-memo-toggle");
  const memoDisplay = el("memo-display");
  const memoInput = el("memo-input");
  const memoSave = el("btn-memo-save");
  if (game.memo) {
    memoDisplay.textContent = game.memo;
  } else {
    memoDisplay.textContent = "메모가 없습니다.";
  }
  memoInput.value = game.memo || "";
  memoBox.classList.add("hidden");
  memoBtn.textContent = "메모 보기";
  memoBtn.onclick = () => {
    const hidden = memoBox.classList.toggle("hidden");
    memoBtn.textContent = hidden ? "메모 보기" : "메모 닫기";
  };
  memoToggle.classList.remove("hidden");

  memoSave.onclick = async () => {
    if (!state.canEdit) {
      alert("뷰어 권한입니다.");
      return;
    }
    try {
      const updated = await fetchJSON(`/games/${game.id}/memo`, {
        method: "POST",
        body: JSON.stringify({ memo: memoInput.value }),
      });
      state.selected.memo = updated.memo;
      memoDisplay.textContent = updated.memo || "메모가 없습니다.";
      alert("메모가 저장되었습니다.");
    } catch {
      alert("메모 저장에 실패했습니다.");
    }
  };

  // 던파 모바일은 결제/재화/그래프 숨김
  const hideEconomy = game.title === "던파 모바일";
  const spendingSection = el("spending-section");
  const currencySection = el("currency-section");
  spendingSection.classList.toggle("hidden", hideEconomy);
  currencySection.classList.toggle("hidden", hideEconomy);

  await Promise.all([
    loadTasks(gameId),
    hideEconomy ? Promise.resolve() : loadSpending(gameId),
    hideEconomy ? Promise.resolve() : loadCurrencies(gameId),
    hideEconomy ? Promise.resolve() : loadCurrencyChart(gameId),
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

function resetEventForm() {
  const form = el("event-form");
  if (form) form.reset();
  state.eventEditId = null;
  const submitBtn = el("event-submit-btn");
  if (submitBtn) submitBtn.textContent = "이벤트 추가";
}

async function loadCurrencies(gameId) {
  const list = el("currency-list");
  list.innerHTML = "로딩 중...";
  const currencies = await fetchJSON(`/games/${gameId}/currencies`);
  state.currencies = currencies;
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

async function loadTasks(gameId) {
  const section = el("task-section");
  state.tasks = null;
  if (section) section.classList.add("hidden");
  try {
    const tasks = await fetchJSON(`/games/${gameId}/tasks`);
    state.tasks = tasks;
    renderTasks();
  } catch (err) {
    if (section) section.classList.add("hidden");
    console.warn("tasks unavailable", err);
  }
}

async function saveTaskState() {
  if (!state.tasks) return;
  try {
    const updated = await fetchJSON(`/tasks/${state.tasks.id}/state`, {
      method: "POST",
      body: JSON.stringify({
        daily_state: state.tasks.daily_state,
        weekly_state: state.tasks.weekly_state,
        monthly_state: state.tasks.monthly_state,
      }),
    });
    state.tasks = updated;
    renderTasks();
  } catch (err) {
    alert("숙제 상태 저장에 실패했습니다.");
    throw err;
  }
}

function renderTaskGroup(key, items, states) {
  const block = el(`task-${key}`);
  const list = el(`task-${key}-list`);
  if (!block || !list) return;
  if (!items || items.length === 0) {
    block.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  block.classList.remove("hidden");
  list.innerHTML = "";
  items.forEach((text, idx) => {
    const row = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = Boolean(states[idx]);
    cb.disabled = !state.canEdit;
    cb.addEventListener("change", async () => {
      if (!state.canEdit) {
        cb.checked = !cb.checked;
        alert("뷰어 권한입니다.");
        return;
      }
      state.tasks[`${key}_state`][idx] = cb.checked;
      try {
        await saveTaskState();
      } catch {
        state.tasks[`${key}_state`][idx] = !cb.checked;
        cb.checked = !cb.checked;
      }
    });
    const span = document.createElement("span");
    span.textContent = text;
    row.appendChild(cb);
    row.appendChild(span);
    list.appendChild(row);
  });
}

function renderTasks() {
  const section = el("task-section");
  if (!section) return;
  const data = state.tasks;
  if (!data) {
    section.classList.add("hidden");
    return;
  }
  const hasAny =
    (data.daily_tasks && data.daily_tasks.length) ||
    (data.weekly_tasks && data.weekly_tasks.length) ||
    (data.monthly_tasks && data.monthly_tasks.length);
  section.classList.toggle("hidden", !hasAny);
  if (!hasAny) return;
  renderTaskGroup("daily", data.daily_tasks, data.daily_state);
  renderTaskGroup("weekly", data.weekly_tasks, data.weekly_state);
  renderTaskGroup("monthly", data.monthly_tasks, data.monthly_state);
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
  const base = new URLSearchParams({
    weekly: "true",
    weeks: "15",
    start_date: "2025-11-22",
  });
  const titles =
    state.currencyFilter === "ALL"
      ? state.currencies.map((c) => c.title)
      : [state.currencyFilter];
  const series = await Promise.all(
    titles.map((title) => {
      const params = new URLSearchParams(base.toString());
      params.append("title", title);
      const qs = `?${params.toString()}`;
      return fetchJSON(`/games/${gameId}/currencies/timeseries${qs}`);
    })
  );
  drawChart(el("currency-chart"), series);
}

function drawChart(canvas, series) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth;
  const h = canvas.height = 200;
  ctx.clearRect(0,0,w,h);
  if (!series || series.length === 0) return;
  const allBuckets = series.flatMap((s) => s.buckets || []);
  const valid = allBuckets.filter((b) => b.count !== null && b.count !== undefined);
  if (valid.length === 0) return;
  const counts = valid.map((b) => b.count);
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts, 0);
  const pad = 24;
  const bucketsLen = series[0].buckets.length;
  const stepX = (w - pad * 2) / Math.max(1, bucketsLen - 1);
  ctx.strokeStyle = "#d1d5db";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, pad);
  ctx.lineTo(pad, h - pad);
  ctx.lineTo(w - pad, h - pad);
  ctx.stroke();
  const colors = ["#4338ca", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];
  series.forEach((s, idx) => {
    const color = colors[idx % colors.length];
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    const points = [];
    let lastCount = null;
    let lastY = null;
    (s.buckets || []).forEach((b, i) => {
      const x = pad + stepX * i;
      const val = b.count === null || b.count === undefined ? lastCount : b.count;
      if (val === null || val === undefined) {
        points.push({ x, y: null, bucket: b, title: s.title });
        return;
      }
      lastCount = val;
      const norm = (val - min) / (max - min || 1);
      const y = h - pad - norm * (h - pad * 2);
      points.push({ x, y, bucket: b, title: s.title, count: val });
      if (lastY === null) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
      lastY = y;
    });
    ctx.stroke();
    ctx.fillStyle = color;
    points.forEach((p) => {
      if (p.y === null) return;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
      ctx.fill();
    });
    attachChartTooltip(canvas, points);
  });
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
    item.addEventListener("click", () => {
      const form = el("event-form");
      if (!form) return;
      form.title.value = ev.title;
      form.type.value = ev.type;
      form.start_date.value = ev.start_date;
      form.end_date.value = ev.end_date ?? "";
      form.priority.value = ev.priority;
      state.eventEditId = ev.id;
      const submitBtn = el("event-submit-btn");
      if (submitBtn) submitBtn.textContent = "이벤트 수정";
    });
    list.appendChild(item);
  });
}

async function loadCharacters(gameId) {
  const list = el("character-list");
  list.innerHTML = "로딩 중...";
  const chars = await fetchJSON(`/games/${gameId}/characters`);
  state.characters = chars;
  const gradeOptions = [...new Set(chars.map((c) => c.grade).filter(Boolean))];
  const positions = [...new Set(chars.map((c) => c.position).filter(Boolean))];
  state.characterOptions = { grades: gradeOptions, positions };
  renderCharacterFilters(gradeOptions, positions);
  renderCharacters();
}

function applyCharacterFilters(list) {
  return list.filter((c) => {
    const { level, grade, overpower, position } = state.characterFilter;
    if (level && (c.level ?? 0) < Number(level)) return false;
    if (overpower && (c.overpower ?? 0) < Number(overpower)) return false;
    if (grade && c.grade !== grade) return false;
    if (position && c.position !== position) return false;
    return true;
  });
}

function renderCharacterFilters(grades, positions) {
  const gradeSelect = el("filter-grade");
  const posSelect = el("filter-position");
  gradeSelect.innerHTML =
    `<option value="">등급 전체</option>` +
    grades.map((g) => `<option value="${g}">${g}</option>`).join("");
  posSelect.innerHTML =
    `<option value="">포지션 전체</option>` +
    positions.map((p) => `<option value="${p}">${p}</option>`).join("");
  gradeSelect.value = state.characterFilter.grade || "";
  posSelect.value = state.characterFilter.position || "";
  el("filter-level").value = state.characterFilter.level || "";
  el("filter-overpower").value = state.characterFilter.overpower || "";
}

function renderCharacters() {
  const list = el("character-list");
  list.innerHTML = "";
  const chars = applyCharacterFilters(state.characters);
  const sorted = sortCharacters(chars);
  sorted.forEach((ch) => {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <h4>${ch.title}</h4>
      <p class="meta">Lv ${ch.level ?? "-"} • ${ch.grade ?? "-"} • 돌파 ${ch.overpower ?? 0} • ${ch.position ?? "-"}</p>
      <div class="row compact">
        <input class="level-input" type="number" value="${ch.level ?? 0}" placeholder="레벨">
        <select class="grade"></select>
        <select class="overpower"></select>
        <label class="inline-check"><input type="checkbox" ${ch.is_have ? "checked" : ""}> 보유</label>
        <button class="small-btn">변경</button>
      </div>
    `;
    const levelInput = item.querySelector(".level-input");
    const gradeSelect = item.querySelector("select.grade");
    const overpowerSelect = item.querySelector("select.overpower");
    const haveInput = item.querySelector('input[type="checkbox"]');

    // grade select options
    const grades = [
      ...new Set([ch.grade, ...state.characterOptions.grades].filter(Boolean)),
    ];
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

function renderVersion() {
  const versionEl = el("version-text");
  if (!versionEl) return;
  const today = new Date().toISOString().slice(0, 10);
  versionEl.textContent = `2025-12-07 최초 발행, ${today} 업데이트, 현재 버전 v.1.1.0`;
}

function wireActions() {
  el("btn-back-main").addEventListener("click", () => {
    showView("gallery");
  });
  const authToggle = el("auth-toggle");
  authToggle.addEventListener("click", () => {
    if (state.canEdit) {
      setEditMode(false);
      return;
    }
    const val = prompt("편집 모드 암호를 입력하세요.");
    const can = val === "0690";
    setEditMode(can);
    if (!can) alert("암호가 올바르지 않습니다. 뷰어 권한으로 전환됩니다.");
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
    const submitBtn = el("event-submit-btn");
    if (submitBtn) {
      submitBtn.setAttribute("disabled", "true");
      submitBtn.classList.add("disabled-btn");
      submitBtn.textContent = state.eventEditId ? "수정 중..." : "추가 중...";
    }
    try {
      const url = state.eventEditId
        ? `/games/${state.selected.id}/events/${state.eventEditId}`
        : `/games/${state.selected.id}/events`;
      const method = state.eventEditId ? "PUT" : "POST";
      await fetchJSON(url, {
        method,
        body: JSON.stringify(payload),
      });
      resetEventForm();
      await loadEvents(state.selected.id);
      await loadAlerts();
    } catch {
      alert("이벤트 추가 실패");
    } finally {
      if (submitBtn) {
        submitBtn.removeAttribute("disabled");
        submitBtn.classList.remove("disabled-btn");
        submitBtn.textContent = state.eventEditId ? "이벤트 수정" : "이벤트 추가";
      }
    }
  });
  el("event-reset-btn").addEventListener("click", () => resetEventForm());

  const lvlFilter = el("filter-level");
  const gradeFilter = el("filter-grade");
  const opFilter = el("filter-overpower");
  const posFilter = el("filter-position");
  const resetFilter = el("filter-reset");
  const applyFilters = () => {
    state.characterFilter = {
      level: lvlFilter.value,
      grade: gradeFilter.value,
      overpower: opFilter.value,
      position: posFilter.value,
    };
    renderCharacters();
  };
  [lvlFilter, gradeFilter, opFilter, posFilter].forEach((elmt) => {
    elmt.addEventListener("input", applyFilters);
    elmt.addEventListener("change", applyFilters);
  });
  resetFilter.addEventListener("click", () => {
    lvlFilter.value = "";
    gradeFilter.value = "";
    opFilter.value = "";
    posFilter.value = "";
    applyFilters();
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
  await loadAlerts();
  await loadGames();
  renderVersion();
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
  const chip = el("auth-toggle");
  if (state.canEdit) {
    chip.textContent = "편집";
    chip.classList.remove("muted");
    chip.classList.add("active");
  } else {
    chip.textContent = "뷰어";
    chip.classList.add("muted");
    chip.classList.remove("active");
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
  const memoInput = el("memo-input");
  const memoSave = el("btn-memo-save");
  if (memoInput) memoInput.disabled = !state.canEdit;
  if (memoSave) {
    memoSave.disabled = !state.canEdit;
    memoSave.classList.toggle("disabled-btn", !state.canEdit);
  }
  document.querySelectorAll("#task-section input[type=\"checkbox\"]").forEach((cb) => {
    cb.disabled = !state.canEdit;
  });
}
