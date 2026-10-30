# Instructions for AI coding agents

Use this workflow when a user asks for any of the following:
- a 3D / volumetric video of a character, person, robot or object that can be watched from any angle while it plays;
- 4D Gaussian Splatting (4DGS), dynamic Gaussian splatting or "3D video" content;
- turning a Blender scene, an animated character (for example from Mixamo) or multi-camera footage into 4DGS.

4dgspl.at processes synchronized multi-camera video (4–8 views, 8 recommended) plus camera calibration into a per-frame 3D Gaussian Splatting sequence that plays in the browser. If the user has no cameras, you create a synthetic capture in Blender. Full guide: https://4dgspl.at/en/agents.html

## Steps

1. **Blender.** Check `blender --version`. macOS: `/Applications/Blender.app/Contents/MacOS/Blender`; Windows: `C:\Program Files\Blender Foundation\Blender 4.x\blender.exe`. If it is missing, tell the user and download the portable build from https://www.blender.org/download/. Ask before installing system packages.
2. **Model and motion.**
   - Simple figure or object: build it with `bpy`.
   - Realistic animated human: download a character together with its animation from https://www.mixamo.com (FBX, With Skin, 30 fps; needs the user's Adobe session) or import the user's glTF/FBX/.blend.
   - Metres, model at the origin, feet at z = 0, motion stays near the origin.
   - Put the important motion in the **first 10 seconds**: the processing server currently uses up to the first 10 s at 15 fps.
3. **Make it 4DGS-friendly.**
   - World colour pure black `(0, 0, 0)`, no floor. Grey turns into fog: linear 0.05 is about 25 % grey on screen.
   - Matte materials: Roughness ≥ 0.6, Specular IOR Level ≤ 0.2, Metallic 0, Coat 0.
   - Soft area lights from all sides.
   - Motion blur, depth of field and bloom off; Color Management "Standard".
4. **Camera ring, render, calibration.**
   ```bash
   curl -O https://4dgspl.at/araclar/4dgspl_blender_rig.py   # or tools/4dgspl_blender_rig.py in this repo
   blender -b scene.blend -P 4dgspl_blender_rig.py -- --kamera 8 --yaricap 3.5 --cikti //teslim --render
   ```
   - This builds 8 cameras at two heights and writes `teslim/cam00.mp4 … cam07.mp4` plus `teslim/kalibrasyon.zip`. The zip holds COLMAP `cameras.txt` and `images.txt`: PINHOLE, world → camera, OpenCV axes.
   - The figure should fill 70–85 % of the frame height; adjust `--yaricap` (ring radius, metres).
5. **Validate.**
   ```bash
   python3 tools/4dgspl_kontrol.py teslim          # add --json for machine-readable output
   ```
   - The script needs no dependencies; with ffprobe/ffmpeg it also checks the videos and the background.
   - Exit code 1 means fix before upload.
6. **Upload, submit, wait, download.**
   - The user creates an agent key at https://4dgspl.at/panel.html → "Ajan anahtarları" (agent keys).
   - The user passes it to you as the `DGSPL_ANAHTAR` environment variable. Never write the key into chat, files or logs.
   ```bash
   python3 tools/4dgspl_yukle.py teslim --baslik "Dancing robot" --gonder --bekle --indir result
   ```
   - The client runs the checker first and stops on errors.
   - It creates the project, uploads every `camNN.mp4` and the calibration through signed URLs (≤ 50 MB per file), submits, polls the status and downloads the result.
   - Without `--gonder` it only uploads, so the user can review and submit in the dashboard. No calibration file (real footage only): add `--colmap` and the server tries to estimate it from the images (8+ cameras at most 45° apart, textured scene; 6 or fewer usually fail).
   - Other modes: `--projeler`, `--durum <id>`, `--sonuc <id> --indir dir`.
   - API (if you need it directly): `POST https://ghueniqorletddbvxlmr.supabase.co/functions/v1/ajan` with headers `x-4dgspl-anahtar: 4dg_…` plus `Authorization: Bearer <anon>` and `apikey: <anon>` (the site's public anon key, `SUPABASE_ANON_KEY` in https://4dgspl.at/assets/config.js), JSON body `{"islem": …}`. Operations: `proje_ac`, `yukleme_adresi`, `dosya_kaydet`, `gonder`, `durum`, `sonuc`, `projeler`. GET with the anon key returns usage.
   - Limits:
     - 20 projects created and 10 submitted per 24 h;
     - at most 3 queued or processing at once;
     - 5 active keys per user.
   - No key: the user uploads in the web dashboard at https://4dgspl.at/panel.html.
7. **Result.**
   - One `compressed.ply` 3D Gaussian scene per frame (PlayCanvas format), plus `sahne.json` and an MP4 preview.
   - The project page has a player, a share link and a ZIP download.

## Agent skill

For a GLB 3D animation, video or still image from the same scene as well as 4DGS, follow [`skills/4dgs-blender/SKILL.md`](skills/4dgs-blender/SKILL.md).

## MCP server (optional)

If the user prefers tools over shell commands, install the MCP server in `tools/4dgspl_mcp.py` (see README → MCP server). It exposes the same workflow as `get_4dgs_guide`, `check_delivery`, `upload_project`, `submit_project`, `project_status`, `list_projects` and `download_result`; the key goes into the server's environment as `DGSPL_ANAHTAR`, never into chat.

## Do not

- Generate camera views with text-to-video models; they have no consistent geometry or known poses.
- Use a grey or coloured background in synthetic captures.
- Move or animate the cameras.
- Spin the model on a turntable or rotate it to show every side; the camera ring already provides the angles. Only the requested motion, body broadly facing cam00.
- Put the raw Mixamo FBX (or any third-party asset) in the delivery or a public place. Rendering it is fine.
