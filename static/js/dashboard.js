const gymHeading = document.getElementById("gym-heading");
const alertBox = document.getElementById("dashboard-alert");
const notificationList = document.getElementById("notification-list");
const markNotificationsReadBtn = document.getElementById("mark-notifications-read-btn");
const enableBrowserAlertsBtn = document.getElementById("enable-browser-alerts-btn");
const browserAlertStatus = document.getElementById("browser-alert-status");

const statNewMembers = document.getElementById("stat-new-members");
const statRecoveredMembers = document.getElementById("stat-recovered-members");
const statLostMembers = document.getElementById("stat-lost-members");

const membersFeed = document.getElementById("home-members-feed");
const homeFilters = Array.from(document.querySelectorAll("[data-home-filter]"));

let dashboardData = null;
let members = [];
let currentFilter = "all";
let recoveredMemberIds = new Set();

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

function monthKey(dateInput) {
  const dt = new Date(dateInput);
  if (Number.isNaN(dt.getTime())) return "";
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
}

function currentMonthKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function deriveRecoveredIdsFromNotifications(items) {
  const set = new Set();
  const currentMonth = currentMonthKey();
  (items || []).forEach((item) => {
    const kind = String(item.kind || "").toUpperCase();
    const data = item.data || {};
    const createdAt = item.created_at || "";
    if (kind === "CHECKIN" && data.mode === "existing" && monthKey(createdAt) === currentMonth && item.member_id) {
      set.add(Number(item.member_id));
    }
  });
  return set;
}

function isNewMember(member) {
  return monthKey(member.created_at) === currentMonthKey();
}

function memberTileStatus(member) {
  if (member.status === "Lost") return "lost";
  if (recoveredMemberIds.has(Number(member.id))) return "recovered";
  if (isNewMember(member)) return "new";
  if (member.status === "At Risk") return "at_risk";
  return "active";
}

function statusBadge(statusKind) {
  if (statusKind === "lost") {
    return '<span class="badge lost">Lost</span>';
  }
  if (statusKind === "recovered") {
    return '<span class="badge active">Recovered</span>';
  }
  if (statusKind === "new") {
    return '<span class="badge active">New</span>';
  }
  if (statusKind === "at_risk") {
    return '<span class="badge at-risk">At Risk</span>';
  }
  return '<span class="badge active">Active</span>';
}

function memberNote(member, statusKind) {
  if (statusKind === "lost") {
    const days = member.days_inactive == null ? "a while" : `${member.days_inactive} days`;
    return `This member has not checked in for ${days}. Send a recovery message now.`;
  }
  if (statusKind === "recovered") {
    return "Great news. This member recently came back after being inactive.";
  }
  if (statusKind === "new") {
    return "New member this month. Send a welcome message and keep them engaged.";
  }
  if (statusKind === "at_risk") {
    const days = member.days_inactive == null ? "a few" : member.days_inactive;
    return `This member may be drifting. Last active about ${days} day(s) ago.`;
  }
  return "Member is active and doing well.";
}

function actionText(statusKind) {
  if (statusKind === "lost") return "Send recovery message";
  if (statusKind === "recovered") return "Send thank you message";
  if (statusKind === "new") return "Send welcome message";
  return "Send check-in message";
}

function actionPayload(member, statusKind) {
  if (statusKind === "lost") {
    return { template_type: "lost" };
  }
  if (statusKind === "at_risk") {
    return { template_type: "at_risk" };
  }
  if (statusKind === "recovered") {
    return { message: `Hi ${member.name.split(" ")[0] || "there"}, thanks for coming back. We're glad to see you again.` };
  }
  if (statusKind === "new") {
    return { message: `Hi ${member.name.split(" ")[0] || "there"}, welcome to our business. We're excited to have you with us.` };
  }
  return { template_type: "status" };
}

function filteredMembersForHome() {
  const withKinds = members.map((member) => ({ member, kind: memberTileStatus(member) }));
  if (currentFilter === "new") return withKinds.filter((x) => x.kind === "new");
  if (currentFilter === "recovered") return withKinds.filter((x) => x.kind === "recovered");
  if (currentFilter === "lost") return withKinds.filter((x) => x.kind === "lost");
  return withKinds.filter((x) => ["new", "recovered", "lost", "at_risk"].includes(x.kind));
}

function renderHomeCards() {
  const newCount = members.filter((m) => isNewMember(m)).length;
  const recoveredCount = members.filter((m) => recoveredMemberIds.has(Number(m.id))).length;
  const lostCount = members.filter((m) => m.status === "Lost").length;

  statNewMembers.textContent = String(newCount);
  statRecoveredMembers.textContent = String(recoveredCount);
  statLostMembers.textContent = String(lostCount);
}

function renderMemberFeed() {
  const rows = filteredMembersForHome();
  if (!rows.length) {
    membersFeed.innerHTML = '<div class="empty">No members match this filter right now.</div>';
    return;
  }

  membersFeed.innerHTML = rows
    .map(({ member, kind }) => {
      const payload = actionPayload(member, kind);
      const payloadJson = encodeURIComponent(JSON.stringify(payload));
      return `
        <article class="member-row">
          <div>
            <div class="member-meta">
              <strong>${Retainr.escapeHtml(member.name)}</strong>
              ${statusBadge(kind)}
            </div>
            <div class="member-note">${Retainr.escapeHtml(memberNote(member, kind))}</div>
          </div>
          <div class="row">
            <button
              type="button"
              data-action="home-send-message"
              data-member-id="${member.id}"
              data-payload="${payloadJson}"
            >${Retainr.escapeHtml(actionText(kind))}</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderNotifications(items) {
  if (!items.length) {
    notificationList.innerHTML = '<div class="empty">No notifications yet.</div>';
    return;
  }

  notificationList.innerHTML = items
    .map((item) => {
      const unreadClass = item.is_read ? "" : " unread";
      const memberId = item.member_id ? Number(item.member_id) : 0;
      const messageBtn = memberId > 0
        ? `<button type="button" data-action="notify-send-message" data-member-id="${memberId}">Send Message</button>`
        : "";

      return `
        <article class="notification-item${unreadClass}">
          <div>
            <strong>${Retainr.escapeHtml(item.kind || "NOTICE")}</strong>
            <div>${Retainr.escapeHtml(item.message || "")}</div>
            <small class="muted">${Retainr.formatDateTime(item.created_at)}</small>
          </div>
          <div class="row">${messageBtn}</div>
        </article>
      `;
    })
    .join("");
}

async function sendMessage(memberId, payload) {
  const data = await Retainr.apiRequest("/messages/link", {
    method: "POST",
    body: JSON.stringify({
      member_id: Number(memberId),
      ...(payload || { template_type: "status" }),
    }),
  });
  if (!data.whatsapp_url) {
    throw new Error("No WhatsApp URL returned for this member.");
  }
  const win = window.open(data.whatsapp_url, "_blank");
  if (!win) {
    throw new Error("Popup blocked. Allow popups to open WhatsApp.");
  }
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
  browserAlertStatus.textContent = `Browser Alerts: ${currentPermissionLabel()}`;
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
        if (typeof v === "string" && v.trim()) out.add(v);
      });
    }
  } catch (_) {
    // ignore
  }
  return out;
}

function saveNotifiedKeys(businessId) {
  if (!businessId) return;
  try {
    localStorage.setItem(notifiedStorageKey(businessId), JSON.stringify(Array.from(notifiedEventKeys).slice(-500)));
  } catch (_) {
    // ignore
  }
}

function notificationEventKey(item) {
  if (item.id !== null && item.id !== undefined) return `db:${item.id}`;
  const kind = String(item.kind || "NOTICE").toUpperCase();
  const memberId = item.member_id ? Number(item.member_id) : 0;
  if (kind === "MESSAGE_NEEDED" && memberId > 0) {
    const status = String((item.data && item.data.status) || "").toUpperCase() || "UNKNOWN";
    return `attention:${memberId}:${status}`;
  }
  return `adhoc:${kind}:${memberId}:${item.created_at || ""}:${item.message || ""}`;
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
  try {
    const notification = new Notification(notificationTitle(item, businessName || "Retainr"), {
      body: String(item.message || "You have a new dashboard alert."),
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
    // ignore
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
    events.forEach((item) => notifiedEventKeys.add(notificationEventKey(item)));
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
  if (changed) saveNotifiedKeys(currentBusinessId);
}

async function loadDashboard(options = {}) {
  const silent = Boolean(options.silent);
  const notifyBrowser = Boolean(options.notifyBrowser);
  if (!silent) hideAlert();

  dashboardData = await Retainr.apiRequest("/dashboard");
  processIncomingBrowserAlerts(dashboardData, notifyBrowser);

  const gym = dashboardData.gym || {};
  members = dashboardData.members || [];
  recoveredMemberIds = deriveRecoveredIdsFromNotifications(dashboardData.notifications || []);

  gymHeading.textContent = `${gym.gym_name || "Business"} Home`;

  renderHomeCards();
  renderMemberFeed();
  renderNotifications(dashboardData.notifications || []);
}

function startDashboardPolling() {
  if (pollTimer) return;
  pollTimer = window.setInterval(async () => {
    try {
      await loadDashboard({ silent: true, notifyBrowser: true });
    } catch (_) {
      // keep polling
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
    showAlert("Browser alerts are already enabled.", "success");
    updateBrowserAlertStatusLabel();
    return;
  }
  if (Notification.permission === "denied") {
    showAlert("Browser alerts are blocked. Allow notifications for this site in browser settings.");
    updateBrowserAlertStatusLabel();
    return;
  }

  enableBrowserAlertsBtn.disabled = true;
  enableBrowserAlertsBtn.textContent = "Enabling...";
  try {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      showAlert("Browser alerts enabled. You'll be notified about check-ins and follow-up alerts.", "success");
    } else if (permission === "denied") {
      showAlert("Browser alerts were blocked. You can change this in browser settings.");
    } else {
      showAlert("Browser alerts were not enabled.");
    }
  } catch (_) {
    showAlert("Could not request browser notification permission.");
  } finally {
    updateBrowserAlertStatusLabel();
  }
}

membersFeed.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.dataset.action !== "home-send-message") return;

  const memberId = Number(target.dataset.memberId || 0);
  if (!memberId) return;

  let payload = { template_type: "status" };
  try {
    payload = JSON.parse(decodeURIComponent(target.dataset.payload || "%7B%7D"));
  } catch (_) {
    payload = { template_type: "status" };
  }

  hideAlert();
  try {
    await sendMessage(memberId, payload);
    showAlert("WhatsApp opened successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

notificationList.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.dataset.action !== "notify-send-message") return;

  const memberId = Number(target.dataset.memberId || 0);
  if (!memberId) return;

  hideAlert();
  try {
    await sendMessage(memberId, { template_type: "status" });
    showAlert("WhatsApp opened successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

homeFilters.forEach((btn) => {
  btn.addEventListener("click", () => {
    currentFilter = String(btn.dataset.homeFilter || "all");
    homeFilters.forEach((b) => b.classList.toggle("active", b === btn));
    renderMemberFeed();
  });
});

markNotificationsReadBtn.addEventListener("click", async () => {
  hideAlert();
  try {
    await Retainr.apiRequest("/notifications/mark-all-read", { method: "POST", body: "{}" });
    await loadDashboard();
    showAlert("Notifications marked as read.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

if (enableBrowserAlertsBtn) {
  enableBrowserAlertsBtn.addEventListener("click", async () => {
    await requestBrowserAlertsPermission();
  });
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  loadDashboard({ silent: true, notifyBrowser: true }).catch(() => {});
});

updateBrowserAlertStatusLabel();
loadDashboard()
  .then(() => startDashboardPolling())
  .catch((error) => showAlert(error.message));
