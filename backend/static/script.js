const state = {
  games: [],
  selected: null,
  currencyFilter: "ALL",
  view: "gallery",
  canEdit: false,
  alerts: null,
  tasks: null,
  taskEdit: false,
  taskDraft: null,
  eventEditId: null,
  taskCollapsed: { daily: false, weekly: false, monthly: false },
  characters: [],
  spendingDraft: {},
  spendingEdit: {},
  adminToken: null,
  alertsExpanded: false,
  spendingAlertsExpanded: false,
  refreshAlertsExpanded: false,
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

const AUTH_TOKEN_KEY = "dashboard-admin-token";

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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = headers["X-Admin-Token"] || state.adminToken;
  if (token) headers["X-Admin-Token"] = token;
  const res = await fetch(url, {
    headers,
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
    const badges = node.querySelector(".task-badges");
    if (badges) {
      const badgeMap = {
        daily: g.daily_complete,
        weekly: g.weekly_complete,
        monthly: g.monthly_complete,
      };
      Object.entries(badgeMap).forEach(([key, done]) => {
        const b = badges.querySelector(`[data-type="${key}"]`);
        if (b) {
          b.classList.remove("done", "pending");
          b.classList.add(done ? "done" : "pending");
          b.textContent = key === "daily" ? "일" : key === "weekly" ? "주" : "월";
        }
      });
      badges.classList.remove("hidden");
    }
    node.addEventListener("click", () => selectGame(g.id));
    gallery.appendChild(node);
  });
}

async function loadAlerts() {
  try {
    const alerts = await fetchJSON("/dashboard/alerts");
    state.alerts = alerts;
    state.alertsExpanded = false;
    state.spendingAlertsExpanded = false;
    state.refreshAlertsExpanded = false;
    renderAlerts();
  } catch (err) {
    console.error("alert load failed", err);
  }
}

function canToggleAlerts() {
  return Boolean(
    state.alerts &&
      state.alerts.ongoing_count > 0 &&
      state.alerts.ongoing_events &&
      state.alerts.ongoing_events.length
  );
}

function toggleAlertsList() {
  if (!canToggleAlerts()) return;
  state.alertsExpanded = !state.alertsExpanded;
  renderAlerts();
}

function canToggleSpendingAlerts() {
  return Boolean(
    state.alerts &&
      state.alerts.spending_due_count > 0 &&
      state.alerts.spending_due &&
      state.alerts.spending_due.length
  );
}

function toggleSpendingAlerts() {
  if (!canToggleSpendingAlerts()) return;
  state.spendingAlertsExpanded = !state.spendingAlertsExpanded;
  renderAlerts();
}

function toggleRefreshAlerts() {
  if (!state.alerts?.refresh_by_day?.length) return;
  state.refreshAlertsExpanded = !state.refreshAlertsExpanded;
  renderAlerts();
}

function renderAlerts() {
  const banner = el("alert-banner");
  if (!banner) return;
  if (!state.alerts) {
    banner.classList.add("hidden");
    return;
  }
  const { ongoing_count, ongoing_events, refresh_by_day } = state.alerts;
  const line1 = el("alert-line1");
  const line2 = el("alert-line2");
  const spendingLine = el("alert-spending-line");
  const spendingList = el("alert-spending-list");
  const refreshLine = el("alert-refresh-line");
  const refreshList = el("alert-refresh-list");
  const canToggle = canToggleAlerts();
  const canToggleSpending = canToggleSpendingAlerts();
  if (line1) {
    line1.textContent =
      ongoing_count > 0
        ? `📢 현재 ${ongoing_count}개의 이벤트가 진행 중이에요!`
        : "현재 진행 중인 이벤트가 없어요.";
    line1.disabled = !canToggle;
    line1.setAttribute("aria-expanded", canToggle ? String(state.alertsExpanded) : "false");
  }
  if (line2) {
    if (canToggle) {
      const order = [];
      const counts = {};
      ongoing_events.forEach((ev) => {
        if (!counts[ev.game_title]) {
          counts[ev.game_title] = 0;
          order.push(ev.game_title);
        }
        counts[ev.game_title] += 1;
      });
      const list = order.map((title) => `${title}, ${counts[title]}개`).join("\n");
      line2.textContent = list;
      line2.classList.toggle("hidden", !state.alertsExpanded);
    } else {
      line2.textContent = "";
      line2.classList.add("hidden");
    }
  }
  if (spendingLine) {
    const spendingCount = state.alerts.spending_due_count || 0;
    spendingLine.textContent =
      spendingCount > 0
        ? `📢 현재 ${spendingCount}개의 과금 확인이 필요해요.`
        : "현재 확인 필요한 과금 사항이 없어요.";
    spendingLine.disabled = !canToggleSpending;
    spendingLine.setAttribute(
      "aria-expanded",
      canToggleSpending ? String(state.spendingAlertsExpanded) : "false"
    );
  }
  if (spendingList) {
    if (canToggleSpending) {
      const lines = state.alerts.spending_due
        .map((s) => `${s.game_title}, ${s.spending_title}, 남은 ${s.remain_date}일`)
        .join("\n");
      spendingList.textContent = lines;
      spendingList.classList.toggle("hidden", !state.spendingAlertsExpanded);
    } else {
      spendingList.textContent = "";
      spendingList.classList.add("hidden");
    }
  }
  if (refreshLine) {
    const today = new Date();
    const tomorrowDay = ((today.getDay() + 1) % 7) + 1; // JS getDay: Sun=0
    const tomorrowList =
      refresh_by_day?.find((row) => row.weekday === tomorrowDay)?.titles || [];
    const count = tomorrowList.length;
    refreshLine.textContent =
      count > 0
        ? `📢 내일 주간 초기화되는 게임은 ${count}개입니다.`
        : "내일 주간 초기화되는 게임이 없어요.";
    refreshLine.disabled = !(refresh_by_day?.length && count > 0);
    refreshLine.setAttribute(
      "aria-expanded",
      refresh_by_day?.length && count > 0 ? String(state.refreshAlertsExpanded) : "false"
    );
  }
  if (refreshList) {
    if (refresh_by_day?.length) {
      const weekdayLabels = ["", "일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];
      const today = new Date();
      const tomorrowDay = ((today.getDay() + 1) % 7) + 1;
      const lines = refresh_by_day.map((row) => {
        const label = weekdayLabels[row.weekday] || "-";
        const items = row.titles.length ? row.titles.join(", ") : "없음";
        const cls = row.weekday === tomorrowDay ? "today" : "";
        return `<span class="${cls}">${label}: ${items}</span>`;
      });
      refreshList.innerHTML = lines.join("<br>");
      refreshList.classList.toggle("hidden", !state.refreshAlertsExpanded);
    } else {
      refreshList.textContent = "";
      refreshList.classList.add("hidden");
    }
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
  state.spendingDraft = {};
  state.spendingEdit = {};
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

  await Promise.all([loadTasks(gameId), loadEvents(gameId), loadCharacters(gameId)]);
  if (!hideEconomy) {
    await loadCurrencies(gameId);
    await loadSpending(gameId);
  } else {
    await loadSpending(gameId);
  }
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
    const mode = s.reward_mode || (s.type.includes("패스") ? "ONCE" : "DAILY");
    const editing = Boolean(state.spendingEdit[s.id]);
    const draft =
      state.spendingDraft[s.id] ||
      {
        reward_mode: mode,
        rewards: (s.rewards || []).map((r) => ({ ...r })),
        pass_current_level: s.pass_current_level ?? "",
        pass_max_level: s.pass_max_level ?? "",
      };
    state.spendingDraft[s.id] = draft;
    const summaryRewards = (s.rewards || [])
      .map((r) => `${r.title} ${r.count > 0 ? "+" : ""}${r.count}`)
      .join(", ");
    const passMeta =
      mode === "ONCE" && (s.pass_current_level || s.pass_max_level)
        ? `패스 레벨 ${s.pass_current_level ?? "-"} / ${s.pass_max_level ?? "-"}`
        : "";
    const disabledMode = draft.reward_mode === "DISABLED" || mode === "DISABLED";
    item.innerHTML = `
      <div class="row space-between spending-row">
        <div class="spending-info">
          <h4>${s.title}</h4>
          <p class="meta">${s.paying} • ${s.type}</p>
          <p class="meta">${disabledMode ? "사용 안함" : `남은 ${s.remain_date}일 / ${s.is_repaying}`}</p>
          <p class="meta">${disabledMode ? "보상: 사용 안함" : `보상: ${summaryRewards || "미설정"}`}</p>
          ${passMeta && !disabledMode ? `<p class="meta">${passMeta}</p>` : ""}
        </div>
        <div class="row compact spending-actions">
          <input type="date" value="${s.paying_date}" data-id="${s.id}" ${disabledMode ? "disabled" : ""}>
          <button data-id="${s.id}" ${disabledMode ? "disabled" : ""}>상품 추가구매</button>
          <button class="ghost small-btn" data-edit="${s.id}">${editing ? "편집 취소" : "구성 수정"}</button>
        </div>
      </div>
    `;
    const renewBtn = item.querySelector("button[data-id]");
    if (!state.canEdit) renewBtn.classList.add("disabled-btn");
    renewBtn.addEventListener("click", async () => {
      if (!state.canEdit) {
        alert("뷰어 권한입니다.");
        return;
      }
      const date = item.querySelector("input").value;
      try {
        await fetchJSON(`/spendings/${s.id}/renew`, {
          method: "POST",
          body: JSON.stringify({ paying_date: date }),
        });
        await loadSpending(gameId);
      } catch (err) {
        alert("갱신 실패");
      }
    });
    const editBtn = item.querySelector(`button[data-edit="${s.id}"]`);
    editBtn.addEventListener("click", () => {
      if (!state.canEdit) {
        alert("뷰어 권한입니다.");
        return;
      }
      state.spendingEdit[s.id] = !editing;
      if (!state.spendingEdit[s.id]) {
        state.spendingDraft[s.id] = {
          reward_mode: mode,
          rewards: (s.rewards || []).map((r) => ({ ...r })),
        };
      }
      loadSpending(gameId);
    });

    if (editing) {
      const editor = document.createElement("div");
      editor.className = "stack";
      const modeRow = document.createElement("div");
      modeRow.className = "row compact";
      const modeSelect = document.createElement("select");
      ["DAILY", "ONCE", "DISABLED"].forEach((val) => {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent =
          val === "DAILY" ? "월정액(매일 지급)" : val === "ONCE" ? "패스(1회 지급)" : "사용하지 않음";
        if (draft.reward_mode === val) opt.selected = true;
        modeSelect.appendChild(opt);
      });
      modeSelect.addEventListener("change", () => {
        draft.reward_mode = modeSelect.value;
      });
      modeRow.appendChild(modeSelect);
      editor.appendChild(modeRow);

      const rewardWrap = document.createElement("div");
      rewardWrap.className = "stack";
      if (draft.reward_mode === "DISABLED") {
        const note = document.createElement("p");
        note.className = "meta";
        note.textContent = "사용하지 않음: 일자 체크/보상 지급/알림 제외";
        rewardWrap.appendChild(note);
      }
      const passWrap = document.createElement("div");
      passWrap.className = "row compact";
      if (draft.reward_mode === "ONCE") {
        const cur = document.createElement("input");
        cur.type = "number";
        cur.placeholder = "현재 레벨";
        cur.value = draft.pass_current_level ?? "";
        cur.addEventListener("input", () => {
          draft.pass_current_level = cur.value === "" ? "" : Number(cur.value);
        });
        const max = document.createElement("input");
        max.type = "number";
        max.placeholder = "최고 레벨";
        max.value = draft.pass_max_level ?? "";
        max.addEventListener("input", () => {
          draft.pass_max_level = max.value === "" ? "" : Number(max.value);
        });
        passWrap.appendChild(cur);
        passWrap.appendChild(max);
        editor.appendChild(passWrap);
      }
      if (draft.reward_mode !== "DISABLED") {
        (draft.rewards || []).forEach((rw, ridx) => {
          const rrow = document.createElement("div");
          rrow.className = "row compact";
          const select = document.createElement("select");
          const defaultOpt = document.createElement("option");
          defaultOpt.value = "";
          defaultOpt.textContent = "재화 선택";
          select.appendChild(defaultOpt);
          (state.currencies || []).forEach((c) => {
            const opt = document.createElement("option");
            opt.value = c.title;
            opt.textContent = c.title;
            if (c.title === rw.title) opt.selected = true;
            select.appendChild(opt);
          });
          select.value = rw.title || "";
          select.addEventListener("change", () => {
            draft.rewards[ridx].title = select.value;
          });
          const input = document.createElement("input");
          input.type = "number";
          input.value = rw.count ?? 0;
          input.addEventListener("input", () => {
            draft.rewards[ridx].count = Number(input.value || 0);
          });
          const delBtn = document.createElement("button");
          delBtn.type = "button";
          delBtn.textContent = "삭제";
          delBtn.className = "ghost small-btn";
          delBtn.addEventListener("click", () => {
            draft.rewards.splice(ridx, 1);
            loadSpending(gameId);
          });
          rrow.appendChild(select);
          rrow.appendChild(input);
          rrow.appendChild(delBtn);
          rewardWrap.appendChild(rrow);
        });
        const addReward = document.createElement("button");
        addReward.type = "button";
        addReward.textContent = "보상 추가";
        addReward.className = "ghost small-btn";
        addReward.addEventListener("click", () => {
          draft.rewards.push({ title: state.currencies?.[0]?.title || "", count: 0 });
          loadSpending(gameId);
        });
        rewardWrap.appendChild(addReward);
      }
      editor.appendChild(rewardWrap);

      const saveRow = document.createElement("div");
      saveRow.className = "row compact";
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.textContent = "구성 저장";
      saveBtn.addEventListener("click", async () => {
        try {
          await fetchJSON(`/spendings/${s.id}/configure`, {
            method: "POST",
            body: JSON.stringify({
              reward_mode: draft.reward_mode,
              rewards: draft.reward_mode === "DISABLED" ? [] : draft.rewards,
              pass_current_level:
                draft.reward_mode === "ONCE" && draft.pass_current_level !== ""
                  ? Number(draft.pass_current_level)
                  : null,
              pass_max_level:
                draft.reward_mode === "ONCE" && draft.pass_max_level !== ""
                  ? Number(draft.pass_max_level)
                  : null,
            }),
          });
          state.spendingEdit[s.id] = false;
          await loadSpending(gameId);
        } catch {
          alert("구성 저장 실패");
        }
      });
      saveRow.appendChild(saveBtn);
      editor.appendChild(saveRow);
      item.appendChild(editor);
    }

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
  state.taskEdit = false;
  state.taskDraft = null;
  if (section) section.classList.add("hidden");
  try {
    const tasks = await fetchJSON(`/games/${gameId}/tasks`);
    state.tasks = tasks;
    renderTasks();
    const master = el("task-daily-master");
    if (master && !master.dataset.wired) {
      master.dataset.wired = "1";
      master.addEventListener("change", async () => {
        if (!state.canEdit) {
          master.checked = !master.checked;
          alert("뷰어 권한입니다.");
          return;
        }
        if (!state.tasks) return;
        const next = master.checked;
        state.tasks.daily_state = state.tasks.daily_state.map(() => next);
        try {
          await saveTaskState();
        } catch {
          master.checked = !next;
        }
      });
    }
    const toggleBtn = el("task-daily-toggle");
    if (toggleBtn && !toggleBtn.dataset.wired) {
      toggleBtn.dataset.wired = "1";
      toggleBtn.addEventListener("click", () => {
        state.taskCollapsed.daily = !state.taskCollapsed.daily;
        renderTasks();
      });
    }
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
  const isDaily = key === "daily";
  const master = isDaily ? el("task-daily-master") : null;
  const toggleBtn = isDaily ? el("task-daily-toggle") : null;
  const rewards = state.taskEdit
    ? state.taskDraft?.[`${key}_rewards`] || []
    : state.tasks?.[`${key}_rewards`] || [];
  const currencyOptions = state.currencies || [];
  if (!block || !list) return;
  if (!items || items.length === 0) {
    block.classList.add("hidden");
    list.innerHTML = "";
    if (master) master.checked = false;
    return;
  }
  block.classList.remove("hidden");
  list.innerHTML = "";
  if (state.taskEdit) {
    const draft = state.taskDraft?.[`${key}_tasks`] || items;
    draft.forEach((text, idx) => {
      const row = document.createElement("div");
      row.className = "row compact";
      const input = document.createElement("input");
      input.type = "text";
      input.value = text;
      input.addEventListener("input", () => {
        state.taskDraft[`${key}_tasks`][idx] = input.value;
      });
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.textContent = "수정";
      saveBtn.addEventListener("click", async () => {
        state.taskDraft[`${key}_tasks`][idx] = input.value;
      });
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "삭제";
      delBtn.className = "ghost small-btn";
      delBtn.addEventListener("click", () => {
        state.taskDraft[`${key}_tasks`].splice(idx, 1);
        state.taskDraft[`${key}_rewards`].splice(idx, 1);
        renderTasks();
      });
      row.appendChild(input);
      row.appendChild(saveBtn);
      row.appendChild(delBtn);
      list.appendChild(row);

      const rewardWrap = document.createElement("div");
      rewardWrap.className = "reward-list";
      const rewardRows = rewards[idx] || [];
      rewardRows.forEach((rw, ridx) => {
        const rrow = document.createElement("div");
        rrow.className = "row compact reward-row";
        const select = document.createElement("select");
        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = "재화 선택";
        select.appendChild(defaultOpt);
        currencyOptions.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.title;
          opt.textContent = c.title;
          if (c.title === rw.title) opt.selected = true;
          select.appendChild(opt);
        });
        select.value = rw.title || "";
        select.addEventListener("change", () => {
          state.taskDraft[`${key}_rewards`][idx][ridx].title = select.value;
        });
        const inputCount = document.createElement("input");
        inputCount.type = "number";
        inputCount.value = rw.count ?? 0;
        inputCount.min = "0";
        inputCount.addEventListener("input", () => {
          state.taskDraft[`${key}_rewards`][idx][ridx].count = Number(inputCount.value || 0);
        });
        const delReward = document.createElement("button");
        delReward.type = "button";
        delReward.textContent = "보상 삭제";
        delReward.className = "ghost small-btn";
        delReward.addEventListener("click", () => {
          state.taskDraft[`${key}_rewards`][idx].splice(ridx, 1);
          renderTasks();
        });
        rrow.appendChild(select);
        rrow.appendChild(inputCount);
        rrow.appendChild(delReward);
        rewardWrap.appendChild(rrow);
      });
      const addReward = document.createElement("button");
      addReward.type = "button";
      addReward.textContent = "보상 추가";
      addReward.className = "ghost small-btn";
      addReward.addEventListener("click", () => {
        state.taskDraft[`${key}_rewards`][idx].push({ title: currencyOptions[0]?.title || "", count: 0 });
        renderTasks();
      });
      rewardWrap.appendChild(addReward);
      list.appendChild(rewardWrap);
    });
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.textContent = "추가하기";
    addBtn.className = "ghost small-btn";
    addBtn.addEventListener("click", () => {
      state.taskDraft[`${key}_tasks`].push("");
      state.taskDraft[`${key}_rewards`].push([]);
      renderTasks();
    });
    list.appendChild(addBtn);
    return;
  }
  if (master) {
    const allDone = items.length > 0 && states.every(Boolean);
    master.checked = allDone;
    master.disabled = !state.canEdit;
  }
  if (toggleBtn) {
    const collapsed = state.taskCollapsed.daily;
    list.classList.toggle("collapsed", collapsed);
    toggleBtn.textContent = collapsed ? "펼치기" : "접기";
    toggleBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggleBtn.classList.toggle("active", !collapsed);
  }
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
  const editToggle = el("task-edit-toggle");
  const saveBtn = el("task-edit-save");
  const cancelBtn = el("task-edit-cancel");
  [editToggle, saveBtn, cancelBtn].forEach((btn) => {
    if (!btn) return;
    btn.classList.toggle("hidden", !state.canEdit || state.view !== "detail");
  });
  if (editToggle) {
    editToggle.textContent = state.taskEdit ? "편집 중" : "편집하기";
    editToggle.disabled = !state.canEdit;
  }
  if (saveBtn) saveBtn.classList.toggle("hidden", !state.taskEdit);
  if (cancelBtn) cancelBtn.classList.toggle("hidden", !state.taskEdit);
  const dailyHint = el("task-daily-hint");
  const weeklyHint = el("task-weekly-hint");
  const monthlyHint = el("task-monthly-hint");
  const masterRow = document.querySelector(".task-parent-row");
  if (masterRow) masterRow.classList.toggle("hidden", state.taskEdit);
  if (dailyHint) {
    dailyHint.textContent = data.daily_message || "";
    dailyHint.classList.toggle("hidden", !data.daily_message);
  }
  if (weeklyHint) {
    weeklyHint.textContent = data.weekly_message || "";
    weeklyHint.classList.toggle("hidden", !data.weekly_message);
  }
  if (monthlyHint) {
    monthlyHint.textContent = data.monthly_message || "";
    monthlyHint.classList.toggle("hidden", !data.monthly_message);
  }
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
  const today = new Date().toISOString().slice(0, 10);
  const text = `최초 발행 2025-12-07, 업데이트 ${today}, 현재 버전 v.1.2.1`;
  const versionMain = el("version-text-main");
  if (versionMain) versionMain.textContent = text;
}

function wireActions() {
  el("btn-back-main").addEventListener("click", () => {
    showView("gallery");
  });
  const alertToggle = el("alert-line1");
  if (alertToggle) {
    alertToggle.addEventListener("click", () => toggleAlertsList());
    alertToggle.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleAlertsList();
      }
    });
  }
  const spendingToggle = el("alert-spending-line");
  if (spendingToggle) {
    spendingToggle.addEventListener("click", () => toggleSpendingAlerts());
    spendingToggle.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleSpendingAlerts();
      }
    });
  }
  const refreshToggle = el("alert-refresh-line");
  if (refreshToggle) {
    refreshToggle.addEventListener("click", () => toggleRefreshAlerts());
    refreshToggle.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleRefreshAlerts();
      }
    });
  }
  const authToggle = el("auth-toggle");
  const authPanel = el("auth-panel");
  const authForm = el("auth-form");
  const authInput = el("auth-input");
  const authRemember = el("auth-remember");
  const authCancel = el("auth-cancel");
  const hideAuthPanel = () => authPanel?.classList.add("hidden");
  const showAuthPanel = () => {
    if (!authPanel) return;
    authPanel.classList.remove("hidden");
    if (authInput) {
      authInput.value = "";
      authInput.focus();
    }
    if (authRemember) {
      authRemember.checked = Boolean(localStorage.getItem(AUTH_TOKEN_KEY));
    }
  };
  authToggle.addEventListener("click", async () => {
    if (state.canEdit) {
      state.adminToken = null;
      sessionStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(AUTH_TOKEN_KEY);
      setEditMode(false);
      return;
    }
    if (authPanel?.classList.contains("hidden")) showAuthPanel();
    else hideAuthPanel();
  });
  if (authCancel) {
    authCancel.addEventListener("click", () => hideAuthPanel());
  }
  if (authForm) {
    authForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!authInput) return;
      const token = authInput.value.trim();
      if (!token) return;
      const remember = Boolean(authRemember?.checked);
      const submitBtn = el("auth-submit");
      submitBtn?.setAttribute("disabled", "true");
      submitBtn?.classList.add("disabled-btn");
      try {
        await fetchJSON("/auth/verify", { headers: { "X-Admin-Token": token } });
        state.adminToken = token;
        sessionStorage.setItem(AUTH_TOKEN_KEY, token);
        if (remember) {
          localStorage.setItem(AUTH_TOKEN_KEY, token);
        } else {
          localStorage.removeItem(AUTH_TOKEN_KEY);
        }
        setEditMode(true);
        hideAuthPanel();
      } catch {
        state.adminToken = null;
        sessionStorage.removeItem(AUTH_TOKEN_KEY);
        if (!remember) localStorage.removeItem(AUTH_TOKEN_KEY);
        setEditMode(false);
        alert("암호가 올바르지 않습니다. 뷰어 권한으로 전환됩니다.");
      } finally {
        submitBtn?.removeAttribute("disabled");
        submitBtn?.classList.remove("disabled-btn");
      }
    });
  }

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

  const editToggle = el("task-edit-toggle");
  const saveBtn = el("task-edit-save");
  const cancelBtn = el("task-edit-cancel");
  if (editToggle) {
    editToggle.addEventListener("click", () => {
      if (!state.canEdit || !state.tasks) {
        alert("편집 권한이 없습니다.");
        return;
      }
      state.taskEdit = true;
      state.taskDraft = {
        daily_tasks: [...(state.tasks.daily_tasks || [])],
        weekly_tasks: [...(state.tasks.weekly_tasks || [])],
        monthly_tasks: [...(state.tasks.monthly_tasks || [])],
        daily_rewards: (state.tasks.daily_rewards || []).map((row) => row.map((r) => ({ ...r }))),
        weekly_rewards: (state.tasks.weekly_rewards || []).map((row) => row.map((r) => ({ ...r }))),
        monthly_rewards: (state.tasks.monthly_rewards || []).map((row) => row.map((r) => ({ ...r }))),
      };
      renderTasks();
    });
  }
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      state.taskEdit = false;
      state.taskDraft = null;
      renderTasks();
    });
  }
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (!state.canEdit || !state.taskDraft || !state.selected) return;
      try {
        const updated = await fetchJSON(`/games/${state.selected.id}/tasks/update`, {
          method: "POST",
          body: JSON.stringify({
            daily_tasks: state.taskDraft.daily_tasks,
            weekly_tasks: state.taskDraft.weekly_tasks,
            monthly_tasks: state.taskDraft.monthly_tasks,
            daily_rewards: state.taskDraft.daily_rewards,
            weekly_rewards: state.taskDraft.weekly_rewards,
            monthly_rewards: state.taskDraft.monthly_rewards,
          }),
        });
        state.tasks = updated;
        state.taskEdit = false;
        state.taskDraft = null;
        renderTasks();
      } catch (err) {
        alert("숙제 편집 저장에 실패했습니다.");
        console.error(err);
      }
    });
  }
}

async function init() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch((err) => {
      console.error("SW register failed", err);
    });
  }
  await restoreAuth();
  wireActions();
  await Promise.all([loadAlerts(), loadGames()]);
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
  applyEditState();
}

async function restoreAuth() {
  const token = sessionStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem(AUTH_TOKEN_KEY);
  if (!token) {
    setEditMode(false);
    return;
  }
  state.adminToken = token;
  try {
    await fetchJSON("/auth/verify", { headers: { "X-Admin-Token": token } });
    setEditMode(true);
  } catch {
    state.adminToken = null;
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_TOKEN_KEY);
    setEditMode(false);
  }
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
