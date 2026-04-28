const form = document.getElementById("member-form");
const formAlert = document.getElementById("form-alert");
const pageTitle = document.getElementById("form-title");
const saveBtn = document.getElementById("save-btn");

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

pageTitle.textContent = "Add Member";

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
    await Retainr.apiRequest("/members", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    window.location.href = "/members";
  } catch (error) {
    showFormAlert(error.message);
  } finally {
    setFormLoading(false);
  }
});
