// Registers the service worker so the app can be installed and shows an offline page.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.error("Service worker registration failed:", error);
    });
  });
}

// Ctrl/Cmd+Enter saves the quick-add form from a hardware keyboard.
document.addEventListener("keydown", (event) => {
  const isSubmitShortcut = (event.ctrlKey || event.metaKey) && event.key === "Enter";
  const textarea = event.target;
  if (isSubmitShortcut && textarea instanceof HTMLTextAreaElement && textarea.form) {
    textarea.form.requestSubmit();
  }
});

// Feature checkboxes save instantly and refresh the idea's progress without a page reload.
function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

function renderProgress(card, { done_count: done, total }) {
  const percent = total ? Math.round((100 * done) / total) : 0;
  card.querySelector(".progress-label").textContent = `${done}/${total}`;
  card.querySelector(".progress-fill").style.width = `${percent}%`;
  card.querySelector(".progress").classList.toggle("progress-complete", total > 0 && done === total);
}

async function saveFeatureState(checkbox) {
  const item = checkbox.closest(".feature");
  const response = await fetch(item.dataset.toggleUrl, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
    body: `done=${checkbox.checked}`,
  });
  if (!response.ok) throw new Error(`Saving feature failed with status ${response.status}`);
  renderProgress(checkbox.closest(".idea-card"), await response.json());
}

document.addEventListener("change", (event) => {
  if (!event.target.matches(".feature-check input")) return;
  const checkbox = event.target;
  saveFeatureState(checkbox).catch((error) => {
    checkbox.checked = !checkbox.checked;
    console.error(error);
    alert("Kaydedilemedi, bağlantını kontrol et.");
  });
});

// The capture textarea grows with its content, like a chat input.
document.addEventListener("input", (event) => {
  if (!event.target.matches(".quick-bar textarea")) return;
  event.target.style.height = "auto";
  event.target.style.height = `${event.target.scrollHeight}px`;
});

// After quick capture the list page asks the server to fill the new idea with AI, so saving itself
// is instant. Whatever happens, we end up on the normal page; a failed AI run is shown there.
async function enrichPendingIdea() {
  const card = document.querySelector("[data-enrich-url]");
  if (!card) return;
  try {
    // "manual": do not follow the redirect, or its page render would consume the flash message.
    await fetch(card.dataset.enrichUrl, { method: "POST", redirect: "manual", headers: { "X-CSRFToken": csrfToken() } });
  } catch (error) {
    console.error("AI enrichment request failed:", error);
  }
  window.location.replace(card.dataset.doneUrl);
}

enrichPendingIdea();

// Chat: show a typing indicator while the server waits for the AI, and start at the newest message.
const chatForm = document.querySelector(".chat-form");
if (chatForm) {
  window.scrollTo(0, document.body.scrollHeight);
  chatForm.addEventListener("submit", () => {
    document.querySelector(".typing").hidden = false;
    window.scrollTo(0, document.body.scrollHeight);
  });
}

// Remember the last chosen AI across pages and visits (per device).
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

// The repository review takes a while: tell the user it is working instead of showing a frozen page.
const inspectForm = document.querySelector(".inspect-form");
if (inspectForm) {
  inspectForm.addEventListener("submit", () => {
    inspectForm.querySelector("button").disabled = true;
    document.querySelector(".inspect-working").hidden = false;
  });
}

// Theme switch: Otomatik (system) -> Açık -> Koyu -> Gri. The choice is remembered on this device.
const THEME_STORAGE_KEY = "idealar.theme";
const THEMES = [
  { value: "", label: "🌓 Otomatik" },
  { value: "light", label: "☀️ Açık" },
  { value: "dark", label: "🌙 Koyu" },
  { value: "gray", label: "🌫️ Gri" },
];

function currentThemeIndex() {
  const index = THEMES.findIndex((theme) => theme.value === (document.documentElement.dataset.theme || ""));
  return index === -1 ? 0 : index;
}

function showTheme(theme) {
  if (theme.value) document.documentElement.dataset.theme = theme.value;
  else delete document.documentElement.dataset.theme;
  document.querySelectorAll(".theme-toggle").forEach((button) => (button.textContent = theme.label));
}

function saveTheme(theme) {
  try {
    if (theme.value) localStorage.setItem(THEME_STORAGE_KEY, theme.value);
    else localStorage.removeItem(THEME_STORAGE_KEY);
  } catch (error) {
    console.warn("Could not remember the theme:", error);
  }
}

showTheme(THEMES[currentThemeIndex()]);
document.addEventListener("click", (event) => {
  if (!event.target.closest(".theme-toggle")) return;
  const next = THEMES[(currentThemeIndex() + 1) % THEMES.length];
  showTheme(next);
  saveTheme(next);
});

// On a computer (mouse + keyboard) Enter sends the message and Shift+Enter adds a new line.
// On touch devices Enter stays a new line because the on-screen keyboard has no Shift and a send button exists.
const DESKTOP_INPUT = window.matchMedia("(hover: hover) and (pointer: fine)");

document.addEventListener("keydown", (event) => {
  const textarea = event.target;
  const isPlainEnter = event.key === "Enter" && !event.shiftKey && !event.isComposing;
  if (!isPlainEnter || !DESKTOP_INPUT.matches) return;
  if (!(textarea instanceof HTMLTextAreaElement) || !textarea.matches(".quick-bar textarea")) return;
  event.preventDefault();
  textarea.form.requestSubmit();
});
