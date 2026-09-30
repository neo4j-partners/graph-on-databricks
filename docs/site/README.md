# Graph on Databricks Site

This folder builds the GitHub Pages site for the repo. The site has a home page at the root and the Finance Genie slide decks under `/finance-genie/`.

## Build and preview

You need Node.js 22 LTS and Python 3. Run these commands from the repo root:

```bash
(cd finance-genie/docs/demo-guide/slides && npm ci && npm run build:all)
node docs/site/build-site.mjs
python3 -m http.server 8080 --directory docs/site/build
```

Open <http://localhost:8080/> to view the site.

## What the build does

- **Finance Genie:** The script copies the Finance Genie slide build into `build/finance-genie/`. The home page carries the Finance Genie links, so the script replaces the Finance Genie gallery page with a redirect to the home page.
- **Redirects:** Finance Genie used to publish at the site root. The script writes a redirect stub at the root for each old deck page, such as `/slides.html`, so shared links keep working.
- **Home page:** The script renders `build/index.html` from the `featured`, `projects`, and `resources` arrays in [`build-site.mjs`](./build-site.mjs). To add a card, add an entry to one of those arrays.

## Publishing

The workflow [`.github/workflows/deploy-finance-genie-slides.yml`](../../.github/workflows/deploy-finance-genie-slides.yml) builds the Finance Genie slides, runs `build-site.mjs`, and deploys `docs/site/build/` to GitHub Pages. It runs on pushes to `main` that change `docs/site/**`, the Finance Genie slides, or the workflow file.
