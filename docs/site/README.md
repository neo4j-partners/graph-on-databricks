# Graph on Databricks Site

This folder builds the GitHub Pages site for the repo. The site has a home page and the project slide decks, all published at the root.

## Build and preview

You need Node.js 22 LTS and Python 3. Run these commands from the repo root:

```bash
(cd docs/slides && npm ci && npm run build:all)
node docs/site/build-site.mjs
python3 -m http.server 8080 --directory docs/site/build
```

Open <http://localhost:8080/> to view the site.

## What the build does

- **Slides:** The script copies the slide build from `docs/slides/build/` into the site root. The home page carries the deck links, so it replaces the Marp gallery page (`index.html`) from the slide build.
- **Home page:** The script renders `build/index.html` from the `featured`, `projects`, and `resources` arrays in [`build-site.mjs`](./build-site.mjs). To add a card, add an entry to one of those arrays.

## Publishing

The workflow [`.github/workflows/deploy-site.yml`](../../.github/workflows/deploy-site.yml) builds the project slides, runs `build-site.mjs`, and deploys `docs/site/build/` to GitHub Pages. It runs on pushes to `main` that change `docs/site/**`, the project slides, or the workflow file.
