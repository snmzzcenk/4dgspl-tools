# 4dgspl-tools

Open tools for making **4D Gaussian Splatting (4DGS)** content with [4dgspl.at](https://4dgspl.at/en/). Turn a 3D model, an animated character (for example from Mixamo) or a Blender scene into a synchronized multi-camera render with exact COLMAP calibration, validate it, and convert it to a 4DGS sequence that plays in the browser.

Built to be used by **AI coding agents** (Claude Code, Codex, …) as well as people. Agents: start with [AGENTS.md](AGENTS.md).

| Tool | What it does |
|---|---|
| [`tools/4dgspl_blender_rig.py`](tools/4dgspl_blender_rig.py) | Blender: builds a 4–16 camera ring (8 recommended, two heights) around the scene, renders `cam00.mp4 …` from every camera and writes COLMAP `cameras.txt` + `images.txt` (`kalibrasyon.zip`). Pure black world by default. |
| [`tools/4dgspl_yukle.py`](tools/4dgspl_yukle.py) | Dependency-free upload client for an agent key (`DGSPL_ANAHTAR`). It validates, creates a project, uploads, submits, waits and downloads the per-frame 3DGS result: `--gonder --bekle --indir result`. |
| [`tools/4dgspl_mcp.py`](tools/4dgspl_mcp.py) | Dependency-free **MCP server** (stdio). Claude Code, Codex, Cursor or Claude Desktop get 4dgspl.at as tools: `get_4dgs_guide`, `check_delivery`, `upload_project`, `submit_project`, `project_status`, `list_projects`, `download_result`. |
| [`tools/4dgspl_kontrol.py`](tools/4dgspl_kontrol.py) | Dependency-free pre-upload checker. It checks video names, resolution, fps and frame count, the calibration format and pixel units, whether the cameras look at a common centre, height variety and ring gaps, and a black background. `--json` output; exit code 1 on errors. |

## Quick start

```bash
# 1. Camera ring + render + calibration (Blender 4.x)
blender -b scene.blend -P tools/4dgspl_blender_rig.py -- --kamera 8 --yaricap 3.5 --cikti //teslim --render

# 2. Validate
python3 tools/4dgspl_kontrol.py teslim

# 3. Upload, process and download with your agent key (4dgspl.at → Projelerim → Ajan anahtarları)
export DGSPL_ANAHTAR=4dg_…
python3 tools/4dgspl_yukle.py teslim --gonder --bekle --indir result
```

Rules that matter most:
- **Background:** pure black world (0, 0, 0).
- **Materials:** matte.
- **Cameras:** at least 6, 8 recommended; they never move.
- **Timing:** the key motion within the first 10 seconds.
- **Framing:** the subject fills 70–85 % of the frame height.

Details: [agent guide](https://4dgspl.at/en/agents.html) · [capture guide](https://4dgspl.at/en/capture.html) · [examples](https://4dgspl.at/en/examples.html) · [llms.txt](https://4dgspl.at/llms.txt)

## Agent skill

[`skills/4dgs-blender/SKILL.md`](skills/4dgs-blender/SKILL.md) packages the whole workflow as an agent skill: GLB 3D animation, video, still image and 4DGS videos from one Blender scene. To install it in Claude Code, copy the folder into `~/.claude/skills/`. Agents that read `SKILL.md` from their own skills folder can use the same files.

## MCP server

```bash
mkdir -p ~/.4dgspl && cd ~/.4dgspl && curl -O https://4dgspl.at/araclar/4dgspl_mcp.py \
  -O https://4dgspl.at/araclar/4dgspl_yukle.py -O https://4dgspl.at/araclar/4dgspl_kontrol.py
claude mcp add 4dgspl --env DGSPL_ANAHTAR=4dg_… -- python3 ~/.4dgspl/4dgspl_mcp.py   # Claude Code
codex mcp add 4dgspl --env DGSPL_ANAHTAR=4dg_… -- python3 ~/.4dgspl/4dgspl_mcp.py    # Codex
```

- Claude Desktop: install `4dgspl.mcpb` from the [latest release](https://github.com/snmzzcenk/4dgspl-tools/releases/latest) and enter the key in its settings.
- Other clients: command `python3`, argument the path to `4dgspl_mcp.py`, environment `DGSPL_ANAHTAR`.
- Without a key, `get_4dgs_guide` and `check_delivery` still work.
- Listed in the MCP Registry as `io.github.snmzzcenk/4dgspl` ([server.json](server.json)). Build the bundle with `python3 mcpb/build.py`.

<!-- mcp-name: io.github.snmzzcenk/4dgspl -->

## Output

4dgspl.at reconstructs every frame as a 3D Gaussian Splatting scene ([gsplat](https://github.com/nerfstudio-project/gsplat)). The output is:
- a `compressed.ply` sequence in PlayCanvas format;
- `sahne.json` with the frame count, fps, start camera and metrics;
- an MP4 preview.

Play the sequence in the browser with PlayCanvas, or open a single frame in SuperSplat.

## Türkçe

4dgspl.at ile 4D Gaussian Splatting içeriği üretmek için açık araçlar. Blender rig betiği 4–16 kameralı halkayı kurar, her kameradan render alır ve COLMAP kalibrasyonunu yazar. Denetleyici, teslimi yüklemeden önce motorun kurallarına göre kontrol eder (`--dil tr`). Yapay zekâ ajanları için iş akışı: https://4dgspl.at/ajan.html

The tools in this repository are copies of https://4dgspl.at/araclar/; the site is the source and they are kept in sync. MIT license.
