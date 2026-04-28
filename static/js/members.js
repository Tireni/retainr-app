const membersBody = document.getElementById("members-body");
const membersAlert = document.getElementById("members-alert");
const filterButtons = Array.from(document.querySelectorAll("[data-filter]"));
const searchInput = document.getElementById("search-input");

let activeFilter = "all";
let query = "";
let loadedMembers = [];

function showMembersAlert(message, type = "error") {
  membersAlert.className = `alert ${type}`;
  membersAlert.textContent = message;
  membersAlert.style.display = "block";
}

function hideMembersAlert() {
  membersAlert.style.display = "none";
}

function monthKey(value) {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "";
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
}

function currentMonthKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function isNewMember(member) {
  return monthKey(member.created_at) === currentMonthKey();
}

function isRecoveredMember(member) {
  if (member.status !== "Active") return false;
  if (isNewMember(member)) return false;
  if (!member.last_visit) return false;
  const dt = new Date(member.last_visit);
  if (Number.isNaN(dt.getTime())) return false;
  const now = new Date();
  const days = Math.floor((now.getTime() - dt.getTime()) / 86400000);
  return days >= 0 && days <= 3;
}

function memberKind(member) {
  if (member.status === "Lost") return "lost";
  if (isRecoveredMember(member)) return "recovered";
  if (isNewMember(member)) return "new";
  return "other";
}

function filterMember(member) {
  if (query) {
    const q = query.toLowerCase();
    if (!String(member.name || "").toLowerCase().includes(q) && !String(member.phone || "").toLowerCase().includes(q)) {
      return false;
    }
  }
  const kind = memberKind(member);
  if (activeFilter === "all") {
    return ["new", "recovered", "lost"].includes(kind) || member.status === "At Risk";
  }
  return kind === activeFilter;
}

function badgeFor(member, kind) {
  if (kind === "new") return '<span class="badge active">New</span>';
  if (kind === "recovered") return '<span class="badge active">Recovered</span>';
  if (kind === "lost") return '<span class="badge lost">Lost</span>';
  if (member.status === "At Risk") return '<span class="badge at-risk">At Risk</span>';
  return '<span class="badge active">Active</span>';
}

function explanationFor(member, kind) {
  if (kind === "new") return "Joined this month. Send a warm welcome and what to expect next.";
  if (kind === "recovered") return "Recently active again. Send a thank-you message to keep momentum.";
  if (kind === "lost") return "No recent check-ins. Send a recovery message before they disengage fully.";
  if (member.status === "At Risk") return "Activity is dropping. A quick follow-up can bring them back.";
  return "No immediate action needed.";
}

function primaryActionFor(member, kind) {
  if (kind === "new") {
    return {
      text: "Send welcome message",
      payload: { message: `Hi ${member.name.split(" ")[0] || "there"}, welcome to our business. We are excited to have you.` },
    };
  }
  if (kind === "recovered") {
    return {
      text: "Send thank you message",
      payload: { message: `Hi ${member.name.split(" ")[0] || "there"}, welcome back. We are glad to see you again.` },
    };
  }
  if (kind === "lost") {
    return {
      text: "Send recovery message",
      payload: { template_type: "lost" },
    };
  }
  return {
    text: "Send check-in message",
    payload: { template_type: "at_risk" },
  };
}

async function openWhatsappForMember(memberId, payload) {
  const res = await Retainr.apiRequest("/messages/link", {
    method: "POST",
    body: JSON.stringify({
      member_id: Number(memberId),
      ...(payload || { template_type: "status" }),
    }),
  });
  if (!res.whatsapp_url) {
    throw new Error("No WhatsApp URL returned for this member.");
  }
  const win = window.open(res.whatsapp_url, "_blank");
  if (!win) {
    throw new Error("Popup blocked. Allow popups for this site.");
  }
}

function renderMembers() {
  const rows = loadedMembers.filter(filterMember);
  if (!rows.length) {
    membersBody.innerHTML = '<div class="empty">No members match this filter right now.</div>';
    return;
  }

  membersBody.innerHTML = rows
    .map((member) => {
      const kind = memberKind(member);
      const action = primaryActionFor(member, kind);
      return `
        <article class="member-row">
          <div>
            <div class="member-meta">
              <strong>${Retainr.escapeHtml(member.name)}</strong>
              ${badgeFor(member, kind)}
            </div>
            <div class="member-note">${Retainr.escapeHtml(explanationFor(member, kind))}</div>
          </div>
          <div class="row">
            <button
              type="button"
              data-action="send-primary"
              data-id="${member.id}"
              data-payload="${encodeURIComponent(JSON.stringify(action.payload))}"
            >${Retainr.escapeHtml(action.text)}</button>
            <button class="btn-secondary" type="button" data-action="visit" data-id="${member.id}">Mark Visit</button>
            <button class="btn-danger" type="button" data-action="delete" data-id="${member.id}" data-name="${Retainr.escapeHtml(member.name)}">Delete</button>
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadMembers() {
  hideMembersAlert();
  try {
    const data = await Retainr.apiRequest("/members");
    loadedMembers = data.items || [];
    renderMembers();
  } catch (error) {
    showMembersAlert(error.message);
  }
}

filterButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeFilter = btn.dataset.filter || "all";
    filterButtons.forEach((b) => b.classList.toggle("active", b === btn));
    renderMembers();
  });
});

searchInput.addEventListener("input", () => {
  query = searchInput.value.trim();
  renderMembers();
});

membersBody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const action = target.dataset.action;
  const id = Number(target.dataset.id || 0);
  if (!action || !id) return;

  try {
    if (action === "send-primary") {
      let payload = { template_type: "status" };
      try {
        payload = JSON.parse(decodeURIComponent(target.dataset.payload || "%7B%7D"));
      } catch (_) {
        payload = { template_type: "status" };
      }
      await openWhatsappForMember(id, payload);
      showMembersAlert("WhatsApp opened successfully.", "success");
      return;
    }

    if (action === "visit") {
      await Retainr.apiRequest(`/members/${id}/mark-visit`, { method: "POST", body: "{}" });
      await loadMembers();
      showMembersAlert("Visit marked successfully.", "success");
      return;
    }

    if (action === "delete") {
      const name = target.dataset.name || "this member";
      if (!window.confirm(`Delete ${name}?`)) return;
      await Retainr.apiRequest(`/members/${id}`, { method: "DELETE" });
      await loadMembers();
      showMembersAlert("Member deleted.", "success");
    }
  } catch (error) {
    showMembersAlert(error.message);
  }
});

loadMembers();
