const loginForm = document.getElementById("login-form");
const loginAlert = document.getElementById("login-alert");
const loginBtn = document.getElementById("login-btn");

function showLoginAlert(message, type = "error") {
  loginAlert.className = `alert ${type}`;
  loginAlert.textContent = message;
  loginAlert.style.display = "block";
}

function hideLoginAlert() {
  loginAlert.style.display = "none";
}

function getNextPath() {
  const params = new URLSearchParams(window.location.search);
  const next = (params.get("next") || "").trim();
  if (!next || !next.startsWith("/") || next.startsWith("/api/") || next.startsWith("//")) {
    return "/dashboard";
  }
  if (next === "/login" || next === "/register" || next === "/admin-login") {
    return "/dashboard";
  }
  return next;
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideLoginAlert();
  const payload = {
    email: document.getElementById("email").value.trim(),
    password: document.getElementById("password").value,
    next: getNextPath(),
  };
  loginBtn.disabled = true;
  loginBtn.textContent = "Signing in...";
  try {
    const data = await Retainr.apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    window.location.href = data.next || "/dashboard";
  } catch (error) {
    showLoginAlert(error.message);
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = "Login";
  }
});
