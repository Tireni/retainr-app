const registerForm = document.getElementById("register-form");
const registerAlert = document.getElementById("register-alert");
const registerBtn = document.getElementById("register-btn");

function showRegisterAlert(message, type = "error") {
  registerAlert.className = `alert ${type}`;
  registerAlert.textContent = message;
  registerAlert.style.display = "block";
}

function hideRegisterAlert() {
  registerAlert.style.display = "none";
}

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideRegisterAlert();
  const payload = {
    gym_name: document.getElementById("gym_name").value.trim(),
    owner_name: document.getElementById("owner_name").value.trim(),
    email: document.getElementById("email").value.trim(),
    password: document.getElementById("password").value,
  };

  registerBtn.disabled = true;
  registerBtn.textContent = "Creating...";
  try {
    const data = await Retainr.apiRequest("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    window.location.href = data.next || "/dashboard";
  } catch (error) {
    showRegisterAlert(error.message);
  } finally {
    registerBtn.disabled = false;
    registerBtn.textContent = "Create Account";
  }
});
