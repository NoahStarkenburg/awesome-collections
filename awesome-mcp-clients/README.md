# awesome-mcp-clients [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> A curated list of clients that speak the [Model Context Protocol](https://modelcontextprotocol.io).

MCP **server** lists are everywhere. **Client** lists are sparse. This focuses on apps, agents, editors, and tools that *consume* MCP servers — anything that connects to an MCP server and uses its tools, resources, and prompts.

## Contents

- [Official & First-Party](#official--first-party)
- [IDE Extensions & Editors](#ide-extensions--editors)
- [Coding Agents](#coding-agents)
- [Desktop Chat Apps](#desktop-chat-apps)
- [Web Chat Interfaces](#web-chat-interfaces)
- [CLIs & Dev Tools](#clis--dev-tools)
- [Contributing](#contributing)

---

## Official & First-Party

_Coming soon._

## IDE Extensions & Editors

- **[cline](https://github.com/cline/cline)** — Autonomous coding agent right in your IDE, capable of creating/editing files, executing commands, using the browser, and more with your permission every step of the way. ⭐ 61.4k · TypeScript · Apache-2.0 · updated today
- **[continue](https://github.com/continuedev/continue)** — ⏩ Source-controlled AI checks, enforceable in CI. Powered by the open-source Continue CLI. ⭐ 33k · TypeScript · Apache-2.0 · updated today
- **[cursor](https://github.com/cursor/cursor)** — No description. ⭐ 32.8k · — · no-license · updated 1w ago
- **[zed](https://github.com/zed-industries/zed)** — Code at the speed of thought – Zed is a high-performance, multiplayer code editor from the creators of Atom and Tree-sitter. ⭐ 82k · Rust · NOASSERTION · updated today

## Coding Agents

- **[goose](https://github.com/aaif-goose/goose)** — an open source, extensible AI agent that goes beyond code suggestions - install, execute, edit, and test with any LLM. ⭐ 44.3k · Rust · Apache-2.0 · updated today

## Desktop Chat Apps

- **[5ire](https://github.com/nanbingxyz/5ire)** — 5ire is a cross-platform desktop AI assistant, MCP client. It compatible with major service providers,  supports local knowledge base and  tools via model context protocol servers . ⭐ 5.2k · TypeScript · NOASSERTION · updated 8w ago
- **[anything-llm](https://github.com/Mintplex-Labs/anything-llm)** — The all-in-one AI productivity accelerator. On device and privacy first with no annoying setup or configuration. ⭐ 60.1k · JavaScript · MIT · updated today
- **[jan](https://github.com/janhq/jan)** — Jan is an open source alternative to ChatGPT that runs 100% offline on your computer. ⭐ 42.5k · TypeScript · NOASSERTION · updated today
- **[tome](https://github.com/runebookai/tome)** — a magical LLM desktop client that makes it easy for *anyone* to use LLMs and MCP. ⭐ 618 · Svelte · Apache-2.0 · updated 6mo ago

## Web Chat Interfaces

- **[LibreChat](https://github.com/danny-avila/LibreChat)** — Enhanced ChatGPT Clone: Features Agents, MCP, DeepSeek, Anthropic, AWS, OpenAI, Responses API, Azure, Groq, o1, GPT-5, Mistral, OpenRouter, Vertex AI, Gemini, Artifacts, AI model switching, message search, Code Interpreter, langchain, DALL-E-3, OpenAPI Actions, Functions, Secure Multi-User Auth, Presets, open-source for self-hosting. Active. ⭐ 36.7k · TypeScript · MIT · updated today
- **[open-webui](https://github.com/open-webui/open-webui)** — User-friendly AI Interface (Supports Ollama, OpenAI API, ...). ⭐ 137.2k · Python · NOASSERTION · updated today

## CLIs & Dev Tools

- **[fast-agent](https://github.com/evalstate/fast-agent)** — Code, Build and Evaluate agents - excellent Model and Skills/MCP/ACP Support. ⭐ 3.8k · Python · Apache-2.0 · updated 1d ago

---

## Contributing

PRs welcome. Each entry should:

- Be an actual MCP **client** (consumes MCP servers, not just MCP-adjacent or "supports MCP" in name only).
- Use the standard line format — generate it with the included pipeline:

```bash
python pipeline/fetch.py https://github.com/your/client
# copy the output line into the right category in README.md (alphabetized)
```

- Land in the right category. If unsure, open an issue and we'll figure it out together.

## License

[CC0](https://creativecommons.org/publicdomain/zero/1.0/) for content. [MIT](../LICENSE) for code.
