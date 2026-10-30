// Renders the link-preview images (1200x630) shown when the site's address is shared in chats and social apps.
// Developer tool, not needed at runtime. Needs Playwright:  node scripts/og/make_og_images.js
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
  for (const lang of ["tr", "en"]) {
    await page.goto(`file://${path.join(__dirname, "og-image.html")}?lang=${lang}`);
    await page.screenshot({ path: path.join(__dirname, "..", "..", "static", "img", `og-image-${lang}.png`) });
  }
  await browser.close();
})();
