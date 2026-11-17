// Second Netlify site (the Plant Room): set SAFFRON_SITE=plant in that site's environment and its root page becomes the Plant Room.
// The main site leaves this unset and serves the Plant Room at /plant (web/netlify.toml).
import { copyFileSync, existsSync } from "node:fs";
if (process.env.SAFFRON_SITE === "plant" && existsSync("dist/plant.html")) {
  copyFileSync("dist/index.html", "dist/app.html");
  copyFileSync("dist/plant.html", "dist/index.html");
  console.log("site-role: Plant Room site - / serves the Plant Room (the app stays at /app.html)");
}
