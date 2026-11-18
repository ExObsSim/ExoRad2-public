# AI agent guidance for ExoRad 2

This directory holds tool-neutral guidance that repository-aware AI agents can
use to answer user questions and help set up ExoRad payloads.

`../AGENTS.md` is the canonical shared guide (the [agents.md](https://agents.md)
standard). Any repository-aware model can read it; agents that do not pick it up
automatically should be pointed at it.

- `codebase-map.md` — repository structure and high-value source / documentation
  paths.
- `parameter-setup-guide.md` — how the payload XML is parsed and how to help
  users edit parameters safely.
