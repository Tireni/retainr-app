const form = document.getElementById("admin-login-form");
const emailInput = document.getElementById("admin-email");
const passwordInput = document.getElementById("admin-password");
const submitBtn = document.getElementById("admin-login-btn");
const alertBox = document.getElementById("admin-login-alert");

function showError(message) {
  if (!alertBox) return;
  alertBox.className = "alert error";
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideError() {
  if (!alertBox) return;
  alertBox.style.display = "none";
}

function readNext() {
  const query = new URLSearchParams(window.location.search);
  const value = String(query.get("next") || "/admin");
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/api/")) {
    return "/admin";
  }
  return value;
}

async function loginAdmin(event) {
  event.preventDefault();
  hideError();
  submitBtn.disabled = true;
  const oldText = submitBtn.textContent;
  submitBtn.textContent = "Signing in...";
  try {
    const payload = {
      email: String(emailInput.value || "").trim(),
      password: String(passwordInput.value || ""),
      next: readNext(),
    };
    const res = await fetch("/api/admin/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.error || "Invalid admin login.");
    }
    window.location.href = data.next || "/admin";
  } catch (error) {
    showError(error.message || "Unable to login.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = oldText;
  }
}

if (form) {
  form.addEventListener("submit", loginAdmin);
}
