const API = "/v1";
const $ = (id) => document.getElementById(id);
const sessionKey = "zerocode-admin-session";

const state = {
  accessToken: null,
  refreshToken: null,
  user: null,
  view: "overview",
  users: [],
  providers: [],
  models: [],
  clientConfig: null,
  toastTimer: null,
};

const pageInfo = {
  overview: ["Vue générale", "La santé du service en un coup d’œil."],
  accounts: ["Comptes & appareils", "Gère les comptes et les sessions actives."],
  usage: ["Activité IA", "Observe les requêtes et les erreurs du service."],
  protections: ["Protections", "Les limites sont appliquées côté serveur."],
  providers: ["Fournisseurs", "Maîtrise les routes amont disponibles."],
  models: ["Modèles", "Contrôle les modèles accessibles aux clients."],
  system: ["État du service", "Disponibilité, maintenance et fonctions distantes."],
  audit: ["Journal d’audit", "Historique des actions d’administration."],
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function formatNumber(value) {
  return new Intl.NumberFormat("fr-FR").format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function saveSession() {
  sessionStorage.setItem(sessionKey, JSON.stringify({
    accessToken: state.accessToken,
    refreshToken: state.refreshToken,
  }));
}

function clearSession() {
  state.accessToken = null;
  state.refreshToken = null;
  state.user = null;
  sessionStorage.removeItem(sessionKey);
  $("app-shell").hidden = true;
  $("login-view").hidden = false;
}

function readSession() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(sessionKey) || "null");
    if (!saved || typeof saved.accessToken !== "string" || typeof saved.refreshToken !== "string") {
      return false;
    }
    state.accessToken = saved.accessToken;
    state.refreshToken = saved.refreshToken;
    return true;
  } catch {
    sessionStorage.removeItem(sessionKey);
    return false;
  }
}

async function rotateSession() {
  if (!state.refreshToken) return false;
  const response = await fetch(`${API}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.refreshToken }),
    cache: "no-store",
  });
  if (!response.ok) {
    clearSession();
    return false;
  }
  const data = await response.json();
  state.accessToken = data.access_token;
  state.refreshToken = data.refresh_token;
  saveSession();
  return true;
}

async function api(path, options = {}, canRefresh = true) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (state.accessToken) headers.set("Authorization", `Bearer ${state.accessToken}`);
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (
    response.status === 401 &&
    canRefresh &&
    state.refreshToken &&
    path !== "/auth/refresh" &&
    path !== "/auth/login"
  ) {
    const renewed = await rotateSession();
    if (renewed) return api(path, options, false);
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Erreur HTTP ${response.status}`;
    throw new Error(message);
  }
  return data;
}

function showToast(message, isError = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.style.background = isError ? "#a52b3d" : "#1b293b";
  toast.classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 3200);
}

function showNotice(kind, message) {
  const target = kind === "error" ? $("global-error") : $("global-success");
  const other = kind === "error" ? $("global-success") : $("global-error");
  other.hidden = true;
  target.textContent = message;
  target.hidden = false;
  setTimeout(() => { target.hidden = true; }, 5000);
}

function setSwitch(button, enabled) {
  if (!button) return;
  button.setAttribute("aria-pressed", String(Boolean(enabled)));
}

function setMaintenanceUI(enabled) {
  const badge = $("maintenance-badge");
  badge.className = `badge ${enabled ? "badge-amber" : "badge-green"}`;
  badge.textContent = enabled ? "Maintenance" : "En service";
  $("maintenance-title").textContent = enabled ? "Mode maintenance activé" : "Service ouvert";
  $("maintenance-description").textContent = enabled
    ? "Les nouvelles requêtes IA sont bloquées."
    : "Le service accepte les nouvelles requêtes.";
  $("system-maintenance-title").textContent = enabled ? "Activé" : "Désactivé";
  $("system-maintenance-description").textContent = enabled
    ? "Les nouvelles requêtes IA sont bloquées."
    : "Le service accepte les nouvelles requêtes.";
  $("system-maintenance-badge").className = `badge ${enabled ? "badge-amber" : "badge-green"}`;
  $("system-maintenance-badge").textContent = enabled ? "Maintenance" : "En service";
  setSwitch($("maintenance-toggle"), enabled);
  setSwitch($("system-maintenance-toggle"), enabled);
}

function renderUsageTable(rows) {
  if (!rows.length) return '<div class="empty-state">Aucune activité enregistrée pour le moment.</div>';
  return `<table><thead><tr><th>Utilisateur</th><th>Modèle</th><th>Tâche</th><th>Jetons</th><th>Latence</th><th>Résultat</th><th>Date</th></tr></thead><tbody>${rows.map((row) => `
    <tr>
      <td><div class="table-primary">${escapeHtml(row.user_email)}</div><div class="table-secondary">${escapeHtml(row.provider_name)}</div></td>
      <td>${escapeHtml(row.model_alias || row.requested_model)}</td>
      <td>${escapeHtml(row.task_type)}</td>
      <td>${formatNumber(row.total_tokens)}</td>
      <td>${formatNumber(row.latency_ms)} ms</td>
      <td>${row.success ? '<span class="badge badge-green">Réussi</span>' : '<span class="badge badge-red">Échec</span>'}</td>
      <td>${formatDate(row.created_at)}</td>
    </tr>`).join("")}</tbody></table>`;
}

function renderAccounts(rows) {
  if (!rows.length) return '<div class="empty-state">Aucun compte trouvé.</div>';
  return `<table><thead><tr><th>Compte</th><th>Rôle</th><th>État</th><th>Appareils</th><th>Créé le</th><th>Actions</th></tr></thead><tbody>${rows.map((user) => {
    const self = state.user && user.id === state.user.id;
    const status = user.is_active
      ? '<span class="badge badge-green">Actif</span>'
      : '<span class="badge badge-red">Suspendu</span>';
    const actionLabel = user.is_active ? "Suspendre" : "Réactiver";
    return `<tr>
      <td><div class="table-primary">${escapeHtml(user.email)}</div><div class="table-secondary">${escapeHtml(user.id)}</div></td>
      <td>${user.role === "admin" ? '<span class="badge badge-blue">Admin</span>' : "Utilisateur"}</td>
      <td>${status}</td>
      <td>${formatNumber(user.devices_active)} actifs <span class="table-secondary">/ ${formatNumber(user.devices_total)}</span></td>
      <td>${formatDate(user.created_at)}</td>
      <td><div class="table-actions">
        <button class="small-button" data-action="devices" data-user-id="${escapeHtml(user.id)}" data-email="${escapeHtml(user.email)}">Appareils</button>
        <button class="small-button ${user.is_active ? "danger" : ""}" data-action="user-status" data-user-id="${escapeHtml(user.id)}" data-enabled="${String(!user.is_active)}" ${self ? "disabled" : ""}>${self ? "Vous" : actionLabel}</button>
      </div></td>
    </tr>`;
  }).join("")}</tbody></table>`;
}

function renderProviders(rows) {
  if (!rows.length) return '<div class="empty-state">Aucun fournisseur configuré.</div>';
  return rows.map((provider) => `
    <article class="resource-card">
      <div class="resource-top">
        <h3>${escapeHtml(provider.name)}</h3>
        <button class="switch" type="button" data-action="provider-toggle" data-id="${escapeHtml(provider.id)}" aria-pressed="${String(provider.is_enabled)}" aria-label="Activer ou désactiver ${escapeHtml(provider.name)}"><span></span></button>
      </div>
      <div class="resource-url" title="${escapeHtml(provider.base_url)}">${escapeHtml(provider.base_url)}</div>
      <div class="resource-meta">
        <span>${provider.has_api_key ? "Clé serveur configurée" : "Aucune clé configurée"}</span>
        <span class="badge ${provider.is_enabled ? "badge-green" : "badge-red"}">${provider.is_enabled ? "Activé" : "Désactivé"}</span>
      </div>
    </article>`).join("");
}

function renderModels(rows) {
  if (!rows.length) return '<div class="empty-state">Aucun modèle configuré.</div>';
  return `<table><thead><tr><th>Alias</th><th>Fournisseur</th><th>Modèle amont</th><th>Priorité</th><th>Fonctions</th><th>État</th><th>Action</th></tr></thead><tbody>${rows.map((model) => `
    <tr>
      <td><span class="table-primary">${escapeHtml(model.alias)}</span></td>
      <td>${escapeHtml(model.provider_name)}</td>
      <td>${escapeHtml(model.model_name)}</td>
      <td>${formatNumber(model.priority)}</td>
      <td>${[model.supports_tools ? "Outils" : null, model.supports_vision ? "Vision" : null].filter(Boolean).join(" · ") || "Standard"}</td>
      <td>${model.is_enabled ? '<span class="badge badge-green">Actif</span>' : '<span class="badge badge-red">Inactif</span>'}</td>
      <td><button class="small-button ${model.is_enabled ? "danger" : ""}" data-action="model-toggle" data-id="${escapeHtml(model.id)}" data-enabled="${String(!model.is_enabled)}">${model.is_enabled ? "Désactiver" : "Activer"}</button></td>
    </tr>`).join("")}</tbody></table>`;
}

function renderAudit(rows) {
  if (!rows.length) return '<div class="empty-state">Aucune action d’administration enregistrée.</div>';
  return `<table><thead><tr><th>Action</th><th>Cible</th><th>Administrateur</th><th>Détails</th><th>Date</th></tr></thead><tbody>${rows.map((row) => `
    <tr>
      <td><span class="table-primary">${escapeHtml(row.action)}</span></td>
      <td>${escapeHtml(row.target_type)} <span class="table-secondary">${escapeHtml(row.target_id || "")}</span></td>
      <td>${escapeHtml(row.actor_user_id || "Système")}</td>
      <td>${escapeHtml(JSON.stringify(row.details || {}))}</td>
      <td>${formatDate(row.created_at)}</td>
    </tr>`).join("")}</tbody></table>`;
}

function fillGuardrails(limits) {
  const form = $("guardrails-form");
  for (const [key, value] of Object.entries(limits)) {
    const input = form.elements.namedItem(key);
    if (input) input.value = value;
  }
}

function renderGuardrailSummary(limits) {
  const items = [
    ["Requêtes / compte / min", limits.requests_per_minute],
    ["Simultanées / compte", limits.max_concurrent_requests],
    ["Requêtes globales / min", limits.global_requests_per_minute],
    ["Simultanées globales", limits.max_global_concurrent_requests],
    ["Sortie maximale", `${formatNumber(limits.max_output_tokens)} jetons`],
    ["Appareils / compte", limits.max_active_devices],
  ];
  $("guardrail-summary").innerHTML = items.map(([label, value]) =>
    `<div class="guardrail-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`,
  ).join("");
}

async function loadOverview() {
  const [overview, guardrails, clientConfig, recent] = await Promise.all([
    api("/admin/overview"),
    api("/admin/guardrails"),
    api("/admin/client-config"),
    api("/admin/usage/recent?limit=8"),
  ]);
  $("metric-users").textContent = formatNumber(overview.users_active);
  $("metric-users-total").textContent = formatNumber(overview.users_total);
  $("metric-requests").textContent = formatNumber(overview.requests_24h);
  $("metric-errors").textContent = formatNumber(overview.failed_requests_24h);
  $("metric-inflight").textContent = formatNumber(overview.active_requests);
  $("overview-updated").textContent = `Mis à jour à ${new Intl.DateTimeFormat("fr-FR", { timeStyle: "short" }).format(new Date())}`;
  renderGuardrailSummary(guardrails.limits);
  state.clientConfig = clientConfig;
  setMaintenanceUI(clientConfig.maintenance_mode);
  $("overview-recent").innerHTML = renderUsageTable(recent);
}

async function loadAccounts(query = "") {
  const params = new URLSearchParams({ limit: "100" });
  if (query.trim()) params.set("query", query.trim());
  const rows = await api(`/admin/users?${params.toString()}`);
  state.users = rows;
  $("accounts-count").textContent = `${formatNumber(rows.length)} compte(s) affiché(s)`;
  $("accounts-table").innerHTML = renderAccounts(rows);
}

async function loadUsage() {
  const rows = await api("/admin/usage/recent?limit=150");
  $("usage-table").innerHTML = renderUsageTable(rows);
}

async function loadProtections() {
  const data = await api("/admin/guardrails");
  fillGuardrails(data.limits);
}

async function loadProviders() {
  const rows = await api("/admin/providers");
  state.providers = rows;
  $("providers-grid").innerHTML = renderProviders(rows);
}

async function loadModels() {
  const rows = await api("/admin/models");
  state.models = rows;
  $("models-table").innerHTML = renderModels(rows);
}

async function loadSystem() {
  const [health, config] = await Promise.all([
    fetch("/v1/health/ready", { cache: "no-store" }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "L’API n’est pas prête.");
      return body;
    }),
    api("/admin/client-config"),
  ]);
  $("api-health-badge").className = "badge badge-green";
  $("api-health-badge").textContent = "Opérationnelle";
  $("api-health-text").textContent = "API et base de données disponibles";
  $("api-health-detail").textContent = `État : ${health.status} · Base : ${health.database}`;
  state.clientConfig = config;
  setMaintenanceUI(config.maintenance_mode);
  setSwitch($("flag-cloud-ai"), config.feature_flags?.cloud_ai !== false);
  setSwitch($("flag-remote-config"), config.feature_flags?.remote_config !== false);
}

async function loadAudit() {
  const rows = await api("/admin/audit-logs?limit=150");
  $("audit-table").innerHTML = renderAudit(rows);
}

async function loadView(view, showErrors = true) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== view;
  });
  const [title, subtitle] = pageInfo[view] || pageInfo.overview;
  $("page-title").textContent = title;
  $("page-subtitle").textContent = subtitle;
  $("global-error").hidden = true;
  try {
    const loaders = {
      overview: loadOverview,
      accounts: () => loadAccounts($("user-search").value),
      usage: loadUsage,
      protections: loadProtections,
      providers: loadProviders,
      models: loadModels,
      system: loadSystem,
      audit: loadAudit,
    };
    await (loaders[view] || loadOverview)();
  } catch (error) {
    if (showErrors) showNotice("error", error.message || "Impossible de charger cette section.");
  }
}

async function refreshCurrentView() {
  await loadView(state.view);
  showToast("Données actualisées.");
}

async function setMaintenance(enabled) {
  if (enabled && !window.confirm("Activer la maintenance ? Toutes les nouvelles requêtes IA seront bloquées.")) {
    setMaintenanceUI(false);
    return;
  }
  const config = await api("/admin/client-config", {
    method: "PATCH",
    body: JSON.stringify({ maintenance_mode: enabled }),
  });
  state.clientConfig = { ...state.clientConfig, ...config };
  setMaintenanceUI(Boolean(config.maintenance_mode));
  showToast(enabled ? "Mode maintenance activé." : "Service remis en ligne.");
}

async function setFeatureFlag(flag, enabled) {
  const flags = { ...(state.clientConfig?.feature_flags || {}) };
  flags[flag] = enabled;
  const config = await api("/admin/client-config", {
    method: "PATCH",
    body: JSON.stringify({ feature_flags: flags }),
  });
  state.clientConfig = { ...state.clientConfig, ...config };
  setSwitch($(`flag-${flag.replaceAll("_", "-")}`), enabled);
  showToast("Configuration distante mise à jour.");
}

async function openDevices(userId, email) {
  const rows = await api(`/admin/users/${encodeURIComponent(userId)}/devices`);
  $("devices-user-email").textContent = email;
  $("devices-list").innerHTML = rows.length ? rows.map((device) => `
    <div class="device-row">
      <div>
        <strong>${escapeHtml(device.name)}</strong>
        <p>Dernière activité : ${escapeHtml(formatDate(device.last_seen_at))} · Créé : ${escapeHtml(formatDate(device.created_at))}</p>
        <p>${escapeHtml(device.id)}</p>
      </div>
      <div class="table-actions">
        <span class="badge ${device.is_revoked ? "badge-red" : "badge-green"}">${device.is_revoked ? "Révoqué" : "Actif"}</span>
        ${device.is_revoked ? "" : `<button class="small-button danger" data-action="revoke-device" data-user-id="${escapeHtml(userId)}" data-device-id="${escapeHtml(device.id)}">Révoquer</button>`}
      </div>
    </div>`).join("") : '<div class="empty-state">Aucun appareil enregistré.</div>';
  $("devices-dialog").showModal();
}

async function handleAction(button) {
  const action = button.dataset.action;
  button.disabled = true;
  try {
    if (action === "devices") {
      await openDevices(button.dataset.userId, button.dataset.email);
    } else if (action === "user-status") {
      const enabled = button.dataset.enabled === "true";
      const label = enabled ? "réactiver" : "suspendre";
      if (!window.confirm(`Confirmer : ${label} ce compte ?`)) return;
      await api(`/admin/users/${encodeURIComponent(button.dataset.userId)}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: enabled }),
      });
      await loadAccounts($("user-search").value);
      showToast(enabled ? "Compte réactivé. Une nouvelle connexion est nécessaire." : "Compte suspendu et sessions révoquées.");
    } else if (action === "revoke-device") {
      if (!window.confirm("Révoquer cet appareil ? Sa session sera immédiatement invalidée.")) return;
      await api(`/admin/users/${encodeURIComponent(button.dataset.userId)}/devices/${encodeURIComponent(button.dataset.deviceId)}/revoke`, { method: "POST" });
      await openDevices(button.dataset.userId, $("devices-user-email").textContent);
      await loadAccounts($("user-search").value);
      showToast("Appareil révoqué.");
    } else if (action === "provider-toggle") {
      const provider = state.providers.find((item) => item.id === button.dataset.id);
      if (!provider) return;
      const enabled = !provider.is_enabled;
      if (!enabled && !window.confirm(`Désactiver le fournisseur ${provider.name} ?`)) return;
      await api(`/admin/providers/${encodeURIComponent(provider.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ is_enabled: enabled }),
      });
      await loadProviders();
      showToast(enabled ? "Fournisseur activé." : "Fournisseur désactivé.");
    } else if (action === "model-toggle") {
      const enabled = button.dataset.enabled === "true";
      const modelId = button.dataset.id;
      if (!enabled && !window.confirm("Désactiver ce modèle pour tous les clients ?")) return;
      await api(`/admin/models/${encodeURIComponent(modelId)}`, {
        method: "PATCH",
        body: JSON.stringify({ is_enabled: enabled }),
      });
      await loadModels();
      showToast(enabled ? "Modèle activé." : "Modèle désactivé.");
    }
  } catch (error) {
    showToast(error.message || "Action impossible.", true);
  } finally {
    button.disabled = false;
  }
}

function showShell() {
  $("login-view").hidden = true;
  $("app-shell").hidden = false;
  $("admin-email").textContent = state.user?.email || "Administrateur";
  $("avatar").textContent = (state.user?.email || "A").slice(0, 1).toUpperCase();
}

async function login(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const error = $("login-error");
  const submit = event.currentTarget.querySelector('button[type="submit"]');
  error.textContent = "";
  submit.disabled = true;
  submit.textContent = "Connexion…";
  try {
    const response = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
        device_name: "ZeroCode Admin Control Center",
      }),
      cache: "no-store",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Identifiants incorrects.");
    if (data.user?.role !== "admin") {
      throw new Error("Ce compte ne possède pas les droits administrateur.");
    }
    state.accessToken = data.access_token;
    state.refreshToken = data.refresh_token;
    state.user = data.user;
    saveSession();
    showShell();
    await loadView("overview");
  } catch (error) {
    error.textContent = error.message || "Connexion impossible.";
  } finally {
    submit.disabled = false;
    submit.innerHTML = 'Se connecter <span aria-hidden="true">→</span>';
  }
}

async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch {
    // Local credentials are discarded even if the network is unavailable.
  }
  clearSession();
}

async function boot() {
  if (!readSession()) return;
  try {
    state.user = await api("/auth/me");
    if (state.user.role !== "admin") throw new Error("Accès administrateur requis.");
    showShell();
    await loadView("overview", false);
  } catch {
    clearSession();
  }
}

document.addEventListener("click", async (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) {
    await loadView(nav.dataset.view);
    return;
  }
  const go = event.target.closest("[data-go]");
  if (go) {
    await loadView(go.dataset.go);
    return;
  }
  const action = event.target.closest("[data-action]");
  if (action) {
    await handleAction(action);
  }
});

$("login-form").addEventListener("submit", login);
$("logout-button").addEventListener("click", logout);
$("refresh-button").addEventListener("click", refreshCurrentView);
$("accounts-reload").addEventListener("click", () => loadAccounts($("user-search").value));
$("usage-reload").addEventListener("click", loadUsage);
$("providers-reload").addEventListener("click", loadProviders);
$("models-reload").addEventListener("click", loadModels);
$("system-reload").addEventListener("click", loadSystem);
$("audit-reload").addEventListener("click", loadAudit);
$("close-devices").addEventListener("click", () => $("devices-dialog").close());
$("maintenance-toggle").addEventListener("click", async () => {
  try { await setMaintenance(!state.clientConfig?.maintenance_mode); }
  catch (error) { showToast(error.message, true); }
});
$("system-maintenance-toggle").addEventListener("click", async () => {
  try { await setMaintenance(!state.clientConfig?.maintenance_mode); }
  catch (error) { showToast(error.message, true); }
});
$("flag-cloud-ai").addEventListener("click", async () => {
  const enabled = $("flag-cloud-ai").getAttribute("aria-pressed") !== "true";
  try { await setFeatureFlag("cloud_ai", enabled); }
  catch (error) { showToast(error.message, true); }
});
$("flag-remote-config").addEventListener("click", async () => {
  const enabled = $("flag-remote-config").getAttribute("aria-pressed") !== "true";
  try { await setFeatureFlag("remote_config", enabled); }
  catch (error) { showToast(error.message, true); }
});
$("guardrails-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {};
  for (const [key, value] of form.entries()) payload[key] = Number(value);
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api("/admin/guardrails", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    fillGuardrails(result.limits);
    renderGuardrailSummary(result.limits);
    showNotice("success", "Les protections ont été enregistrées et sont maintenant appliquées côté serveur.");
    showToast("Protections mises à jour.");
  } catch (error) {
    showToast(error.message || "Enregistrement impossible.", true);
  } finally {
    button.disabled = false;
  }
});

let searchTimer = null;
$("user-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadAccounts($("user-search").value).catch((error) => showToast(error.message, true)), 280);
});

$("devices-dialog").addEventListener("click", (event) => {
  if (event.target === $("devices-dialog")) $("devices-dialog").close();
});

boot();
