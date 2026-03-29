const form = document.getElementById("member-form");
const formAlert = document.getElementById("form-alert");
const pageTitle = document.getElementById("form-title");
const saveBtn = document.getElementById("save-btn");

const params = new URLSearchParams(window.location.search);
const memberId = Number(params.get("id") || 0);
const isEdit = memberId > 0;

function showFormAlert(message, type = "error") {
  formAlert.className = `alert ${type}`;
  formAlert.textContent = message;
  formAlert.style.display = "block";
}

function hideFormAlert() {
  formAlert.style.display = "none";
}

function setFormLoading(isLoading) {
  saveBtn.disabled = isLoading;
  saveBtn.textContent = isLoading ? "Saving..." : "Save Member";
}

function setFieldValue(id, value) {
  const field = document.getElementById(id);
  if (!field) return;
  field.value = value || "";
}

async function loadMemberIfEdit() {
  if (!isEdit) return;
  pageTitle.textContent = "Edit Member";
  try {
    const data = await Retainr.apiRequest(`/members/${memberId}`);
    const member = data.member;
    setFieldValue("name", member.name);
    setFieldValue("phone", member.phone);
    setFieldValue("monthly_fee", member.monthly_fee);
    setFieldValue("expiry_date", member.expiry_date);
    setFieldValue("last_visit", member.last_visit);
    setFieldValue("goal", member.goal);
    setFieldValue("purpose", member.purpose);
    setFieldValue("preferred_time", member.preferred_time);
  } catch (error) {
    showFormAlert(error.message);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideFormAlert();

  const payload = {
    name: document.getElementById("name").value.trim(),
    phone: document.getElementById("phone").value.trim(),
    monthly_fee: document.getElementById("monthly_fee").value.trim(),
    expiry_date: document.getElementById("expiry_date").value.trim(),
    last_visit: document.getElementById("last_visit").value.trim(),
    goal: document.getElementById("goal").value.trim(),
    purpose: document.getElementById("purpose").value.trim(),
    preferred_time: document.getElementById("preferred_time").value.trim(),
  };

  setFormLoading(true);
  try {
    if (isEdit) {
      await Retainr.apiRequest(`/members/${memberId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await Retainr.apiRequest("/members", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    window.location.href = "/members";
  } catch (error) {
    showFormAlert(error.message);
  } finally {
    setFormLoading(false);
  }
});

loadMemberIfEdit();
