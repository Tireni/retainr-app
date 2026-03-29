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

const messageMemberSelect = document.getElementById("message-member-select");
const messageTemplateSelect = document.getElementById("message-template-select");
const quickMessageBox = document.getElementById("quick-message-box");
const composeTemplateBtn = document.getElementById("compose-template-btn");
const sendQuickMessageBtn = document.getElementById("send-quick-message-btn");
const markNotificationsReadBtn = document.getElementById("mark-notifications-read-btn");

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

let dashboardData = null;
let members = [];
const membersById = new Map();

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
  checkinQrImage.src = gym.checkin_qr_image_url || "";
  checkinUrlLink.href = checkinLink;
  checkinUrlLink.textContent = checkinLink;
  openCheckinLinkBtn.href = checkinLink;
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
  gymHeading.textContent = `${gym.gym_name || "Gym"} Dashboard`;
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

async function loadDashboard() {
  hideAlert();
  dashboardData = await Retainr.apiRequest("/dashboard");
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
    showAlert("Gym settings saved.", "success");
  } catch (error) {
    showAlert(error.message);
  }
});

loadDashboard().catch((error) => {
  showAlert(error.message);
});
