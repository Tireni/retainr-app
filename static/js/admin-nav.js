async function retainrLogout() {
  try {
    await Retainr.apiRequest("/auth/logout", { method: "POST", body: "{}" });
  } catch (error) {
    // Ignore logout API errors; still redirect to login.
  }
  window.location.href = "/login";
}

document.querySelectorAll(".js-admin-logout").forEach((el) => {
  el.addEventListener("click", (event) => {
    event.preventDefault();
    retainrLogout();
  });
});
