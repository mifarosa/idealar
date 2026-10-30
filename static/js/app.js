// Idealar front-end behaviour. Everything degrades gracefully: pages work without JS, JS only speeds things up.

// ---------- Service worker (installable PWA, offline page) ----------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.error("Service worker registration failed:", error);
    });
  });
}

// Texts come from the page (translated on the server); the Turkish defaults only matter if that script is missing.
function text(key, fallback) {
  return (window.IDEALAR_TEXT && window.IDEALAR_TEXT[key]) || fallback;
}

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

function isTyping(target) {
  return target instanceof HTMLElement && (target.isContentEditable || target.matches("input, textarea, select"));
}

// ---------- Toasts: flash messages fade away; errors stay until clicked ----------
document.querySelectorAll(".toast").forEach((toast) => {
  toast.addEventListener("click", () => toast.remove());
  if (!toast.classList.contains("toast-error")) setTimeout(() => toast.remove(), 5000);
});

// ---------- Feature checklist: instant save, progress updated in place ----------
function renderProgress(ideaId, { done_count: done, total }) {
  const percent = total ? Math.round((100 * done) / total) : 0;
  const count = document.querySelector(`#idea-${ideaId} .feature-count`);
  if (count) count.textContent = `${done} / ${total}`;
  const row = document.getElementById(`row-${ideaId}`);
  if (!row) return;
  row.querySelector(".row-progress").textContent = `${done}/${total}`;
  row.querySelector(".fill").style.width = `${percent}%`;
}

async function saveFeatureState(checkbox) {
  const item = checkbox.closest(".feature");
  const response = await fetch(item.dataset.toggleUrl, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
    body: `done=${checkbox.checked}`,
  });
  if (!response.ok) throw new Error(`Saving feature failed with status ${response.status}`);
  renderProgress(checkbox.closest(".detail").dataset.idea, await response.json());
}

document.addEventListener("change", (event) => {
  if (!event.target.matches(".feature .check")) return;
  const checkbox = event.target;
  saveFeatureState(checkbox).catch((error) => {
    checkbox.checked = !checkbox.checked;
    console.error(error);
    alert(text("saveFailed", "Kaydedilemedi, bağlantını kontrol et."));
  });
});

// ---------- Rename in place (features, conversations): pencil button -> type -> Enter ----------
function postForm(url, fields) {
  return fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(fields),
  });
}

// Makes `label` editable; `save(text)` must resolve to the stored text or throw an Error with a user-facing message.
function editInPlace(label, save) {
  const original = label.textContent;
  label.contentEditable = "true";
  label.focus();
  document.getSelection().selectAllChildren(label);

  const finish = async (shouldSave) => {
    label.removeEventListener("blur", onBlur);
    label.contentEditable = "false";
    const typed = label.textContent.trim();
    if (!shouldSave || typed === original) {
      label.textContent = original;
      return;
    }
    try {
      label.textContent = await save(typed);
    } catch (error) {
      label.textContent = original;
      alert(error.message);
    }
  };
  const onBlur = () => finish(true);
  label.addEventListener("blur", onBlur);
  // The text may sit inside a <label> or a link; without this, clicking it while editing would toggle or navigate.
  label.addEventListener("click", (event) => { if (label.isContentEditable) event.preventDefault(); });
  label.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); label.blur(); }
    if (event.key === "Escape") { label.removeEventListener("blur", onBlur); finish(false); }
  });
}

async function saveRename(url, field, text) {
  const response = await postForm(url, { [field]: text });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || text("notSaved", "Kaydedilemedi."));
  return body[field];
}

document.addEventListener("click", (event) => {
  const featureButton = event.target.closest("[data-edit]");
  if (featureButton) {
    const item = featureButton.closest(".feature");
    editInPlace(item.querySelector(".feature-text"), (text) => saveRename(item.dataset.editUrl, "text", text));
    return;
  }
  const renameButton = event.target.closest("[data-rename-url]");
  if (renameButton) {
    const label = renameButton.closest("li, .page-head").querySelector("[data-rename-text]");
    editInPlace(label, (text) => saveRename(renameButton.dataset.renameUrl, "title", text));
  }
});

// Forms that destroy something ask first.
document.addEventListener("submit", (event) => {
  const question = event.target.dataset.confirm;
  if (question && !window.confirm(question)) event.preventDefault();
});

// ---------- AI fills a freshly captured idea; saving itself stays instant ----------
async function enrichPendingIdea() {
  const article = document.querySelector("[data-enrich-url]");
  if (!article) return;
  try {
    // "manual": do not follow the redirect, or its page render would consume the flash message.
    await fetch(article.dataset.enrichUrl, { method: "POST", redirect: "manual", headers: { "X-CSRFToken": csrfToken() } });
  } catch (error) {
    console.error("AI enrichment request failed:", error);
  }
  window.location.replace(article.dataset.doneUrl);
}
enrichPendingIdea();

// ---------- Remember the chosen AI (per device) ----------
const PROVIDER_STORAGE_KEY = "idealar.provider";

function restoreProviderChoice() {
  let saved = "";
  try {
    saved = localStorage.getItem(PROVIDER_STORAGE_KEY) || "";
  } catch (error) {
    return; // storage can be blocked (private mode); the picker then just defaults to Otomatik
  }
  document.querySelectorAll(".provider-select").forEach((select) => {
    if ([...select.options].some((option) => option.value === saved)) select.value = saved;
  });
}

document.addEventListener("change", (event) => {
  if (!event.target.matches(".provider-select")) return;
  try {
    localStorage.setItem(PROVIDER_STORAGE_KEY, event.target.value);
  } catch (error) {
    console.warn("Could not remember the AI choice:", error);
  }
});
restoreProviderChoice();

// ---------- Theme: Açık / Gri / Koyu, remembered on this device ----------
const THEME_STORAGE_KEY = "idealar.theme";

function activeTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit) return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function markActiveTheme() {
  const current = activeTheme();
  document.querySelectorAll("[data-set]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.set === current)));
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-set]");
  if (!button) return;
  document.documentElement.dataset.theme = button.dataset.set;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, button.dataset.set);
  } catch (error) {
    console.warn("Could not remember the theme:", error);
  }
  markActiveTheme();
});
markActiveTheme();

// ---------- Keyboard: Enter sends on computers, N / slash / J / K for speed ----------
const DESKTOP_INPUT = window.matchMedia("(hover: hover) and (pointer: fine)");
const MESSAGE_BOX = ".capture textarea, .composer textarea";

document.addEventListener("keydown", (event) => {
  const box = event.target;
  const isMessageBox = box instanceof HTMLTextAreaElement && box.matches(MESSAGE_BOX);
  const plainEnter = event.key === "Enter" && !event.shiftKey && !event.isComposing;
  const submitShortcut = (event.ctrlKey || event.metaKey) && event.key === "Enter";
  // On touch devices Enter stays a new line: the on-screen keyboard has no Shift and a send button exists.
  if (isMessageBox && ((plainEnter && DESKTOP_INPUT.matches) || submitShortcut)) {
    event.preventDefault();
    box.form.requestSubmit();
  }
});

function focusFirst(selector) {
  const element = document.querySelector(selector);
  if (element) element.focus();
  return Boolean(element);
}

function moveSelection(step) {
  const rows = [...document.querySelectorAll(".rows .row")];
  const current = rows.findIndex((row) => row.hasAttribute("aria-current"));
  const next = rows[current === -1 ? 0 : current + step];
  if (next) window.location.href = next.href;
}

document.addEventListener("keydown", (event) => {
  if (isTyping(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
  const handlers = {
    n: () => focusFirst(".capture textarea"),
    "/": () => focusFirst("[data-shortcut-search]"),
    j: () => moveSelection(1),
    k: () => moveSelection(-1),
    ArrowDown: () => moveSelection(1),
    ArrowUp: () => moveSelection(-1),
  };
  const handler = handlers[event.key];
  if (handler && document.querySelector(".rows") && handler() !== false) event.preventDefault();
});

// ---------- Capture bar: a "Vazgeç" button appears while there is something to discard ----------
const captureForm = document.querySelector(".capture");
if (captureForm) {
  const box = captureForm.querySelector("textarea");
  const cancel = captureForm.querySelector(".cancel");
  const sync = () => { cancel.hidden = !box.value && document.activeElement !== box; };
  const discard = () => {
    box.value = "";
    box.style.height = "auto";
    box.blur();
    sync();
  };
  box.addEventListener("input", sync);
  box.addEventListener("focus", sync);
  // Not on blur: tapping the cancel button itself blurs the box first and would hide the button before the click lands.
  cancel.addEventListener("click", discard);
  box.addEventListener("keydown", (event) => { if (event.key === "Escape") discard(); });
  sync();
}

// ---------- Kanban: drag a card to another column or position ----------
function dropIndex(list, y) {
  const cards = [...list.querySelectorAll(".card:not(.dragging)")];
  const after = cards.findIndex((card) => y < card.getBoundingClientRect().top + card.offsetHeight / 2);
  return after === -1 ? cards.length : after;
}

document.querySelectorAll("[data-drop-zone]").forEach((list) => {
  list.addEventListener("dragover", (event) => {
    event.preventDefault();
    list.classList.add("drag-over");
  });
  list.addEventListener("dragleave", () => list.classList.remove("drag-over"));
  list.addEventListener("drop", async (event) => {
    event.preventDefault();
    list.classList.remove("drag-over");
    const card = document.querySelector(".card.dragging");
    if (!card) return;
    const index = dropIndex(list, event.clientY);
    const status = list.closest(".column").dataset.status;
    const response = await postForm(card.dataset.moveUrl, { status, index });
    if (response.ok) window.location.reload(); // counts and arrow buttons depend on the column
    else alert(text("cardMoveFailed", "Kart taşınamadı."));
  });
});
document.addEventListener("dragstart", (event) => {
  const card = event.target.closest && event.target.closest(".card");
  if (card) {
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.task);
  }
});
document.addEventListener("dragend", (event) => {
  if (event.target.classList) event.target.classList.remove("dragging");
});

// ---------- Dialogs (e.g. the full "what's new" list): open/close buttons, click outside to close ----------
document.addEventListener("click", (event) => {
  const opener = event.target.closest("[data-open-dialog]");
  if (opener) {
    document.getElementById(opener.dataset.openDialog).showModal();
    return;
  }
  if (event.target.closest("[data-close-dialog]")) {
    event.target.closest("dialog").close();
    return;
  }
  if (event.target instanceof HTMLDialogElement) event.target.close(); // the backdrop counts as the dialog itself
});

// ---------- Small conveniences ----------
document.addEventListener("input", (event) => {
  if (!event.target.matches(MESSAGE_BOX)) return;
  event.target.style.height = "auto"; // the textarea grows with its content, like a chat input
  event.target.style.height = `${event.target.scrollHeight}px`;
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-autosubmit]")) event.target.form.submit();
});

const chatForm = document.querySelector(".chat-form");
if (chatForm) {
  const page = document.querySelector(".page");
  if (page) page.scrollTop = page.scrollHeight;
  chatForm.addEventListener("submit", () => {
    const typing = document.querySelector(".typing");
    if (typing) typing.hidden = false;
    if (page) page.scrollTop = page.scrollHeight;
  });
}

// Slow AI actions (refresh, similarity search): show that something is happening instead of a frozen page.
function showBusyNote(text, button) {
  const detail = document.querySelector(".detail");
  if (!detail || detail.querySelector(".ai-working")) return;
  const note = document.createElement("p");
  note.className = "ai-working";
  note.setAttribute("role", "status");
  note.textContent = text;
  // Right under the buttons, where the user is looking; the top of a long page may be off-screen.
  (button.closest(".actions") || detail.querySelector("h2")).after(note);
}

document.addEventListener("submit", (event) => {
  if (event.defaultPrevented) return; // e.g. the user declined a delete confirmation
  const button = event.target.querySelector("[data-pending]");
  if (!button) return;
  button.dataset.label = button.textContent;
  button.textContent = button.dataset.pending;
  button.disabled = true; // also stops accidental double submissions
  if (button.dataset.busyNote) showBusyNote(button.dataset.busyNote, button);
});

// Coming back with the browser's back button restores the page as it was; undo the busy state.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  document.querySelectorAll("[data-pending][disabled]").forEach((button) => {
    button.disabled = false;
    if (button.dataset.label) button.textContent = button.dataset.label;
  });
  document.querySelectorAll(".detail .ai-working").forEach((note) => note.remove());
});

// Copy buttons: put the text of a target field on the clipboard (with a fallback for non-secure contexts).
async function copyText(field) {
  try {
    await navigator.clipboard.writeText(field.value);
  } catch (error) {
    field.select(); // clipboard API needs HTTPS; the old way works everywhere
    if (!document.execCommand("copy")) throw error;
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  const field = document.querySelector(button.dataset.copyTarget);
  const status = document.querySelector(".copy-status");
  try {
    await copyText(field);
    button.textContent = button.dataset.copied;
    if (status) status.textContent = text("copied", "Panoya kopyalandı. Claude'a yapıştırabilirsin.");
    setTimeout(() => { button.textContent = text("copy", "Kopyala"); }, 2500);
  } catch (error) {
    field.focus();
    field.select();
    if (status) status.textContent = text("copyFailed", "Otomatik kopyalanamadı; metin seçili, Ctrl+C ile kopyala.");
  }
});

const inspectForm = document.querySelector(".inspect-form");
if (inspectForm) {
  inspectForm.addEventListener("submit", () => {
    inspectForm.querySelector("button").disabled = true;
    document.querySelector(".inspect-working").hidden = false;
  });
}
