const alertBox = document.getElementById("sticker-alert");
const previewImage = document.getElementById("sticker-preview-image");
const businessNameEl = document.getElementById("sticker-business-name");
const checkinLinkEl = document.getElementById("sticker-checkin-link");
const downloadBtn = document.getElementById("download-sticker-btn");
const printBtn = document.getElementById("print-sticker-btn");

function showAlert(message, type = "error") {
  alertBox.className = `alert ${type}`;
  alertBox.textContent = message;
  alertBox.style.display = "block";
}

function hideAlert() {
  alertBox.style.display = "none";
}

async function loadStickerContext() {
  hideAlert();
  const data = await Retainr.apiRequest("/dashboard");
  const gym = data.gym || {};

  businessNameEl.textContent = String(gym.gym_name || "Business");

  const checkinLink = String(gym.checkin_link || "/my-checkin");
  const previewSrc = String(gym.checkin_qr_image_url || "/api/checkin/qr/image");

  checkinLinkEl.href = checkinLink;
  checkinLinkEl.textContent = checkinLink;

  previewImage.src = `${previewSrc}${previewSrc.includes("?") ? "&" : "?"}v=${Date.now()}`;
  downloadBtn.href = `/api/checkin/qr/download?v=${Date.now()}`;
}

function printSticker() {
  const src = previewImage.src;
  if (!src) {
    showAlert("Sticker preview is not ready yet.");
    return;
  }

  const w = window.open("", "_blank", "width=860,height=900");
  if (!w) {
    showAlert("Popup blocked. Allow popups to print your sticker.");
    return;
  }

  w.document.write(`
    <html>
      <head>
        <title>Print Sticker</title>
        <style>
          body { font-family: Arial, sans-serif; padding: 20px; }
          .wrap { max-width: 520px; margin: 0 auto; text-align: center; }
          img { width: 100%; height: auto; border: 1px solid #ddd; border-radius: 12px; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <img src="${src}" alt="Sticker">
        </div>
      </body>
    </html>
  `);
  w.document.close();
  w.focus();
  w.print();
}

printBtn.addEventListener("click", printSticker);

loadStickerContext().catch((error) => showAlert(error.message));
