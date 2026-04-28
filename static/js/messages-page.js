const alertBox = document.getElementById("messages-alert");
const modal = document.getElementById("template-modal");
const modalKind = document.getElementById("template-modal-kind");
const nameInput = document.getElementById("template-name-input");
const purposeInput = document.getElementById("template-purpose-input");
const messageInput = document.getElementById("template-message-input");
const cancelBtn = document.getElementById("template-cancel-btn");
const saveBtn = document.getElementById("template-save-btn");

let dashboardData = null;
let activeTemplateKey = "";

const TEMPLATE_META = {
  welcome: {
    displayName: "Welcome Message",
    backendField: "at_risk",
    purpose: "Use this when a new member joins.",
  },
  recovery: {
    displayName: "Recovery Message",
    backendField: "lost",
    purpose: "Use this when members have not checked in for a while.",
  },
  thanks: {
    displayName: "Thank You Message",
    backendField: "promo",
    purpose: "Use this after a member returns or engages again.",
  },
};

function showAlert(message, type = "error") {
  alertBox.className = `alert ${type}`;
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideAlert() {
  alertBox.style.display = "none";
}

function openModal() {
  modal.classList.add("show");
  modal.setAttribute("aria-hidden", "false");
}

function closeModal() {
  modal.classList.remove("show");
  modal.setAttribute("aria-hidden", "true");
}

function currentTemplates() {
  return (dashboardData && dashboardData.gym && dashboardData.gym.templates) || {};
}

function templateValue(templateKey) {
  const meta = TEMPLATE_META[templateKey];
  if (!meta) return "";
  return String(currentTemplates()[meta.backendField] || "");
}

function openTemplateEditor(templateKey) {
  const meta = TEMPLATE_META[templateKey];
  if (!meta) return;
  activeTemplateKey = templateKey;

  modalKind.textContent = meta.displayName;
  nameInput.value = meta.displayName;
  purposeInput.value = meta.purpose;
  messageInput.value = templateValue(templateKey);
  openModal();
}

async function loadTemplates() {
  hideAlert();
  dashboardData = await Retainr.apiRequest("/dashboard");
}

async function saveTemplate() {
  const templates = currentTemplates();
  const payload = {
    at_risk_message: String(templates.at_risk || ""),
    lost_message: String(templates.lost || ""),
    promo_message: String(templates.promo || ""),
  };

  const meta = TEMPLATE_META[activeTemplateKey];
  if (!meta) return;
  if (meta.backendField === "at_risk") payload.at_risk_message = messageInput.value.trim();
  if (meta.backendField === "lost") payload.lost_message = messageInput.value.trim();
  if (meta.backendField === "promo") payload.promo_message = messageInput.value.trim();

  if (!messageInput.value.trim()) {
    showAlert("Message text cannot be empty.");
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = "Saving...";
  try {
    await Retainr.apiRequest("/messages/templates", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadTemplates();
    closeModal();
    showAlert("Template saved successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save Template";
  }
}

document.querySelectorAll("[data-open-template]").forEach((btn) => {
  btn.addEventListener("click", () => {
    openTemplateEditor(String(btn.dataset.openTemplate || ""));
  });
});

cancelBtn.addEventListener("click", closeModal);
modal.addEventListener("click", (event) => {
  if (event.target === modal) {
    closeModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModal();
});

saveBtn.addEventListener("click", saveTemplate);

loadTemplates().catch((error) => {
  showAlert(error.message);
});
