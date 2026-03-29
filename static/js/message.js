const messageAlert = document.getElementById("message-alert");
const memberNameEl = document.getElementById("member-name");
const memberStatusEl = document.getElementById("member-status");
const messageBox = document.getElementById("message-box");
const sendBtn = document.getElementById("send-btn");

let phoneWhatsApp = "";

function showMessageAlert(message, type = "error") {
  messageAlert.className = `alert ${type}`;
  messageAlert.textContent = message;
  messageAlert.style.display = "block";
}

function hideMessageAlert() {
  messageAlert.style.display = "none";
}

async function loadMessageData() {
  const params = new URLSearchParams(window.location.search);
  const memberId = Number(params.get("member_id") || 0);
  if (!memberId) {
    showMessageAlert("Missing member_id in URL.");
    sendBtn.disabled = true;
    return;
  }

  try {
    const data = await Retainr.apiRequest(`/members/${memberId}/message`);
    const member = data.member;
    memberNameEl.textContent = member.name;
    memberStatusEl.innerHTML = `<span class="badge ${Retainr.statusClass(member.status)}">${Retainr.escapeHtml(member.status)}</span>`;
    messageBox.value = data.message || "";
    phoneWhatsApp = data.phone_whatsapp || "";
    if (!phoneWhatsApp) {
      showMessageAlert("This member has no valid WhatsApp number.");
      sendBtn.disabled = true;
    }
  } catch (error) {
    showMessageAlert(error.message);
    sendBtn.disabled = true;
  }
}

sendBtn.addEventListener("click", () => {
  hideMessageAlert();
  const text = messageBox.value.trim();
  if (!text) {
    showMessageAlert("Message cannot be empty.");
    return;
  }
  if (!phoneWhatsApp) {
    showMessageAlert("No valid WhatsApp number for this member.");
    return;
  }
  const url = `https://wa.me/${phoneWhatsApp}?text=${encodeURIComponent(text)}`;
  window.open(url, "_blank");
});

loadMessageData();
