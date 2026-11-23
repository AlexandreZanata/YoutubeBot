# Video editing skills for the agent

`skills/ffmpeg-skill/` vendors the MIT-licensed
[ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) agent skill (42 typed
FFmpeg tools, a machine-readable contract and an optional MCP server). It gives the
coding agent a local video editor: probe, cut, join, reframe, speed, captions,
overlays, silence removal, loudness, HDR to SDR, platform exports and delivery
checks, all with `ffmpeg`/`ffprobe` and Python's standard library. No cloud, no API
keys, no footage uploaded.

## Layout

```
skills/ffmpeg-skill/
  SKILL.md        agent instructions (workflow: probe, edit, verify)
  scripts/        one script per tool (probe.py, cut.py, fit.py, ...)
  references/     flags, workflow, platform specs
  templates/      platform render templates
  mcp/            MCP server entry point
  bin/            helper launchers
  LICENSE         upstream MIT license
```

## Agent access

The skill follows the Agent Skills convention (`SKILL.md` with `name` and
`description` frontmatter). Link the vendored copy into the agent's skill
directory once per workstation:

```bash
ln -sfn "$PWD/skills/ffmpeg-skill" ~/.config/opencode/skills/ffmpeg-skill
```

Codex and Claude Code read the same `SKILL.md`; point them at the same folder.

## Use

```bash
python3 skills/ffmpeg-skill/scripts/ffprobe.py input.mp4
python3 skills/ffmpeg-skill/scripts/cut.py input.mp4 --segments 0:45-1:20 --accurate
python3 skills/ffmpeg-skill/scripts/fit.py in.mp4 --aspect 9:16 --fit crop
python3 skills/ffmpeg-skill/scripts/export.py in.mp4 --preset reels
python3 skills/ffmpeg-skill/scripts/check.py out.mp4 --platform reels
```

Every writing tool verifies what it wrote, and `--json` returns a structured
report. The full tool list and contracts are in `references/` and `SKILL.md`.

## Update

The vendored copy is pinned to the upstream revision recorded in
`skills/ffmpeg-skill/package.json`. To refresh, copy `SKILL.md`, `scripts/`,
`references/`, `templates/`, `mcp/`, `bin/`, `package.json` and `LICENSE` from a
newer upstream checkout; never copy `demos/`, `site/` or media fixtures.

The skill is optional for the bot itself: `tools/ytbot` keeps its own render and
upload paths unchanged. It exists so the agent can edit footage with verified
FFmpeg operations when a task asks for it.
