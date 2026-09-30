import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SITE_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SITE_DIR, "..", "..");
const BUILD_DIR = join(SITE_DIR, "build");
const FINANCE_BUILD = join(
  REPO_ROOT,
  "finance-genie/docs/demo-guide/slides/build",
);
const FINANCE_PATH = "finance-genie";

const REPO_URL = "https://github.com/neo4j-partners/graph-on-databricks";

const featured = {
  label: "Featured demo",
  title: "Finance Genie",
  description:
    "Neo4j Graph Data Science enriches Databricks Lakehouse tables with network features. PageRank, Louvain communities, and node similarity land in Gold Delta tables as plain columns. Genie can then answer questions about fraud-ring structure and risk communities.",
  tags: ["Fraud", "Graph Data Science", "Genie", "Delta"],
  actions: [
    { text: "Open full slide deck", href: `./${FINANCE_PATH}/slides.html` },
    {
      text: "Open 15-minute deck",
      href: `./${FINANCE_PATH}/slides-15min.html`,
      variant: "secondary",
    },
    {
      text: "View project on GitHub",
      href: `${REPO_URL}/tree/main/finance-genie`,
      variant: "tertiary",
    },
  ],
};

const projects = [
  {
    title: "Agentic Commerce",
    description:
      "A Databricks-hosted shopping assistant backed by a Neo4j product knowledge graph. It uses GraphRAG retrieval and graph-backed memory to search products, diagnose issues, and personalize recommendations.",
    tags: ["GraphRAG", "Agent memory", "Model Serving", "Databricks Apps"],
    href: `${REPO_URL}/tree/main/agentic-commerce`,
  },
  {
    title: "Aircraft GraphRAG",
    description:
      "A notebook-based GraphRAG starter over an aircraft digital twin. It loads the fleet topology into Neo4j, embeds maintenance manuals, and builds vector, graph-enhanced, and hybrid retrievers.",
    tags: ["GraphRAG", "Notebooks", "Vector search"],
    href: `${REPO_URL}/tree/main/aircraft-graphrag`,
  },
  {
    title: "Supplier Risk Graph",
    description:
      "A supply-and-credit risk demo that runs two engines over the same data. Genie Agent answers from Unity Catalog tables. Genie One adds a governed Neo4j knowledge layer that grounds answers in authored definitions, ownership chains, and sub-tier supply paths.",
    tags: ["Knowledge layer", "Genie", "MCP", "Supervisor agent"],
    href: `${REPO_URL}/tree/main/supplier-risk-graph`,
  },
  {
    title: "Supply Chain",
    description:
      "A supply chain risk and disruption assistant. An Agent Bricks Supervisor routes each question to Genie for SQL over Gold Delta tables or to the Neo4j MCP server for graph traversal and GDS algorithms.",
    tags: ["Lakeflow", "Agent Bricks", "GDS", "MCP"],
    href: `${REPO_URL}/tree/main/supply-chain`,
  },
];

const resources = [
  {
    label: "Workshop",
    title: "Databricks + Neo4j: Production AI Agents with Graph and Lakehouse",
    description:
      "Build a multi-agent supervisor over an aircraft digital twin. Neo4j answers the relationship questions and Databricks answers the sensor analytics questions. You finish with a LangGraph agent deployed to Model Serving, with memory stored in your graph.",
    tags: [
      "6 labs",
      "About 5 hours",
      "AuraDB Free",
      "Genie Agent",
      "LangGraph",
      "Agent memory",
    ],
    actions: [
      {
        text: "Open workshop",
        href: "https://neo4j-partners.github.io/databricks-neo4j-workshop/databricks-neo4j-workshop/1.0/index.html",
      },
      {
        text: "Source code",
        href: "https://github.com/neo4j-partners/databricks-neo4j-workshop",
      },
    ],
  },
  {
    label: "Workshop slides",
    title: "Databricks + Neo4j Workshop Slide Decks",
    description:
      "Eight workshop decks follow the labs in presenting order, from the business case for GraphRAG to supervisor agents and agent memory. Eight background decks go deeper on knowledge graph construction, entity resolution, graph features, and connectors.",
    tags: ["8 workshop decks", "8 background decks", "GraphRAG", "Agents"],
    actions: [
      {
        text: "Open slide decks",
        href: "https://neo4j-partners.github.io/databricks-neo4j-workshop/databricks-neo4j-workshop/1.0/slides.html",
      },
    ],
  },
];

if (!existsSync(join(FINANCE_BUILD, "index.html"))) {
  console.error(`Finance Genie build not found at ${FINANCE_BUILD}`);
  console.error(
    "Run `npm ci && npm run build:all` in finance-genie/docs/demo-guide/slides first.",
  );
  process.exit(1);
}

rmSync(BUILD_DIR, { force: true, recursive: true });
mkdirSync(BUILD_DIR, { recursive: true });

cpSync(FINANCE_BUILD, join(BUILD_DIR, FINANCE_PATH), { recursive: true });

// The home page carries the Finance Genie links, so its gallery page is not published.
writeFileSync(join(BUILD_DIR, FINANCE_PATH, "index.html"), renderRedirect("../"));

// Finance Genie used to publish at the site root. Keep its old deck URLs working.
for (const file of readdirSync(FINANCE_BUILD)) {
  if (file.endsWith(".html") && file !== "index.html") {
    writeFileSync(
      join(BUILD_DIR, file),
      renderRedirect(`./${FINANCE_PATH}/${file}`),
    );
  }
}

writeFileSync(join(BUILD_DIR, ".nojekyll"), "");
writeFileSync(join(BUILD_DIR, "index.html"), renderIndex());

console.log(`Site written to ${BUILD_DIR}`);

function renderRedirect(target) {
  const href = escapeHtml(target);
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Redirecting</title>
    <link rel="canonical" href="${href}">
    <meta http-equiv="refresh" content="0; url=${href}">
  </head>
  <body>
    <p>This page moved to <a href="${href}">${href}</a>.</p>
  </body>
</html>
`;
}

function renderIndex() {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Neo4j + Databricks</title>
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

      * { box-sizing: border-box; }

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

      h2 {
        font-size: 26px;
        margin: 52px 0 8px;
      }

      p {
        color: var(--muted);
        font-size: 19px;
        line-height: 1.5;
        margin: 0;
        max-width: 760px;
      }

      .section-intro { font-size: 16px; }

      .eyebrow {
        color: var(--accent);
        font-size: 24px;
        font-weight: 800;
        letter-spacing: 0.08em;
        margin-bottom: 14px;
        text-transform: uppercase;
      }

      .card-label {
        color: var(--accent);
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }

      .card-desc {
        color: var(--muted);
        display: block;
        font-size: 15px;
        line-height: 1.45;
      }

      .featured {
        background: var(--surface);
        border: 1px solid var(--line);
        border-left: 4px solid var(--accent);
        border-radius: 8px;
        margin: 24px 0 0;
        padding: 24px 28px;
      }

      .featured strong {
        display: block;
        font-size: 28px;
        margin: 6px 0 10px;
      }

      .featured .card-desc {
        font-size: 17px;
        max-width: 820px;
      }

      .buttons {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 20px;
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

      .button.secondary { background: var(--ink); }

      .button.tertiary { background: var(--accent-2); }

      .projects {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        margin: 24px 0 0;
      }

      .project-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 8px;
        color: inherit;
        display: flex;
        flex-direction: column;
        padding: 16px 20px 20px;
        text-decoration: none;
        transition: border-color 120ms ease, transform 120ms ease;
      }

      .project-card:hover {
        border-color: var(--accent-2);
        transform: translateY(-2px);
      }

      .project-card strong {
        display: block;
        font-size: 19px;
        margin: 0 0 8px;
      }

      .project-card .tags {
        margin-top: auto;
        padding-top: 16px;
      }

      .project-link {
        color: var(--accent);
        font-weight: 700;
        margin-top: 12px;
      }

      .resources {
        display: grid;
        gap: 16px;
        align-items: start;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        margin: 24px 0 0;
      }

      .resource-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 8px;
        display: flex;
        flex-direction: column;
        padding: 20px;
      }

      .resource-card strong {
        display: block;
        font-size: 19px;
        margin: 6px 0 8px;
      }

      .tags {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 16px 0 0;
      }

      .tag {
        background: var(--bg);
        border: 1px solid var(--line);
        border-radius: 999px;
        color: var(--muted);
        font-size: 13px;
        font-weight: 600;
        padding: 4px 10px;
      }

      .card-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        margin-top: auto;
        padding-top: 16px;
      }

      .card-actions a {
        color: var(--accent);
        font-weight: 700;
        text-decoration: none;
      }

      .card-actions a:hover { text-decoration: underline; }

      @media (max-width: 600px) {
        main { padding: 48px 16px 48px 28px; }
        .featured { padding: 20px; }
      }
    </style>
  </head>
  <body>
    <main>
      <div class="eyebrow">Graph on Databricks</div>
      <h1>Neo4j + Databricks</h1>
      <p>Demos and starter projects that pair a Neo4j graph with the Databricks Lakehouse. They cover graph enrichment of Delta tables, GraphRAG, agent memory, and governed knowledge layers for Genie and supervisor agents.</p>

      <section aria-labelledby="featured">
        <h2 id="featured">Slides and demo</h2>
${renderFeatured(featured)}
      </section>

      <section aria-labelledby="projects">
        <h2 id="projects">More projects</h2>
        <p class="section-intro">Each project lives in the graph-on-databricks repo with its own README and setup steps.</p>
        <div class="projects">
${renderProjects(projects)}
        </div>
      </section>

      <section aria-labelledby="resources">
        <h2 id="resources">Workshop</h2>
        <p class="section-intro">A hands-on workshop for building production AI agents with Neo4j and Databricks.</p>
        <div class="resources">
${renderResources(resources)}
        </div>
      </section>
    </main>
  </body>
</html>
`;
}

function renderFeatured(item) {
  const actions = item.actions
    .map(
      (action) =>
        `            <a class="button${action.variant ? ` ${action.variant}` : ""}" href="${escapeHtml(action.href)}">${escapeHtml(action.text)}</a>`,
    )
    .join("\n");

  return `        <div class="featured">
          <span class="card-label">${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.title)}</strong>
          <span class="card-desc">${escapeHtml(item.description)}</span>
${renderTags(item.tags, "          ")}
          <div class="buttons">
${actions}
          </div>
        </div>`;
}

function renderProjects(items) {
  return items
    .map(
      (item) => `          <a class="project-card" href="${escapeHtml(item.href)}">
            <strong>${escapeHtml(item.title)}</strong>
            <span class="card-desc">${escapeHtml(item.description)}</span>
            <span class="project-link">View on GitHub &rarr;</span>
${renderTags(item.tags, "            ", "span")}
          </a>`,
    )
    .join("\n");
}

function renderResources(items) {
  return items
    .map((item) => {
      const actions = item.actions
        .map(
          (action) =>
            `              <a href="${escapeHtml(action.href)}">${escapeHtml(action.text)} &rarr;</a>`,
        )
        .join("\n");

      return `          <div class="resource-card">
            <span class="card-label">${escapeHtml(item.label)}</span>
            <strong>${escapeHtml(item.title)}</strong>
            <span class="card-desc">${escapeHtml(item.description)}</span>
${renderTags(item.tags, "            ")}
            <div class="card-actions">
${actions}
            </div>
          </div>`;
    })
    .join("\n");
}

function renderTags(tags, indent, element = "div") {
  return `${indent}<${element} class="tags">
${tags.map((tag) => `${indent}  <span class="tag">${escapeHtml(tag)}</span>`).join("\n")}
${indent}</${element}>`;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
