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
  const src = String(previewImage.currentSrc || previewImage.src || "").trim();
  if (!src) {
    showAlert("Sticker preview is not ready yet.");
    return;
  }
  if (!previewImage.complete || Number(previewImage.naturalWidth || 0) <= 0) {
    showAlert("Sticker preview is still loading. Please try again in a moment.");
    return;
  }

  const w = window.open("", "_blank", "width=860,height=900");
  if (!w) {
    showAlert("Popup blocked. Allow popups to print your sticker.");
    return;
  }

  const safeSrc = src.replace(/"/g, "&quot;");
  w.document.write(`<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Print Sticker</title>
    <style>
      @page { margin: 10mm; }
      body { font-family: Arial, sans-serif; padding: 12px; margin: 0; }
      .wrap { max-width: 720px; margin: 0 auto; text-align: center; }
      img { width: 100%; height: auto; border: 1px solid #ddd; border-radius: 12px; display: block; }
      .err { display: none; margin-top: 12px; color: #b91c1c; font-size: 14px; }
      @media print {
        body { padding: 0; }
        .wrap { max-width: 100%; }
        img { border: none; border-radius: 0; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <img id="print-image" src="${safeSrc}" alt="Sticker">
      <div id="print-error" class="err">Could not load sticker image for printing.</div>
    </div>
    <script>
      (function () {
        const img = document.getElementById("print-image");
        const err = document.getElementById("print-error");
        let printed = false;

        function doPrint() {
          if (printed) return;
          printed = true;
          setTimeout(function () {
            window.focus();
            window.print();
          }, 120);
        }

        img.addEventListener("load", doPrint, { once: true });
        img.addEventListener("error", function () {
          err.style.display = "block";
        }, { once: true });

        if (img.complete && img.naturalWidth > 0) {
          doPrint();
        } else {
          // Fallback in case load event is delayed by browser pop-up timing.
          setTimeout(doPrint, 1800);
        }

        window.onafterprint = function () {
          setTimeout(function () { window.close(); }, 80);
        };
      })();
    <\/script>
  </body>
</html>`);
  w.document.close();
}

printBtn.addEventListener("click", printSticker);

loadStickerContext().catch((error) => showAlert(error.message));
