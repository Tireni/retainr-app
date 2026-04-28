const alertBox = document.getElementById("admin-alert");
const rangeButtons = Array.from(document.querySelectorAll("[data-range]"));
const companiesBody = document.getElementById("companies-tbody");
const companyDetailCard = document.getElementById("company-detail-card");
const companyDetailTitle = document.getElementById("company-detail-title");
const companyDetailSub = document.getElementById("company-detail-sub");
const companyDetailSummary = document.getElementById("company-detail-summary");
const companyMembersBody = document.getElementById("company-members-tbody");
const logoutLink = document.getElementById("admin-logout-link");

const kpiBusinessesTotal = document.getElementById("kpi-businesses-total");
const kpiBusinessesSub = document.getElementById("kpi-businesses-sub");
const kpiMembersTotal = document.getElementById("kpi-members-total");
const kpiMembersSub = document.getElementById("kpi-members-sub");
const kpiRecovered = document.getElementById("kpi-recovered");
const kpiVisits = document.getElementById("kpi-visits");
const kpiVisitsSub = document.getElementById("kpi-visits-sub");

const charts = {};
let currentRange = "week";

function showError(message) {
  alertBox.className = "alert error";
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideError() {
  alertBox.style.display = "none";
}

function num(value) {
  return Number(value || 0).toLocaleString();
}

function escapeHtml(input) {
  const div = document.createElement("div");
  div.textContent = input == null ? "" : String(input);
  return div.innerHTML;
}

async function apiRequest(path, options = {}) {
  const opts = {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) {
      window.location.href = "/admin-login";
    }
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function setActiveRangeButton() {
  rangeButtons.forEach((btn) => {
    const isActive = String(btn.dataset.range || "") === currentRange;
    btn.classList.toggle("active", isActive);
  });
}

function upsertChart(id, config) {
  const canvas = document.getElementById(id);
  if (!canvas || typeof Chart === "undefined") return;
  if (charts[id]) {
    charts[id].data = config.data;
    charts[id].options = config.options || charts[id].options;
    charts[id].update();
    return;
  }
  charts[id] = new Chart(canvas, config);
}

function renderKpis(data) {
  const k = data.kpis || {};
  kpiBusinessesTotal.textContent = num(k.businesses_total);
  kpiBusinessesSub.textContent = `Week: ${num(k.businesses_week)} • Month: ${num(k.businesses_month)} • Year: ${num(k.businesses_year)}`;
  kpiMembersTotal.textContent = num(k.members_total);
  kpiMembersSub.textContent = `Active: ${num(k.members_active)} • At Risk: ${num(k.members_at_risk)} • Lost: ${num(k.members_lost)}`;
  kpiRecovered.textContent = num(k.members_recovered);
  kpiVisits.textContent = num(k.visits_total);
  kpiVisitsSub.textContent = `Unique: ${num(k.visits_unique_total)} • In Range: ${num(k.visits_period)}`;
}

function chartDefaults() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: "bottom" },
    },
  };
}

function renderCharts(data) {
  const c = data.charts || {};

  const dailySignups = Array.isArray(c.daily_signups) ? c.daily_signups : [];
  upsertChart("chart-signups-daily", {
    type: "line",
    data: {
      labels: dailySignups.map((r) => String(r.day || "")),
      datasets: [{
        label: "Signups",
        data: dailySignups.map((r) => Number(r.count || 0)),
        borderColor: "#2563eb",
        backgroundColor: "rgba(37,99,235,.14)",
        fill: true,
        tension: 0.35,
      }],
    },
    options: chartDefaults(),
  });

  const monthlySignups = Array.isArray(c.monthly_signups) ? c.monthly_signups : [];
  upsertChart("chart-signups-monthly", {
    type: "bar",
    data: {
      labels: monthlySignups.map((r) => String(r.month || "")),
      datasets: [{
        label: "Businesses",
        data: monthlySignups.map((r) => Number(r.count || 0)),
        backgroundColor: "#0f172a",
      }],
    },
    options: chartDefaults(),
  });

  const statusSplit = c.member_status_split || { labels: [], values: [] };
  upsertChart("chart-member-split", {
    type: "pie",
    data: {
      labels: statusSplit.labels || [],
      datasets: [{
        data: (statusSplit.values || []).map((v) => Number(v || 0)),
        backgroundColor: ["#16a34a", "#f59e0b", "#dc2626"],
      }],
    },
    options: chartDefaults(),
  });

  const visitsDaily = Array.isArray(c.visits_daily) ? c.visits_daily : [];
  upsertChart("chart-visits-daily", {
    type: "line",
    data: {
      labels: visitsDaily.map((r) => String(r.day || "")),
      datasets: [
        {
          label: "Visits",
          data: visitsDaily.map((r) => Number(r.visits || 0)),
          borderColor: "#1d4ed8",
          backgroundColor: "rgba(29,78,216,.10)",
          fill: true,
          tension: 0.35,
        },
        {
          label: "Unique",
          data: visitsDaily.map((r) => Number(r.unique || 0)),
          borderColor: "#0f172a",
          backgroundColor: "rgba(15,23,42,.08)",
          fill: false,
          tension: 0.3,
        },
      ],
    },
    options: chartDefaults(),
  });

  const opsRadar = c.ops_radar || { labels: [], values: [] };
  upsertChart("chart-ops-radar", {
    type: "radar",
    data: {
      labels: opsRadar.labels || [],
      datasets: [{
        label: "Platform",
        data: (opsRadar.values || []).map((v) => Number(v || 0)),
        borderColor: "#2563eb",
        backgroundColor: "rgba(37,99,235,.16)",
      }],
    },
    options: {
      ...chartDefaults(),
      scales: { r: { beginAtZero: true } },
    },
  });
}

function renderCompanies(data) {
  const rows = Array.isArray(data.companies) ? data.companies : [];
  if (!rows.length) {
    companiesBody.innerHTML = `<tr><td colspan="8" class="muted">No businesses found.</td></tr>`;
    return;
  }
  companiesBody.innerHTML = rows.map((row) => `
    <tr>
      <td>
        <strong>${escapeHtml(row.gym_name || "-")}</strong><br>
        <span class="muted">${escapeHtml(row.email || "")}</span>
      </td>
      <td>${escapeHtml(row.created_at || "-")}</td>
      <td>${num(row.members_total)}</td>
      <td>${num(row.members_recovered)}</td>
      <td>${num(row.members_lost)}</td>
      <td>${num(row.new_members_period)}</td>
      <td>${num(row.checkins_period)}</td>
      <td><button class="btn btn-outline" data-company-id="${Number(row.id)}">View</button></td>
    </tr>
  `).join("");
}

function statusBadgeClass(status) {
  if (status === "Active") return "badge active";
  if (status === "At Risk") return "badge at-risk";
  return "badge lost";
}

async function loadCompanyDetails(gymId) {
  hideError();
  try {
    const data = await apiRequest(`/api/admin/company/${gymId}`);
    const gym = data.gym || {};
    const summary = data.summary || {};
    const members = Array.isArray(data.members) ? data.members : [];
    companyDetailCard.style.display = "block";
    companyDetailTitle.textContent = `${gym.gym_name || "Business"} • Company Breakdown`;
    companyDetailSub.textContent = `${gym.email || ""} • Signed up ${gym.created_at || "-"}`;
    companyDetailSummary.innerHTML = `
      <div class="badge active">Active: ${num(summary.members_active)}</div>
      <div class="badge at-risk">At Risk: ${num(summary.members_at_risk)}</div>
      <div class="badge lost">Lost: ${num(summary.members_lost)}</div>
      <div class="badge neutral">Recovered: ${num(summary.members_recovered)}</div>
      <div class="badge neutral">Check-ins: ${num(summary.checkins_total)}</div>
    `;
    if (!members.length) {
      companyMembersBody.innerHTML = `<tr><td colspan="6" class="muted">No members yet.</td></tr>`;
    } else {
      companyMembersBody.innerHTML = members.map((m) => `
        <tr>
          <td>${escapeHtml(m.name || "-")}</td>
          <td>${escapeHtml(m.phone || "-")}</td>
          <td><span class="${statusBadgeClass(m.status)}">${escapeHtml(m.status || "-")}</span></td>
          <td>${m.is_recovered ? "Yes" : "No"}</td>
          <td>${escapeHtml(m.last_visit || "-")}</td>
          <td>${escapeHtml(m.expiry_date || "-")}</td>
        </tr>
      `).join("");
    }
    companyDetailCard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showError(error.message);
  }
}

async function loadOverview() {
  hideError();
  setActiveRangeButton();
  try {
    const data = await apiRequest(`/api/admin/overview?range=${encodeURIComponent(currentRange)}`);
    renderKpis(data);
    renderCharts(data);
    renderCompanies(data);
  } catch (error) {
    showError(error.message);
  }
}

function wireEvents() {
  rangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      currentRange = String(btn.dataset.range || "week");
      loadOverview();
    });
  });
  companiesBody.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const btn = target.closest("[data-company-id]");
    if (!btn) return;
    const gymId = Number(btn.getAttribute("data-company-id") || "0");
    if (!gymId) return;
    loadCompanyDetails(gymId);
  });
  if (logoutLink) {
    logoutLink.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        await apiRequest("/api/admin/auth/logout", { method: "POST" });
      } finally {
        window.location.href = "/admin-login";
      }
    });
  }
}

wireEvents();
loadOverview();
