# awesome-collections

A monorepo of curated `awesome-X` lists focused on under-served niches in the AI / developer-tooling space.

## Lists

- [awesome-mcp-clients](./awesome-mcp-clients) — clients that speak the [Model Context Protocol](https://modelcontextprotocol.io)

More lists land here as gaps are found.

## Why a monorepo?

Each sub-list is a self-contained directory with its own `README.md` and a tiny `pipeline/fetch.py` helper that turns a GitHub URL into a clean, formatted markdown entry. Clone the parent, `cd` into any sub-list, and you've got everything.

## Contributing

1. Pick the relevant sub-list.
2. Run its `pipeline/fetch.py <github-url>` to generate a properly formatted entry line.
3. Drop the line under the right category in that sub-list's `README.md` (alphabetized).
4. Open a PR.

## License

MIT for code, [CC0](https://creativecommons.org/publicdomain/zero/1.0/) for the curated content.
