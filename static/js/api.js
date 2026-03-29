const API_BASE = "/api";

async function apiRequest(path, options = {}) {
  const opts = {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  };
  const res = await fetch(`${API_BASE}${path}`, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && window.location.pathname !== "/login" && window.location.pathname !== "/register") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
  if (!res.ok) {
    const message = data.error || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

function money(value) {
  const num = Number(value || 0);
  return `NGN ${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(value) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleDateString();
}

function formatDateTime(value) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString();
}

function statusClass(status) {
  if (status === "Active") return "active";
  if (status === "At Risk") return "at-risk";
  return "lost";
}

function escapeHtml(input) {
  const div = document.createElement("div");
  div.textContent = input == null ? "" : String(input);
  return div.innerHTML;
}

window.Retainr = {
  apiRequest,
  money,
  formatDate,
  formatDateTime,
  statusClass,
  escapeHtml,
};
