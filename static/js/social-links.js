const alertBox = document.getElementById("social-alert");
const instagramInput = document.getElementById("instagram-url-input");
const whatsappInput = document.getElementById("whatsapp-url-input");
const tiktokInput = document.getElementById("tiktok-url-input");
const facebookInput = document.getElementById("facebook-url-input");
const websiteInput = document.getElementById("website-url-input");
const saveBtn = document.getElementById("save-social-links-btn");

let gymContext = null;

function showAlert(message, type = "error") {
  alertBox.className = `alert ${type}`;
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideAlert() {
  alertBox.style.display = "none";
}

async function loadContext() {
  hideAlert();
  const data = await Retainr.apiRequest("/dashboard");
  gymContext = data.gym || null;
  const socials = (gymContext && gymContext.socials) || {};

  instagramInput.value = socials.instagram_url || "";
  whatsappInput.value = socials.x_url || ""; // mapped to existing backend field
  tiktokInput.value = socials.tiktok_url || "";
  facebookInput.value = socials.facebook_url || "";
  websiteInput.value = socials.website_url || "";
}

async function saveSocialLinks() {
  hideAlert();
  if (!gymContext) {
    showAlert("Unable to load business context. Refresh the page.");
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = "Saving...";
  try {
    await Retainr.apiRequest("/gym/settings", {
      method: "PUT",
      body: JSON.stringify({
        gym_name: String(gymContext.gym_name || "").trim(),
        owner_name: String(gymContext.owner_name || "").trim(),
        instagram_url: instagramInput.value.trim(),
        facebook_url: facebookInput.value.trim(),
        tiktok_url: tiktokInput.value.trim(),
        x_url: whatsappInput.value.trim(),
        website_url: websiteInput.value.trim(),
      }),
    });

    await loadContext();
    showAlert("Social links saved successfully.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save Social Links";
  }
}

saveBtn.addEventListener("click", saveSocialLinks);

loadContext().catch((error) => showAlert(error.message));
