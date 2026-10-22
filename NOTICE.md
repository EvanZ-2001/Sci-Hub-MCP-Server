# Attribution and license provenance

This repository is a fork of [JackKuo666/Sci-Hub-MCP-Server](https://github.com/JackKuo666/Sci-Hub-MCP-Server), based on commit `aacb5c2aca96c225cedcbe31a519736e96fdb90e`. The original Git history and authorship are retained.

The upstream [README at that commit](https://github.com/JackKuo666/Sci-Hub-MCP-Server/blob/aacb5c2aca96c225cedcbe31a519736e96fdb90e/README.md#-license) states: “This project is licensed under the MIT License.” That snapshot does not contain a standalone license file. This fork adds the standard MIT text based on that declaration; it is not an upstream-supplied license file or a claim that the fork maintainer authored the original project.

The repair references these upstream contributions:

- [PR #10 by xuio](https://github.com/JackKuo666/Sci-Hub-MCP-Server/pull/10), commit `6d2e61ab0967f646a94a86b976660edc37fa8351`: mirror configuration, candidate PDF validation and preserving metadata when PDF lookup fails.
- [PR #15 by mikhailnov](https://github.com/JackKuo666/Sci-Hub-MCP-Server/pull/15), commit `879a372d650cc908f61ae3e18bcc757c83fed1a8`: object/embed/iframe parsing and resolving relative PDF URLs.
- [PR #16 by HyperD1ve](https://github.com/JackKuo666/Sci-Hub-MCP-Server/pull/16): independent page parsing and metadata handling approach. This fork retains MCP SDK 1.x rather than adopting that PR wholesale.

These PRs were used as references and were not merged unchanged. The fork combines those ideas with TLS verification, stderr logging, request budgets, title disambiguation, interrupted-download protection and regression tests.

Third-party Python dependencies retain their own licenses. This project's MIT license covers its software and does not grant rights to papers available through external websites.
