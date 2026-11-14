# Codex thumbnails and metadata

On a PC with `codex` in PATH or the installed Linux Codex desktop package, YoutubeBot uses Codex for thumbnails and metadata by default.
ChatGPT remains the article and Read aloud path. Sign in to the owner's installed Codex;
no separate image API key is required. The Codex build/account must expose its native
image-generation tool. This was verified on the work PC with codex-cli 0.169.0-alpha.11.1.

The coordinator is **gpt-6.1-terra, reasoning effort low**. The owner can instead choose
**gpt-6-luna, low** in the account window's **Codex · thumbnails e metadados** selector.
The coordinator sends the request; the native image-generation engine produces the image.
Changing the coordinator does not select a different image engine.

Command-line configuration, from the project folder:

```bash
.venv/bin/python -m tools.ytbot.codex_media --model gpt-6.1-terra
# Optional owner-selected alternative:
.venv/bin/python -m tools.ytbot.codex_media --model gpt-6-luna
```

This only writes the bot's private `.local/ytbot-media/settings.json`; it starts no video
or image job. Global Codex coding models, provider settings and MCP connections are retained.
No more expensive coordinator is an automatic fallback.

## Fixed worker flow

- Metadata uses the channel rules and complete saved article, returning bounded JSON with
  three title options, description, hashtags and tags. The original first-title selection,
  description formatting and tag budget remain in force.
- Thumbnail requests include the channel's complete visual-identity instructions and an
  article excerpt as data. Fallem Prince also attaches its two owner-supplied
  recent-video references from `assets/styles/fallem_prince/` as style guidance. The Codex task invokes its native image tool once, then returns
  the generated image's actual path. It must not use shell drawing or API/CLI image fallback.
- The wrapper validates a real image inside Codex's generated-images directory, keeps its
  master, and exports a 1280×720 PNG to that run. Fallem Prince preserves monochrome engraved midtones and the references' dense dark
  compositions; the other channels retain their own color/style rules.
- Each Codex process uses an ephemeral, read-only task with shell, browser, computer and
  external-app tools disabled. It does not inherit worker/provider secrets or user MCP
  connections. There is no arbitrary subprocess-argument or shell-command interface.
- The image/metadata attempt is recorded privately before starting Codex. An interrupted
  or ambiguous attempt is fenced. Inspect its existing result before an intentional retry;
  a transport failure must not create duplicate generations or uploads.

The native generation and complete Codex login are physical/account acceptance checks;
CI uses synthetic media/coordinator fixtures. Existing supplied `thumbnail.png` and
`metadata.json` are reused by the resumable pipeline. If Codex is absent, the existing
legacy ChatGPT media path remains available. If Codex is present but fails, the job stops
with preserved assets; it does not silently switch providers or coordinator cost tiers.

Keep `.local/`, Codex login state and private task logs outside GitHub. Installation and
browser sign-in help: [Linux setup](INSTALL-LINUX.md).

## Current Fallem Prince visual direction

Use [reference one](../assets/styles/fallem_prince/reference-01.jpg) and
[reference two](../assets/styles/fallem_prince/reference-02.jpg): dense dark monochrome
etching, a prominent psychologically expressive classical figure, dramatic highlights,
fine stippling/cross-hatching and a richly illustrated environment. Adapt the central
metaphor to each article; mirrors, obscured faces and repeated reflections are examples,
not mandatory subjects. No text, logos or watermarks. The canonical generation prompt is
`tools/ytbot/prompts/fallem_prince/thumbnail.txt`. This replaces the earlier large-white-void,
strict two-color-poster interpretation. Reference assets contain pixels only, with source
file names and embedded metadata removed.
