const tableBody = document.getElementById("members-body");
const membersAlert = document.getElementById("members-alert");
const filterButtons = Array.from(document.querySelectorAll("[data-filter]"));
const searchInput = document.getElementById("search-input");
const selectAllCheckbox = document.getElementById("select-all-checkbox");
const bulkSendBtn = document.getElementById("bulk-send-btn");

let activeFilter = "all";
let query = "";
let loadedMembers = [];
const selectedIds = new Set();

function showMembersAlert(message, type = "error") {
  membersAlert.className = `alert ${type}`;
  membersAlert.textContent = message;
  membersAlert.style.display = "block";
}

function hideMembersAlert() {
  membersAlert.style.display = "none";
}

function normalizeFilter(filter) {
  if (filter === "at_risk") return "at risk";
  return filter;
}

function setActiveFilterUi() {
  filterButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.filter === activeFilter);
  });
}

function updateSelectAllCheckbox() {
  if (!loadedMembers.length) {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
    return;
  }
  const selectedVisible = loadedMembers.filter((member) => selectedIds.has(member.id)).length;
  if (selectedVisible === 0) {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
    return;
  }
  if (selectedVisible === loadedMembers.length) {
    selectAllCheckbox.checked = true;
    selectAllCheckbox.indeterminate = false;
    return;
  }
  selectAllCheckbox.checked = false;
  selectAllCheckbox.indeterminate = true;
}

function renderTable(items) {
  loadedMembers = items;
  updateSelectAllCheckbox();

  if (!items.length) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="9"><span class="muted">No members found for this filter.</span></td>
      </tr>
    `;
    return;
  }

  tableBody.innerHTML = items
    .map((member) => {
      return `
        <tr>
          <td>
            <input
              type="checkbox"
              data-action="select"
              data-id="${member.id}"
              ${selectedIds.has(member.id) ? "checked" : ""}
              title="Select member"
            >
          </td>
          <td>${Retainr.escapeHtml(member.name)}</td>
          <td>${Retainr.escapeHtml(member.phone || "-")}</td>
          <td>${Retainr.formatDate(member.last_visit)}</td>
          <td>${Retainr.formatDate(member.expiry_date)}</td>
          <td><span class="badge ${Retainr.statusClass(member.status)}">${Retainr.escapeHtml(member.status)}</span></td>
          <td>${Retainr.money(member.monthly_fee)}</td>
          <td>${member.days_inactive == null ? "-" : `${member.days_inactive} days`}</td>
          <td>
            <div class="actions">
              <a class="btn btn-secondary" href="/message?member_id=${member.id}">Message</a>
              <button data-action="visit" data-id="${member.id}">Mark Visit</button>
              <a class="btn btn-outline" href="/member-form?id=${member.id}">Edit</a>
              <button class="btn-danger" data-action="delete" data-id="${member.id}" data-name="${Retainr.escapeHtml(member.name)}">Delete</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function loadMembers() {
  hideMembersAlert();
  const params = new URLSearchParams();
  if (activeFilter !== "all") {
    params.set("status", normalizeFilter(activeFilter));
  }
  if (query) {
    params.set("q", query);
  }
  try {
    const data = await Retainr.apiRequest(`/members?${params.toString()}`);
    renderTable(data.items || []);
  } catch (error) {
    showMembersAlert(error.message);
  }
}

function bulkSendSelectedMembers() {
  hideMembersAlert();
  const selectedMembers = loadedMembers.filter((member) => selectedIds.has(member.id));
  if (!selectedMembers.length) {
    showMembersAlert("Select at least one visible member before sending.", "error");
    return;
  }

  const sendable = selectedMembers.filter((member) => member.whatsapp_url);
  const skipped = selectedMembers.length - sendable.length;
  if (!sendable.length) {
    showMembersAlert("Selected members do not have valid WhatsApp numbers.", "error");
    return;
  }

  let opened = 0;
  sendable.forEach((member, index) => {
    const timer = 350 * index;
    window.setTimeout(() => {
      const win = window.open(member.whatsapp_url, "_blank");
      if (win) opened += 1;
      if (index === sendable.length - 1) {
        const parts = [`Opened ${opened}/${sendable.length} WhatsApp chat(s).`];
        if (skipped > 0) parts.push(`Skipped ${skipped} without valid numbers.`);
        if (opened < sendable.length) parts.push("Allow popups for this site to open all chats.");
        showMembersAlert(parts.join(" "), opened > 0 ? "success" : "error");
      }
    }, timer);
  });
}

filterButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeFilter = btn.dataset.filter;
    setActiveFilterUi();
    loadMembers();
  });
});

searchInput.addEventListener("input", () => {
  query = searchInput.value.trim();
  loadMembers();
});

selectAllCheckbox.addEventListener("change", () => {
  if (selectAllCheckbox.checked) {
    loadedMembers.forEach((member) => selectedIds.add(member.id));
  } else {
    loadedMembers.forEach((member) => selectedIds.delete(member.id));
  }
  renderTable(loadedMembers);
});

bulkSendBtn.addEventListener("click", bulkSendSelectedMembers);

tableBody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  if (!action || !id) return;

  const memberId = Number(id);
  if (!memberId) return;

  if (action === "visit") {
    try {
      await Retainr.apiRequest(`/members/${memberId}/mark-visit`, { method: "POST", body: "{}" });
      await loadMembers();
    } catch (error) {
      showMembersAlert(error.message);
    }
    return;
  }

  if (action === "delete") {
    const name = target.dataset.name || "this member";
    if (!window.confirm(`Delete ${name}?`)) return;
    try {
      await Retainr.apiRequest(`/members/${memberId}`, { method: "DELETE" });
      selectedIds.delete(memberId);
      showMembersAlert("Member deleted.", "success");
      await loadMembers();
    } catch (error) {
      showMembersAlert(error.message);
    }
  }
});

tableBody.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (target.dataset.action !== "select") return;
  const memberId = Number(target.dataset.id || 0);
  if (!memberId) return;
  if (target.checked) selectedIds.add(memberId);
  else selectedIds.delete(memberId);
  updateSelectAllCheckbox();
});

setActiveFilterUi();
loadMembers();
