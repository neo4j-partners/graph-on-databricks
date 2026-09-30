import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";

const variants = {
  finance: {
    title: "Finance",
    file: "finance.html",
    theme: "finance",
    description: "Clean demo style with finance-oriented accenting.",
  },
  "graph-lakehouse": {
    title: "Graph Lakehouse",
    file: "graph-lakehouse.html",
    theme: "graph-lakehouse",
    description: "Technical graph-paper treatment for architecture and data model slides.",
  },
  default: {
    title: "Default",
    file: "default.html",
    theme: "default",
    description: "Built-in GitHub Markdown style.",
  },
  gaia: {
    title: "Gaia",
    file: "gaia.html",
    theme: "gaia",
    description: "Built-in classic presentation style.",
  },
  uncover: {
    title: "Uncover",
    file: "uncover.html",
    theme: "uncover",
    description: "Built-in centered minimal style.",
  },
};

const decks = {
  full: {
    title: "Full Demo Guide",
    source: "slides.md",
    description: "Complete graph-enriched lakehouse narrative.",
  },
  "15min": {
    title: "15-Minute Talk",
    source: "slides-15min.md",
    description: "Shorter version for tight conference or meeting slots.",
  },
};

const requested = process.argv[2] ?? "all";
const selected =
  requested === "all"
    ? Object.entries(variants)
    : [[requested, variants[requested]]].filter(([, variant]) => variant);

if (selected.length === 0) {
  console.error(`Unknown theme variant: ${requested}`);
  console.error(`Available variants: ${Object.keys(variants).join(", ")}, all`);
  process.exit(1);
}

rmSync("build", { force: true, recursive: true });
mkdirSync("build", { recursive: true });

for (const [deckKey, deck] of Object.entries(decks)) {
  for (const [variantKey, variant] of selected) {
    execFileSync(
      "marp",
      [
        deck.source,
        "-o",
        join("build", outputFile(deckKey, variantKey)),
        "--html",
        "--theme-set",
        "themes/finance.css",
        "--theme-set",
        "themes/graph-lakehouse.css",
        "--theme",
        variant.theme,
      ],
      { stdio: "inherit" },
    );
  }
}

for (const asset of readdirSync(".")) {
  if (/\.(png|jpe?g|gif|webp|svg)$/i.test(asset)) {
    copyFileSync(asset, join("build", asset));
  }
}

writeFileSync(join("build", ".nojekyll"), "");

if (requested === "all") {
  copyFileSync(join("build", outputFile("full", "finance")), join("build", "slides.html"));
  copyFileSync(join("build", outputFile("15min", "finance")), join("build", "slides-15min.html"));
  writeFileSync(join("build", "index.html"), renderIndex());
}

function outputFile(deckKey, variantKey) {
  if (deckKey === "full") {
    return variants[variantKey].file;
  }

  return `${deckKey}-${variantKey}.html`;
}

function renderIndex() {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Finance Genie</title>
    <style>
      :root {
        color-scheme: light;
        --ink: #172033;
        --muted: #5b6678;
        --line: #d9e0ea;
        --accent: #0f766e;
        --accent-2: #2563eb;
        --surface: #ffffff;
        --bg: #f8fafc;
      }

      * {
        box-sizing: border-box;
      }

      body {
        background:
          linear-gradient(90deg, var(--accent) 0 10px, transparent 10px),
          var(--bg);
        color: var(--ink);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
      }

      main {
        margin: 0 auto;
        max-width: 1080px;
        padding: 72px 24px 64px 42px;
      }

      h1 {
        font-size: clamp(36px, 6vw, 64px);
        line-height: 1;
        margin: 0 0 16px;
      }

      p {
        color: var(--muted);
        font-size: 19px;
        line-height: 1.5;
        margin: 0;
        max-width: 760px;
      }

      .eyebrow {
        color: var(--accent);
        font-size: 14px;
        font-weight: 800;
        letter-spacing: 0.08em;
        margin-bottom: 14px;
        text-transform: uppercase;
      }

      .summary {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
        margin: 36px 0 0;
      }

      .summary-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px;
      }

      .summary-card strong {
        color: var(--ink);
        display: block;
        font-size: 17px;
        margin-bottom: 8px;
      }

      .summary-card span {
        color: var(--muted);
        display: block;
        font-size: 15px;
        line-height: 1.45;
      }

      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin: 32px 0 40px;
      }

      .button {
        align-items: center;
        background: var(--accent);
        border-radius: 6px;
        color: white;
        display: inline-flex;
        font-weight: 700;
        min-height: 44px;
        padding: 0 16px;
        text-decoration: none;
      }

      .button.secondary {
        background: var(--ink);
      }

      .button.tertiary {
        background: var(--accent-2);
      }
    </style>
  </head>
  <body>
    <main>
      <div class="eyebrow">Finance Genie</div>
      <h1>Graph-enriched analytics for Databricks Genie</h1>
      <p>Finance Genie demonstrates how Neo4j Graph Data Science can enrich Databricks Lakehouse tables with network features, so Genie can answer questions about fraud-ring structure, risk communities, and relationship-driven patterns using ordinary Delta columns.</p>
      <div class="actions">
        <a class="button" href="./slides.html">Open full slide deck</a>
        <a class="button secondary" href="./slides-15min.html">Open 15-minute deck</a>
        <a class="button tertiary" href="https://github.com/neo4j-partners/graph-on-databricks/tree/main/finance-genie">View project on GitHub</a>
      </div>
      <section class="summary" aria-label="Project overview">
        <div class="summary-card">
          <strong>Baseline</strong>
          <span>Genie answers standard BI questions over Silver tables, but network centrality and community structure are not present in row-level data.</span>
        </div>
        <div class="summary-card">
          <strong>Graph enrichment</strong>
          <span>Neo4j GDS computes PageRank, Louvain communities, and shared-merchant similarity from account, merchant, and transfer relationships.</span>
        </div>
        <div class="summary-card">
          <strong>Lakehouse output</strong>
          <span>The graph features land back in Gold Delta tables as scalar columns that Genie, SQL, dashboards, and ML can use directly.</span>
        </div>
      </section>
    </main>
  </body>
</html>
`;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
