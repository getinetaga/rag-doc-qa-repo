# Mermaid diagrams

This folder contains Mermaid source files used to illustrate the repository architecture and pipelines.

Files:
- `architecture.mmd` — overall component diagram (ingestion, embedding, vector store, RAG, app).
- `pipeline.mmd` — ingestion → embedding → indexing → retrieval → LLM flow.

How to render (recommended):

1. Install the Mermaid CLI (Node.js required):

```bash
npm install -g @mermaid-js/mermaid-cli
```

2. Render all diagrams to SVG/PNG using the included scripts in the project root:

Linux / macOS:

```bash
./scripts/generate_mermaid.sh
```

Windows (PowerShell):

```powershell
.\scripts\generate_mermaid.ps1
```

If you don't want to install the CLI, use the VS Code Mermaid Preview extension to preview `.mmd` files inline.
