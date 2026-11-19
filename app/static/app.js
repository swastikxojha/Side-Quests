const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let authMode = "login";
let toastTimer;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function notify(message, kind = "success") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.dataset.kind = kind;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3600);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(body?.detail || "Something went wrong. Please try again.");
  return body;
}

function setFormMessage(form, message, kind = "error") {
  const output = form.querySelector(".message");
  if (output) {
    output.textContent = message;
    output.dataset.kind = kind;
  }
}

function setBusy(button, busy, label) {
  if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.defaultLabel;
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    authMode = tab.dataset.mode;
    document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("selected", item === tab));
    $("#username-row").classList.toggle("hidden", authMode !== "register");
    $("[name=username]").required = authMode === "register";
    $("[name=password]").autocomplete = authMode === "login" ? "current-password" : "new-password";
    $("#auth-submit").innerHTML = `${authMode === "login" ? "Sign in" : "Create account"} <span>→</span>`;
    $("#auth-message").textContent = "";
  });
});

$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const payload = { email: values.get("email"), password: values.get("password") };
  if (authMode === "register") payload.username = values.get("username");
  const button = $("#auth-submit");
  setBusy(button, true, "One moment…");
  try {
    await api(`/api/auth/${authMode === "login" ? "login" : "register"}`, { method: "POST", body: JSON.stringify(payload) });
    await loadApp();
  } catch (error) {
    $("#auth-message").textContent = error.message;
  } finally {
    setBusy(button, false);
    button.innerHTML = `${authMode === "login" ? "Sign in" : "Create account"} <span>→</span>`;
  }
});

$("#forgot").addEventListener("click", async () => {
  const email = $("[name=email]").value;
  if (!email) {
    $("#auth-message").textContent = "Enter your email address first.";
    $("[name=email]").focus();
    return;
  }
  try {
    await api("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
    $("[name=reset_email]").value = email;
    $("#reset-dialog").showModal();
    $("[name=reset_code]").focus();
  } catch (error) {
    $("#auth-message").textContent = error.message;
  }
});

$("#reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  try {
    await api("/api/auth/reset-password", { method: "POST", body: JSON.stringify({
      email: values.get("reset_email"), code: values.get("reset_code"), new_password: values.get("reset_password"),
    }) });
    form.reset();
    $("#reset-dialog").close();
    $("#auth-message").textContent = "Password updated. You can sign in now.";
    notify("Password updated. Sign in with your new password.");
  } catch (error) {
    setFormMessage(form, error.message);
  }
});

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => $(`#${button.dataset.close}`).close());
});

$("#logout").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } finally { location.reload(); }
});

$("#settings-toggle").addEventListener("click", () => {
  $("#dashboard").classList.toggle("hidden");
  $("#settings").classList.toggle("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
});

const interestChoices = ["Programming", "Fitness", "Photography", "Reading", "Creativity", "Learning", "Social", "Career", "Finance", "Adventure"];
$("#interest-options").innerHTML = interestChoices.map((interest) => `
  <label class="interest-option"><input type="checkbox" value="${escapeHtml(interest)}"><span>${escapeHtml(interest)}</span></label>
`).join("");
$("#settings-interest-options").innerHTML = $("#interest-options").innerHTML;

$("#interest-options").addEventListener("change", (event) => {
  if ($$("#interest-options input:checked").length > 3) {
    event.target.checked = false;
    $("#interest-message").textContent = "Choose up to three interests.";
  } else $("#interest-message").textContent = "";
});
$("#settings-interest-options").addEventListener("change", (event) => {
  if ($$("#settings-interest-options input:checked").length > 3) {
    event.target.checked = false;
    setFormMessage($("#settings-interest-form"), "Choose up to three interests.");
  }
});

$("#interest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const interests = $$("#interest-options input:checked").map((input) => input.value);
  try {
    await api("/api/interests", { method: "PUT", body: JSON.stringify({ interests }) });
    notify("Your interests are saved. Fresh quests are ready.");
    await loadApp();
  } catch (error) { setFormMessage(event.currentTarget, error.message); }
});

function renderQuest(quest) {
  const complete = quest.status === "completed";
  const steps = quest.steps || [];
  const stepList = steps.length ? `<ol class="milestones">${steps.map((step) => `
    <li><label><input type="checkbox" data-step="${step.id}" data-quest="${quest.id}" ${step.completed ? "checked" : ""} ${complete ? "disabled" : ""}>
    <span>${escapeHtml(step.title)}</span></label></li>`).join("")}</ol>` : "";
  const completeDisabled = !complete && steps.some((step) => !step.completed);
  return `<article class="quest ${complete ? "is-complete" : ""}">
    ${quest.is_boss ? '<span class="boss-tag">BOSS QUEST</span>' : ""}
    <h4>${escapeHtml(quest.title)}</h4><p>${escapeHtml(quest.description)}</p>
    <small class="due">Due ${quest.due_at ? new Date(quest.due_at).toLocaleDateString() : "this period"}</small>
    <div class="meta"><span>${escapeHtml(quest.category)} · ${quest.estimated_minutes} min · ${escapeHtml(quest.difficulty)}</span><span>✦ ${quest.xp} XP</span></div>
    <div class="progress-track" role="progressbar" aria-label="Quest progress" aria-valuenow="${quest.progress}" aria-valuemin="0" aria-valuemax="100"><i style="width:${quest.progress}%"></i></div>
    ${stepList}
    ${!steps.length && !complete ? `<label class="progress-label">Progress <input type="range" min="0" max="100" value="${quest.progress}" data-progress="${quest.id}" aria-label="Quest progress"></label>` : ""}
    <div class="quest-actions">${complete ? '<span class="done-label">✓ Complete</span>' : `<button data-action="complete" data-id="${quest.id}" ${completeDisabled ? "disabled title='Complete each milestone first'" : ""}>Complete quest</button><button data-action="reroll" data-id="${quest.id}" ${quest.rerolls >= 3 ? "disabled" : ""}>↻ Reroll</button>`}</div>
  </article>`;
}

async function loadApp() {
  try {
    const user = await api("/api/me");
    $("#auth").classList.add("hidden");
    $("#dashboard").classList.remove("hidden");
    $("#loading-state").classList.remove("hidden");
    $("#retry-load").classList.add("hidden");
    $("#settings").classList.add("hidden");
    $("#logout").classList.remove("hidden");
    $("#settings-toggle").classList.remove("hidden");
    $("#username").textContent = user.username;
    $("#rank").textContent = user.rank.toUpperCase();
    $("#level").textContent = `Level ${user.level}`;
    $("#xp-label").textContent = `${user.xp} XP`;
    $("#xp-bar").style.width = `${user.xp_for_level ? user.xp_into_level / user.xp_for_level * 100 : 0}%`;
    $("#streak").textContent = user.streak;
    $("#completed-count").textContent = user.completed_count;
    $("#onboarding").classList.toggle("hidden", user.interests.length > 0);
    $$("#interest-options input").forEach((input) => { input.checked = user.interests.includes(input.value); });
    $$("#settings-interest-options input").forEach((input) => { input.checked = user.interests.includes(input.value); });
    $("[name=profile_name]").value = user.username;
    $("[name=profile_timezone]").value = user.timezone;

    const quests = await api("/api/quests");
    $("#quest-groups").innerHTML = ["daily", "weekly", "monthly"].map((timeframe) => {
      const group = quests.filter((quest) => quest.timeframe === timeframe);
      return `<section class="quest-group"><h3>${timeframe}<span class="count">${group.filter((quest) => quest.status === "active").length} active</span></h3>
        ${group.map(renderQuest).join("") || '<p class="empty-state">Your next quests will appear here.</p>'}</section>`;
    }).join("");

    const [history, achievements, stats] = await Promise.all([
      api("/api/history"), api("/api/achievements"), api("/api/progress/stats"),
    ]);
    $("#history").innerHTML = history.slice(0, 8).map((quest) => `<article class="history-item"><strong>${escapeHtml(quest.title)}</strong><small>${quest.timeframe} · ${quest.status} · ${quest.xp} XP</small></article>`).join("") || '<p class="empty-state">Your completed quests will appear here.</p>';
    $("#achievements").innerHTML = achievements.map((item) => `<article class="achievement-item"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description)}</small><small>✦ ${item.xp_reward} bonus XP</small></article>`).join("") || '<p class="empty-state">Your milestones will appear as you play.</p>';
    const timeframeCards = Object.entries(stats.timeframes).map(([timeframe, values]) => `<article class="stat-card"><small>${timeframe} quests</small><strong>${values.completed}<span> / ${values.assigned}</span></strong><div class="progress-track"><i style="width:${values.assigned ? values.completed / values.assigned * 100 : 0}%"></i></div></article>`).join("");
    const categoryCards = Object.entries(stats.categories).map(([category, values]) => `<article class="stat-card"><small>${escapeHtml(category)}</small><strong>${values.completed}<span> / ${values.assigned}</span></strong><div class="progress-track"><i style="width:${values.assigned ? values.completed / values.assigned * 100 : 0}%"></i></div></article>`).join("");
    $("#stats").innerHTML = `<article class="stat-card"><small>Total XP</small><strong>${stats.total_xp}</strong><div class="progress-track"><i style="width:100%"></i></div></article>${timeframeCards}${categoryCards}`;
    $("#loading-state").classList.add("hidden");
  } catch (error) {
    if (error.message === "Please sign in") return;
    $("#loading-state").classList.add("hidden");
    $("#retry-load").classList.remove("hidden");
    notify(error.message, "error");
  }
}

$("#retry-load").addEventListener("click", loadApp);

$("#quest-groups").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  button.disabled = true;
  try {
    const result = await api(`/api/quests/${button.dataset.id}/${button.dataset.action}`, { method: "POST" });
    notify(button.dataset.action === "complete" ? `Quest complete! +${result.xp_earned} XP` : `Quest rerolled. New reward: ${result.xp} XP`);
    await loadApp();
  } catch (error) { notify(error.message, "error"); button.disabled = false; }
});

$("#quest-groups").addEventListener("change", async (event) => {
  const checkbox = event.target.closest("[data-step]");
  const slider = event.target.closest("[data-progress]");
  try {
    if (checkbox) await api(`/api/quests/${checkbox.dataset.quest}/steps/${checkbox.dataset.step}`, { method: "PATCH", body: JSON.stringify({ completed: checkbox.checked }) });
    else if (slider) await api(`/api/quests/${slider.dataset.progress}/progress`, { method: "PATCH", body: JSON.stringify({ progress: Number(slider.value) }) });
    else return;
    await loadApp();
  } catch (error) { notify(error.message, "error"); await loadApp(); }
});

$("#profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/profile", { method: "PATCH", body: JSON.stringify({ username: form.get("profile_name"), timezone: form.get("profile_timezone") }) });
    setFormMessage(event.currentTarget, "Profile saved.", "success");
    await loadApp();
  } catch (error) { setFormMessage(event.currentTarget, error.message); }
});

$("#settings-interest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const interests = $$("#settings-interest-options input:checked").map((input) => input.value);
  try {
    await api("/api/interests", { method: "PUT", body: JSON.stringify({ interests }) });
    setFormMessage(event.currentTarget, "Interests saved. New quests will reflect your choices.", "success");
    await loadApp();
  } catch (error) { setFormMessage(event.currentTarget, error.message); }
});

$("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = new FormData(event.currentTarget);
  try {
    await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: values.get("current_password"), new_password: values.get("new_password") }) });
    event.currentTarget.reset();
    notify("Password updated.");
  } catch (error) { setFormMessage(event.currentTarget, error.message); }
});

$("#delete-account").addEventListener("click", () => $("#delete-dialog").showModal());
$("#delete-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (new FormData(event.currentTarget).get("confirm_delete") !== "DELETE") {
    setFormMessage(event.currentTarget, "Type DELETE exactly to confirm.");
    return;
  }
  try {
    await api("/api/me", { method: "DELETE" });
    location.reload();
  } catch (error) { setFormMessage(event.currentTarget, error.message); }
});

loadApp();
