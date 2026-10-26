// Idealar front-end behaviour. Everything degrades gracefully: pages work without JS, JS only speeds things up.

// ---------- Service worker (installable PWA, offline page) ----------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.error("Service worker registration failed:", error);
    });
  });
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
    alert("Kaydedilemedi, bağlantını kontrol et.");
  });
});

// ---------- Rename a feature in place (pencil button) ----------
async function saveFeatureName(item, label) {
  const response = await fetch(item.dataset.editUrl, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
    body: `text=${encodeURIComponent(label.textContent.trim())}`,
  });
  if (!response.ok) throw new Error((await response.json()).error || "Kaydedilemedi.");
  label.textContent = (await response.json()).text;
}

function startRenaming(item) {
  const label = item.querySelector(".feature-text");
  const original = label.textContent;
  label.contentEditable = "true";
  label.focus();
  document.getSelection().selectAllChildren(label);

  const finish = async (save) => {
    label.removeEventListener("blur", onBlur);
    label.contentEditable = "false";
    if (!save || label.textContent.trim() === original) {
      label.textContent = original;
      return;
    }
    try {
      await saveFeatureName(item, label);
    } catch (error) {
      label.textContent = original;
      alert(error.message);
    }
  };
  const onBlur = () => finish(true);
  label.addEventListener("blur", onBlur);
  // The text sits inside a <label>; without this, clicking it while editing would toggle the checkbox.
  label.addEventListener("click", (event) => { if (label.isContentEditable) event.preventDefault(); });
  label.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); label.blur(); }
    if (event.key === "Escape") { label.removeEventListener("blur", onBlur); finish(false); }
  });
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-edit]");
  if (button) startRenaming(button.closest(".feature"));
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

const inspectForm = document.querySelector(".inspect-form");
if (inspectForm) {
  inspectForm.addEventListener("submit", () => {
    inspectForm.querySelector("button").disabled = true;
    document.querySelector(".inspect-working").hidden = false;
  });
}
