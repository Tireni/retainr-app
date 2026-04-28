const alertBox = document.getElementById("settings-alert");
const gymNameInput = document.getElementById("gym-name-input");
const ownerNameInput = document.getElementById("owner-name-input");
const saveBtn = document.getElementById("save-settings-btn");

const companyLogoInput = document.getElementById("company-logo-input");
const uploadCompanyLogoBtn = document.getElementById("upload-company-logo-btn");
const removeCompanyLogoBtn = document.getElementById("remove-company-logo-btn");
const companyLogoPreview = document.getElementById("company-logo-preview");

let gymContext = null;

function showAlert(message, type = "error") {
  alertBox.className = `alert ${type}`;
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideAlert() {
  alertBox.style.display = "none";
}

function renderLogo(url) {
  if (!url) {
    companyLogoPreview.style.display = "none";
    companyLogoPreview.removeAttribute("src");
    removeCompanyLogoBtn.style.display = "none";
    return;
  }
  companyLogoPreview.src = `${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`;
  companyLogoPreview.style.display = "block";
  removeCompanyLogoBtn.style.display = "inline-flex";
}

async function loadContext() {
  hideAlert();
  const data = await Retainr.apiRequest("/dashboard");
  gymContext = data.gym || {};

  gymNameInput.value = gymContext.gym_name || "";
  ownerNameInput.value = gymContext.owner_name || "";
  renderLogo(gymContext.company_logo_url || "");
}

async function saveSettings() {
  hideAlert();
  if (!gymContext) {
    showAlert("Unable to load business context.");
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = "Saving...";
  try {
    await Retainr.apiRequest("/gym/settings", {
      method: "PUT",
      body: JSON.stringify({
        gym_name: gymNameInput.value.trim(),
        owner_name: ownerNameInput.value.trim(),
        instagram_url: ((gymContext.socials || {}).instagram_url || "").trim(),
        facebook_url: ((gymContext.socials || {}).facebook_url || "").trim(),
        tiktok_url: ((gymContext.socials || {}).tiktok_url || "").trim(),
        x_url: ((gymContext.socials || {}).x_url || "").trim(),
        website_url: ((gymContext.socials || {}).website_url || "").trim(),
      }),
    });
    await loadContext();
    showAlert("Settings saved successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save Settings";
  }
}

async function uploadCompanyLogo(file) {
  const body = new FormData();
  body.append("logo", file);
  const res = await fetch("/api/gym/logo", { method: "POST", body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
  return data;
}

async function removeCompanyLogo() {
  const res = await fetch("/api/gym/logo", { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Delete failed (${res.status})`);
  return data;
}

saveBtn.addEventListener("click", saveSettings);

uploadCompanyLogoBtn.addEventListener("click", async () => {
  hideAlert();
  const file = companyLogoInput.files && companyLogoInput.files[0];
  if (!file) {
    showAlert("Choose a logo image first.");
    return;
  }

  uploadCompanyLogoBtn.disabled = true;
  try {
    await uploadCompanyLogo(file);
    companyLogoInput.value = "";
    await loadContext();
    showAlert("Logo uploaded successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    uploadCompanyLogoBtn.disabled = false;
  }
});

removeCompanyLogoBtn.addEventListener("click", async () => {
  hideAlert();
  removeCompanyLogoBtn.disabled = true;
  try {
    await removeCompanyLogo();
    await loadContext();
    showAlert("Logo removed successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    removeCompanyLogoBtn.disabled = false;
  }
});

loadContext().catch((error) => showAlert(error.message));
