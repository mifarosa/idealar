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
