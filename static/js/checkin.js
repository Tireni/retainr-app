const alertEl = document.getElementById("checkin-alert");
const gymNameEl = document.getElementById("checkin-gym-name");
const ownerNameEl = document.getElementById("checkin-owner-name");
const socialLinksEl = document.getElementById("social-links");

const phoneInput = document.getElementById("checkin-phone");
const lookupBtn = document.getElementById("lookup-btn");

const stepPhone = document.getElementById("step-phone");
const stepExisting = document.getElementById("step-existing");
const stepNew = document.getElementById("step-new");
const stepSuccess = document.getElementById("step-success");

const existingNameEl = document.getElementById("existing-name");
const existingPurposeInput = document.getElementById("existing-purpose");
const existingTimeInput = document.getElementById("existing-time");
const existingCheckinBtn = document.getElementById("existing-checkin-btn");
const changePhoneBtn = document.getElementById("change-phone-btn");

const newNameInput = document.getElementById("new-name");
const newPhoneInput = document.getElementById("new-phone");
const newGoalInput = document.getElementById("new-goal");
const newPurposeInput = document.getElementById("new-purpose");
const newTimeInput = document.getElementById("new-time");
const newCheckinBtn = document.getElementById("new-checkin-btn");
const newBackBtn = document.getElementById("new-back-btn");

const successText = document.getElementById("success-text");
const todayMessageEl = document.getElementById("today-message");

let checkinToken = "";
let currentPhone = "";
let existingMember = null;
let alreadyCheckedInToday = false;
let currentGym = null;

function showAlert(message, type = "error") {
  alertEl.className = `alert ${type}`;
  alertEl.textContent = message;
  alertEl.style.display = "block";
}

function hideAlert() {
  alertEl.style.display = "none";
}

function showStep(step) {
  [stepPhone, stepExisting, stepNew, stepSuccess].forEach((el) => {
    el.classList.remove("active");
  });
  step.classList.add("active");
}

function resolveTokenFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const queryToken = (params.get("t") || "").trim();
  if (queryToken) return queryToken;
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts.length >= 2 && parts[0] === "checkin") {
    return decodeURIComponent(parts[1] || "").trim();
  }
  return "";
}

function renderSocialLinks(socials) {
  const entries = [
    ["Instagram", socials.instagram_url],
    ["Facebook", socials.facebook_url],
    ["TikTok", socials.tiktok_url],
    ["WhatsApp", socials.x_url],
    ["Website", socials.website_url],
  ].filter(([, url]) => Boolean(url));

  if (!entries.length) {
    socialLinksEl.innerHTML = '<span class="muted">No social links configured yet.</span>';
    return;
  }
  socialLinksEl.innerHTML = entries
    .map(([label, url]) => `<a class="btn btn-secondary" href="${Retainr.escapeHtml(url)}" target="_blank" rel="noopener">${Retainr.escapeHtml(label)}</a>`)
    .join("");
}

function resetFlow() {
  hideAlert();
  currentPhone = "";
  existingMember = null;
  phoneInput.value = "";
  newNameInput.value = "";
  newPhoneInput.value = "";
  newGoalInput.value = "";
  newPurposeInput.value = "";
  newTimeInput.value = "";
  existingPurposeInput.value = "";
  existingTimeInput.value = "";
  alreadyCheckedInToday = false;
  existingCheckinBtn.disabled = false;
  existingCheckinBtn.textContent = "Check In";
  showStep(stepPhone);
}

async function loadContext() {
  checkinToken = resolveTokenFromUrl();
  if (!checkinToken) {
    throw new Error("Invalid check-in link. Ask the business for their QR/check-in URL.");
  }
  const data = await Retainr.apiRequest(`/public/checkin/context/${encodeURIComponent(checkinToken)}`);
  currentGym = data.gym || null;
  gymNameEl.textContent = `${currentGym?.gym_name || "Business"} Check-In`;
  ownerNameEl.textContent = currentGym?.owner_name ? `Managed by ${currentGym.owner_name}` : "";
  renderSocialLinks(currentGym?.socials || {});
}

async function lookupPhone() {
  hideAlert();
  const phone = phoneInput.value.trim();
  if (!phone) {
    showAlert("Please enter your WhatsApp phone number.");
    return;
  }
  lookupBtn.disabled = true;
  lookupBtn.textContent = "Checking...";
  try {
    const data = await Retainr.apiRequest("/public/checkin/lookup", {
      method: "POST",
      body: JSON.stringify({ token: checkinToken, phone }),
    });
    currentPhone = phone;
    if (data.exists) {
      existingMember = data.member;
      alreadyCheckedInToday = Boolean(data.checked_in_today);
      existingNameEl.textContent = existingMember.name || "Member";
      if (alreadyCheckedInToday) {
        existingCheckinBtn.disabled = true;
        existingCheckinBtn.textContent = "Already Checked In Today";
        showAlert("You already checked in today.", "success");
      } else {
        existingCheckinBtn.disabled = false;
        existingCheckinBtn.textContent = "Check In";
      }
      showStep(stepExisting);
      existingPurposeInput.focus();
      return;
    }
    newPhoneInput.value = phone;
    showStep(stepNew);
    newNameInput.focus();
  } catch (error) {
    showAlert(error.message);
  } finally {
    lookupBtn.disabled = false;
    lookupBtn.textContent = "Continue";
  }
}

async function submitCheckin(payload, button) {
  hideAlert();
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Saving...";
  try {
    const data = await Retainr.apiRequest("/public/checkin/submit", {
      method: "POST",
      body: JSON.stringify({
        token: checkinToken,
        ...payload,
      }),
    });
    const memberName = data.member?.name || "Member";
    successText.textContent = `${memberName}, you're checked in. Have a great session.`;
    if (todayMessageEl) {
      const businessName = currentGym?.gym_name || "our business";
      todayMessageEl.textContent = `Thanks for checking in with ${businessName} today.`;
    }
    showStep(stepSuccess);
  } catch (error) {
    showAlert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

lookupBtn.addEventListener("click", lookupPhone);
phoneInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    lookupPhone();
  }
});

existingCheckinBtn.addEventListener("click", async () => {
  if (alreadyCheckedInToday) {
    showAlert("You already checked in today.", "success");
    return;
  }
  if (!currentPhone) {
    showAlert("WhatsApp phone number is missing. Start again.");
    return;
  }
  await submitCheckin(
    {
      phone: currentPhone,
      purpose: existingPurposeInput.value.trim(),
      session_time: existingTimeInput.value.trim(),
    },
    existingCheckinBtn,
  );
});

newCheckinBtn.addEventListener("click", async () => {
  if (!newNameInput.value.trim()) {
    showAlert("Full name is required for new members.");
    return;
  }
  await submitCheckin(
    {
      phone: newPhoneInput.value.trim(),
      name: newNameInput.value.trim(),
      goal: newGoalInput.value.trim(),
      purpose: newPurposeInput.value.trim(),
      session_time: newTimeInput.value.trim(),
    },
    newCheckinBtn,
  );
});

changePhoneBtn.addEventListener("click", () => {
  showStep(stepPhone);
  phoneInput.focus();
});

newBackBtn.addEventListener("click", () => {
  showStep(stepPhone);
  phoneInput.focus();
});

(async () => {
  try {
    await loadContext();
    resetFlow();
    phoneInput.focus();
  } catch (error) {
    showAlert(error.message);
    lookupBtn.disabled = true;
    newCheckinBtn.disabled = true;
    existingCheckinBtn.disabled = true;
  }
})();
