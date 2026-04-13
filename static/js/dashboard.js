const statsEls = {
  total: document.getElementById("stat-total"),
  active: document.getElementById("stat-active"),
  risk: document.getElementById("stat-risk"),
  lost: document.getElementById("stat-lost"),
  checkins: document.getElementById("stat-checkins"),
};

const gymHeading = document.getElementById("gym-heading");
const alertBox = document.getElementById("dashboard-alert");
const attentionBody = document.getElementById("attention-body");
const checkinsBody = document.getElementById("checkins-body");
const notificationList = document.getElementById("notification-list");
const navNotificationCount = document.getElementById("nav-notification-count");

const checkinQrImage = document.getElementById("checkin-qr-image");
const checkinUrlLink = document.getElementById("checkin-url-link");
const openCheckinLinkBtn = document.getElementById("open-checkin-link-btn");
const copyCheckinLinkBtn = document.getElementById("copy-checkin-link-btn");
const downloadCheckinQrBtn = document.getElementById("download-checkin-qr-btn");

const messageMemberSelect = document.getElementById("message-member-select");
const messageTemplateSelect = document.getElementById("message-template-select");
const quickMessageBox = document.getElementById("quick-message-box");
const composeTemplateBtn = document.getElementById("compose-template-btn");
const sendQuickMessageBtn = document.getElementById("send-quick-message-btn");
const markNotificationsReadBtn = document.getElementById("mark-notifications-read-btn");
const enableBrowserAlertsBtn = document.getElementById("enable-browser-alerts-btn");
const browserAlertStatus = document.getElementById("browser-alert-status");

const atRiskTemplateInput = document.getElementById("at-risk-template");
const lostTemplateInput = document.getElementById("lost-template");
const promoTemplateInput = document.getElementById("promo-template");
const saveTemplatesBtn = document.getElementById("save-templates-btn");

const gymNameInput = document.getElementById("gym-name-input");
const ownerNameInput = document.getElementById("owner-name-input");
const instagramUrlInput = document.getElementById("instagram-url-input");
const facebookUrlInput = document.getElementById("facebook-url-input");
const tiktokUrlInput = document.getElementById("tiktok-url-input");
const xUrlInput = document.getElementById("x-url-input");
const websiteUrlInput = document.getElementById("website-url-input");
const saveGymSettingsBtn = document.getElementById("save-gym-settings-btn");
const companyLogoInput = document.getElementById("company-logo-input");
const uploadCompanyLogoBtn = document.getElementById("upload-company-logo-btn");
const removeCompanyLogoBtn = document.getElementById("remove-company-logo-btn");
const companyLogoPreview = document.getElementById("company-logo-preview");

let dashboardData = null;
let members = [];
const membersById = new Map();
let pollTimer = null;
let currentBusinessId = null;
let hasBaselineEvents = false;
let notifiedEventKeys = new Set();
const DASHBOARD_POLL_INTERVAL_MS = 30000;

function showAlert(message, type = "error") {
  alertBox.className = `alert ${type}`;
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideAlert() {
  alertBox.style.display = "none";
}

function memberNameById(memberId) {
  const member = membersById.get(Number(memberId));
  return member?.name || "Unknown member";
}

function openWhatsapp(url) {
  const win = window.open(url, "_blank");
  if (!win) {
    showAlert("Popup blocked. Allow popups for this site to open WhatsApp.", "error");
    return false;
  }
  return true;
}

function browserNotificationsSupported() {
  return "Notification" in window;
}

function currentPermissionLabel() {
  if (!browserNotificationsSupported()) return "Not Supported";
  if (Notification.permission === "granted") return "Enabled";
  if (Notification.permission === "denied") return "Blocked";
  return "Not Enabled";
}

function updateBrowserAlertStatusLabel() {
  if (!browserAlertStatus) return;
  const label = currentPermissionLabel();
  browserAlertStatus.textContent = `Browser Alerts: ${label}`;
  if (!enableBrowserAlertsBtn) return;
  if (!browserNotificationsSupported() || Notification.permission === "granted") {
    enableBrowserAlertsBtn.style.display = "none";
  } else {
    enableBrowserAlertsBtn.style.display = "inline-flex";
    enableBrowserAlertsBtn.disabled = false;
    enableBrowserAlertsBtn.textContent = "Enable Browser Alerts";
  }
}

function notifiedStorageKey(businessId) {
  return `retainr_notified_events_${businessId}`;
}

function loadNotifiedKeys(businessId) {
  const out = new Set();
  if (!businessId) return out;
  try {
    const raw = localStorage.getItem(notifiedStorageKey(businessId));
    const arr = raw ? JSON.parse(raw) : [];
    if (Array.isArray(arr)) {
      arr.forEach((v) => {
        if (typeof v === "string" && v.trim()) {
          out.add(v);
        }
      });
    }
  } catch (_) {
    // ignore corrupted local storage
  }
  return out;
}

function saveNotifiedKeys(businessId) {
  if (!businessId) return;
  try {
    const items = Array.from(notifiedEventKeys);
    const trimmed = items.slice(-500);
    localStorage.setItem(notifiedStorageKey(businessId), JSON.stringify(trimmed));
  } catch (_) {
    // ignore storage errors
  }
}

function notificationEventKey(item) {
  if (item.id !== null && item.id !== undefined) {
    return `db:${item.id}`;
  }
  const kind = String(item.kind || "NOTICE").toUpperCase();
  const memberId = item.member_id ? Number(item.member_id) : 0;
  if (kind === "MESSAGE_NEEDED" && memberId > 0) {
    const status = String((item.data && item.data.status) || "").toUpperCase() || "UNKNOWN";
    return `attention:${memberId}:${status}`;
  }
  const createdAt = String(item.created_at || "");
  const message = String(item.message || "");
  return `adhoc:${kind}:${memberId}:${createdAt}:${message}`;
}

function notificationTitle(item, businessName) {
  const kind = String(item.kind || "").toUpperCase();
  if (kind === "CHECKIN") return `${businessName}: New Check-In`;
  if (kind === "DUPLICATE_CHECKIN") return `${businessName}: Duplicate Check-In Attempt`;
  if (kind === "MESSAGE_NEEDED") return `${businessName}: Member Needs Follow-Up`;
  return `${businessName}: New Alert`;
}

function showBrowserNotification(item, businessName) {
  if (!browserNotificationsSupported() || Notification.permission !== "granted") return;
  const title = notificationTitle(item, businessName || "Retainr");
  const body = String(item.message || "You have a new dashboard alert.");
  try {
    const notification = new Notification(title, {
      body,
      icon: "/static/images/logo.png",
      badge: "/static/images/logo.png",
      tag: notificationEventKey(item),
      renotify: false,
    });
    notification.onclick = () => {
      window.focus();
      window.location.hash = "notifications-section";
      notification.close();
    };
    window.setTimeout(() => notification.close(), 12000);
  } catch (_) {
    // Ignore browser notification failures
  }
}

function processIncomingBrowserAlerts(data, notifyNew) {
  const gym = data.gym || {};
  const businessId = Number(gym.id || 0);
  if (!businessId) return;

  if (currentBusinessId !== businessId) {
    currentBusinessId = businessId;
    hasBaselineEvents = false;
    notifiedEventKeys = loadNotifiedKeys(currentBusinessId);
  }

  const events = Array.isArray(data.notifications) ? data.notifications : [];
  if (!hasBaselineEvents) {
    events.forEach((item) => {
      notifiedEventKeys.add(notificationEventKey(item));
    });
    saveNotifiedKeys(currentBusinessId);
    hasBaselineEvents = true;
    return;
  }

  let changed = false;
  events.forEach((item) => {
    const key = notificationEventKey(item);
    if (notifiedEventKeys.has(key)) return;
    notifiedEventKeys.add(key);
    changed = true;
    if (notifyNew) {
      showBrowserNotification(item, String(gym.gym_name || "Business"));
    }
  });
  if (changed) {
    saveNotifiedKeys(currentBusinessId);
  }
}

async function composeMessage(memberId, templateType = "status") {
  const data = await Retainr.apiRequest("/messages/link", {
    method: "POST",
    body: JSON.stringify({
      member_id: Number(memberId),
      template_type: templateType,
    }),
  });
  return data.message || "";
}

async function sendMessage(memberId, templateType = "status", customMessage = "") {
  const payload = {
    member_id: Number(memberId),
    template_type: templateType,
  };
  if (customMessage) {
    payload.message = customMessage;
  }
  const data = await Retainr.apiRequest("/messages/link", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!data.whatsapp_url) {
    throw new Error("No WhatsApp URL returned for this member.");
  }
  openWhatsapp(data.whatsapp_url);
  return data.message || "";
}

function renderStats(stats) {
  statsEls.total.textContent = stats.total_members || 0;
  statsEls.active.textContent = stats.active_members || 0;
  statsEls.risk.textContent = stats.at_risk_members || 0;
  statsEls.lost.textContent = stats.lost_members || 0;
  statsEls.checkins.textContent = stats.today_checkins || 0;
}

function renderCheckin(gym) {
  const checkinLink = gym.checkin_link || "/my-checkin";
  const qrImageUrl = gym.checkin_qr_image_url || "";
  checkinQrImage.src = qrImageUrl;
  checkinUrlLink.href = checkinLink;
  checkinUrlLink.textContent = checkinLink;
  openCheckinLinkBtn.href = checkinLink;
  if (downloadCheckinQrBtn) {
    downloadCheckinQrBtn.href = `/api/checkin/qr/download?v=${Date.now()}`;
  }
}

function renderAttention(items) {
  if (!items.length) {
    attentionBody.innerHTML = `
      <tr>
        <td colspan="5"><span class="muted">No at-risk or lost members right now.</span></td>
      </tr>
    `;
    return;
  }

  attentionBody.innerHTML = items
    .map((member) => {
      const days = member.days_inactive == null ? "-" : `${member.days_inactive} days`;
      return `
        <tr>
          <td>${Retainr.escapeHtml(member.name)}</td>
          <td><span class="badge ${Retainr.statusClass(member.status)}">${Retainr.escapeHtml(member.status)}</span></td>
          <td>${days}</td>
          <td>${Retainr.money(member.monthly_fee)}</td>
          <td>
            <button data-action="send-member-message" data-member-id="${member.id}" type="button">Send Message</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderRecentCheckins(items) {
  if (!items.length) {
    checkinsBody.innerHTML = `
      <tr>
        <td colspan="4"><span class="muted">No check-ins yet.</span></td>
      </tr>
    `;
    return;
  }
  checkinsBody.innerHTML = items
    .map((item) => {
      return `
        <tr>
          <td>${Retainr.escapeHtml(item.name)}</td>
          <td>${Retainr.formatDateTime(item.checkin_at)}</td>
          <td>${Retainr.escapeHtml(item.source || "-")}</td>
          <td>${Retainr.escapeHtml(item.purpose || "-")}</td>
        </tr>
      `;
    })
    .join("");
}

function renderNotifications(items) {
  const unreadCount = items.filter((item) => item.id !== null && !item.is_read).length;
  if (navNotificationCount) {
    if (unreadCount > 0) {
      navNotificationCount.hidden = false;
      navNotificationCount.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
    } else {
      navNotificationCount.hidden = true;
      navNotificationCount.textContent = "0";
    }
  }

  if (!items.length) {
    notificationList.innerHTML = '<div class="empty">No notifications yet.</div>';
    return;
  }
  notificationList.innerHTML = items
    .map((item) => {
      const unreadClass = item.is_read ? "" : " unread";
      const memberId = item.member_id ? Number(item.member_id) : 0;
      const canMessage = memberId > 0;
      return `
        <article class="notification-item${unreadClass}">
          <div>
            <strong>${Retainr.escapeHtml(item.kind || "NOTICE")}</strong>
            <div>${Retainr.escapeHtml(item.message || "")}</div>
            <small class="muted">${Retainr.formatDateTime(item.created_at)}</small>
          </div>
          <div class="row">
            ${canMessage ? `<button data-action="send-member-message" data-member-id="${memberId}" type="button">Message ${Retainr.escapeHtml(memberNameById(memberId))}</button>` : ""}
          </div>
        </article>
      `;
    })
    .join("");
}

function renderMemberOptions() {
  const sorted = [...members].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  if (!sorted.length) {
    messageMemberSelect.innerHTML = '<option value="">No members yet</option>';
    return;
  }
  messageMemberSelect.innerHTML = sorted
    .map((member) => `<option value="${member.id}">${Retainr.escapeHtml(member.name)} (${Retainr.escapeHtml(member.status)})</option>`)
    .join("");
}

function fillSettings(gym) {
  gymHeading.textContent = `${gym.gym_name || "Business"} Dashboard`;
  const templates = gym.templates || {};
  atRiskTemplateInput.value = templates.at_risk || "";
  lostTemplateInput.value = templates.lost || "";
  promoTemplateInput.value = templates.promo || "";

  gymNameInput.value = gym.gym_name || "";
  ownerNameInput.value = gym.owner_name || "";
  const socials = gym.socials || {};
  instagramUrlInput.value = socials.instagram_url || "";
  facebookUrlInput.value = socials.facebook_url || "";
  tiktokUrlInput.value = socials.tiktok_url || "";
  xUrlInput.value = socials.x_url || "";
  websiteUrlInput.value = socials.website_url || "";

  const logoUrl = gym.company_logo_url || "";
  if (companyLogoPreview) {
    if (logoUrl) {
      companyLogoPreview.src = `${logoUrl}${logoUrl.includes("?") ? "&" : "?"}v=${Date.now()}`;
      companyLogoPreview.style.display = "block";
    } else {
      companyLogoPreview.removeAttribute("src");
      companyLogoPreview.style.display = "none";
    }
  }
  if (removeCompanyLogoBtn) {
    removeCompanyLogoBtn.style.display = logoUrl ? "inline-flex" : "none";
  }
}

function selectedMemberId() {
  return Number(messageMemberSelect.value || 0);
}

async function refreshMessagePreview() {
  const memberId = selectedMemberId();
  if (!memberId) {
    quickMessageBox.value = "";
    return;
  }
  const templateType = messageTemplateSelect.value || "status";
  if (templateType === "custom") {
    return;
  }
  try {
    quickMessageBox.value = await composeMessage(memberId, templateType);
  } catch (error) {
    showAlert(error.message);
  }
}

async function loadDashboard(options = {}) {
  const silent = Boolean(options.silent);
  const notifyBrowser = Boolean(options.notifyBrowser);
  if (!silent) {
    hideAlert();
  }
  dashboardData = await Retainr.apiRequest("/dashboard");
  processIncomingBrowserAlerts(dashboardData, notifyBrowser);
  const gym = dashboardData.gym || {};
  members = dashboardData.members || [];
  membersById.clear();
  members.forEach((m) => membersById.set(Number(m.id), m));

  renderStats(dashboardData.stats || {});
  renderCheckin(gym);
  renderAttention(dashboardData.attention_needed || []);
  renderRecentCheckins(dashboardData.recent_checkins || []);
  renderNotifications(dashboardData.notifications || []);
  renderMemberOptions();
  fillSettings(gym);
  await refreshMessagePreview();
}

async function uploadCompanyLogo(file) {
  const body = new FormData();
  body.append("logo", file);
  const res = await fetch("/api/gym/logo", { method: "POST", body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Upload failed (${res.status})`);
  }
  return data;
}

async function removeCompanyLogo() {
  const res = await fetch("/api/gym/logo", { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Delete failed (${res.status})`);
  }
  return data;
}

function startDashboardPolling() {
  if (pollTimer) return;
  pollTimer = window.setInterval(async () => {
    try {
      await loadDashboard({ silent: true, notifyBrowser: true });
    } catch (_) {
      // Keep polling; transient network issues should not stop alerts.
    }
  }, DASHBOARD_POLL_INTERVAL_MS);
}

async function requestBrowserAlertsPermission() {
  if (!browserNotificationsSupported()) {
    showAlert("This browser does not support desktop notifications.");
    updateBrowserAlertStatusLabel();
    return;
  }
  if (Notification.permission === "granted") {
    updateBrowserAlertStatusLabel();
    showAlert("Browser alerts are already enabled.", "success");
    return;
  }
  if (Notification.permission === "denied") {
    showAlert("Browser alerts are blocked. Allow notifications for this site in browser settings.");
    updateBrowserAlertStatusLabel();
    return;
  }

  if (enableBrowserAlertsBtn) {
    enableBrowserAlertsBtn.disabled = true;
    enableBrowserAlertsBtn.textContent = "Enabling...";
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      showAlert("Browser alerts enabled. You will now get check-in and inactivity alerts.", "success");
    } else if (permission === "denied") {
      showAlert("Browser alerts blocked. You can change this in browser site settings.");
    } else {
      showAlert("Browser alerts were not enabled.");
    }
  } catch (_) {
    showAlert("Could not request browser notification permission.");
  } finally {
    updateBrowserAlertStatusLabel();
  }
}

copyCheckinLinkBtn.addEventListener("click", async () => {
  const link = checkinUrlLink.href || "";
  if (!link) return;
  try {
    await navigator.clipboard.writeText(link);
    showAlert("Check-in link copied.", "success");
  } catch (_) {
    showAlert("Copy failed. Copy directly from the link shown.", "error");
  }
});

composeTemplateBtn.addEventListener("click", async () => {
  await refreshMessagePreview();
});

messageMemberSelect.addEventListener("change", () => {
  refreshMessagePreview();
});

messageTemplateSelect.addEventListener("change", () => {
  if (messageTemplateSelect.value === "custom" && !quickMessageBox.value.trim()) {
    quickMessageBox.placeholder = "Type custom message here...";
    return;
  }
  refreshMessagePreview();
});

sendQuickMessageBtn.addEventListener("click", async () => {
  hideAlert();
  const memberId = selectedMemberId();
  if (!memberId) {
    showAlert("Select a member first.");
    return;
  }
  const templateType = messageTemplateSelect.value || "status";
  const customMessage = quickMessageBox.value.trim();
  if (templateType === "custom" && !customMessage) {
    showAlert("Type your custom message first.");
    return;
  }
  try {
    const sentText = await sendMessage(memberId, templateType, customMessage);
    if (!customMessage && sentText) {
      quickMessageBox.value = sentText;
    }
    showAlert(`WhatsApp opened for ${memberNameById(memberId)}.`, "success");
  } catch (error) {
    showAlert(error.message);
  }
});

attentionBody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.dataset.action !== "send-member-message") return;
  const memberId = Number(target.dataset.memberId || 0);
  if (!memberId) return;
  try {
    await sendMessage(memberId, "status");
    messageMemberSelect.value = String(memberId);
    await refreshMessagePreview();
    showAlert(`WhatsApp opened for ${memberNameById(memberId)}.`, "success");
  } catch (error) {
    showAlert(error.message);
  }
});

notificationList.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.dataset.action !== "send-member-message") return;
  const memberId = Number(target.dataset.memberId || 0);
  if (!memberId) return;
  try {
    await sendMessage(memberId, "status");
    messageMemberSelect.value = String(memberId);
    await refreshMessagePreview();
    showAlert(`WhatsApp opened for ${memberNameById(memberId)}.`, "success");
  } catch (error) {
    showAlert(error.message);
  }
});

markNotificationsReadBtn.addEventListener("click", async () => {
  hideAlert();
  try {
    await Retainr.apiRequest("/notifications/mark-all-read", {
      method: "POST",
      body: "{}",
    });
    await loadDashboard();
    showAlert("Notifications marked as read.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

saveTemplatesBtn.addEventListener("click", async () => {
  hideAlert();
  try {
    await Retainr.apiRequest("/messages/templates", {
      method: "PUT",
      body: JSON.stringify({
        at_risk_message: atRiskTemplateInput.value.trim(),
        lost_message: lostTemplateInput.value.trim(),
        promo_message: promoTemplateInput.value.trim(),
      }),
    });
    await loadDashboard();
    showAlert("Message templates updated.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

saveGymSettingsBtn.addEventListener("click", async () => {
  hideAlert();
  try {
    await Retainr.apiRequest("/gym/settings", {
      method: "PUT",
      body: JSON.stringify({
        gym_name: gymNameInput.value.trim(),
        owner_name: ownerNameInput.value.trim(),
        instagram_url: instagramUrlInput.value.trim(),
        facebook_url: facebookUrlInput.value.trim(),
        tiktok_url: tiktokUrlInput.value.trim(),
        x_url: xUrlInput.value.trim(),
        website_url: websiteUrlInput.value.trim(),
      }),
    });
    await loadDashboard();
    showAlert("Business settings saved.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

if (enableBrowserAlertsBtn) {
  enableBrowserAlertsBtn.addEventListener("click", async () => {
    await requestBrowserAlertsPermission();
  });
}

if (uploadCompanyLogoBtn) {
  uploadCompanyLogoBtn.addEventListener("click", async () => {
    hideAlert();
    const file = companyLogoInput?.files?.[0];
    if (!file) {
      showAlert("Choose a logo image first.");
      return;
    }
    uploadCompanyLogoBtn.disabled = true;
    try {
      await uploadCompanyLogo(file);
      if (companyLogoInput) {
        companyLogoInput.value = "";
      }
      await loadDashboard();
      showAlert("Company logo uploaded. QR sticker layout switched to logo template.", "success");
    } catch (error) {
      showAlert(error.message);
    } finally {
      uploadCompanyLogoBtn.disabled = false;
    }
  });
}

if (removeCompanyLogoBtn) {
  removeCompanyLogoBtn.addEventListener("click", async () => {
    hideAlert();
    removeCompanyLogoBtn.disabled = true;
    try {
      await removeCompanyLogo();
      if (companyLogoInput) {
        companyLogoInput.value = "";
      }
      await loadDashboard();
      showAlert("Company logo removed. QR sticker layout switched to no-logo template.", "success");
    } catch (error) {
      showAlert(error.message);
    } finally {
      removeCompanyLogoBtn.disabled = false;
    }
  });
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  loadDashboard({ silent: true, notifyBrowser: true }).catch(() => {});
});

updateBrowserAlertStatusLabel();
loadDashboard()
  .then(() => {
    startDashboardPolling();
  })
  .catch((error) => {
    showAlert(error.message);
  });
