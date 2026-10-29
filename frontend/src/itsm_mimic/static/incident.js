// Polls the incident and its pending approvals. Uses textContent only (agent output is untrusted).
(() => {
  const number = document.currentScript.dataset.number;
  const list = document.getElementById("work-notes");
  const badge = document.getElementById("state-badge");
  const stateSelect = document.getElementById("state-select");
  const status = document.getElementById("notes-status");
  const approvalsPanel = document.getElementById("approvals-panel");
  const approvalsList = document.getElementById("approvals");
  let lastNoteId = null;
  let lastState = badge.textContent;
  let lastApprovals = "";

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function input(type, name, value, attrs = {}) {
    const node = document.createElement(type === "textarea" ? "textarea" : "input");
    if (type !== "textarea") node.type = type;
    node.name = name;
    if (value !== undefined) node.value = value;
    Object.assign(node, attrs);
    return node;
  }

  function renderNotes(notes) {
    list.replaceChildren(
      ...notes.map((n) => {
        const item = el("li", `note note-${n.kind}`);
        const meta = el("div", "note-meta");
        meta.append(el("strong", "", n.author), el("span", "note-kind", n.kind), el("time", "", n.created_at));
        item.append(meta, el("div", "note-text", n.text));
        return item;
      }),
    );
    if (!notes.length) list.append(el("li", "empty", "No work notes yet."));
  }

  function renderApprovals(approvals) {
    approvalsPanel.hidden = approvals.length === 0;
    approvalsList.replaceChildren(
      ...approvals.map((a) => {
        const item = el("li", "approval");
        const meta = el("div", "note-meta");
        meta.append(el("strong", "", a.agent), el("span", "note-kind", a.tool_name), el("time", "", a.requested_at));
        const form = document.createElement("form");
        form.method = "post";
        form.action = `/incidents/${number}/approvals/${a.id}`;
        form.className = "approval-form";
        const approve = el("button", "btn btn-primary", "Approve");
        approve.name = "decision";
        approve.value = "approve";
        const deny = el("button", "btn btn-danger", "Deny");
        deny.name = "decision";
        deny.value = "deny";
        form.append(
          input("text", "approver", localStorage.getItem("approver") || "", { required: true, placeholder: "Your name" }),
          input("text", "comment", "", { placeholder: "Comment (optional)" }),
          approve,
          deny,
        );
        form.addEventListener("submit", () => localStorage.setItem("approver", form.approver.value));
        item.append(meta, el("div", "note-text", JSON.stringify(a.tool_input, null, 2)), form);
        return item;
      }),
    );
  }

  async function refreshApprovals() {
    const resp = await fetch(`/api/incidents/${number}/approvals`);
    if (!resp.ok) return;
    const approvals = await resp.json();
    const key = approvals.map((a) => a.id).join(",");
    const typing = approvalsPanel.contains(document.activeElement);
    if (key !== lastApprovals && !typing) {
      renderApprovals(approvals);
      lastApprovals = key;
    }
  }

  async function refresh() {
    try {
      const resp = await fetch(`/api/incidents/${number}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const newest = data.work_notes.length ? data.work_notes[0].id : 0;
      if (newest !== lastNoteId) {
        renderNotes(data.work_notes);
        lastNoteId = newest;
      }
      if (data.state !== lastState) {
        badge.textContent = data.state;
        badge.className = `state state-${data.state.toLowerCase().replace(/ /g, "-")}`;
        stateSelect.value = data.state;
        lastState = data.state;
      }
      await refreshApprovals();
      status.textContent = `Live · updated ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      status.textContent = `Refresh failed (${err.message})`;
    }
  }

  refresh();
  setInterval(refresh, 3000);
})();
