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
   - Put the important motion in the **first 4 seconds**: the processing server currently uses the first 4 s at 15 fps.
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
6. **Upload.**
   - Uploads currently go through the web dashboard at https://4dgspl.at/panel.html.
   - Create a new project with the camera count, put `camNN.mp4` into the camera slots in order, upload `kalibrasyon.zip` as calibration and submit.
   - If you have a browser tool and the user is signed in, you may do this yourself. Otherwise give the user these steps and the path of the delivery folder.
   - A direct upload key for agents is in preparation.
7. **Result.**
   - One `compressed.ply` 3D Gaussian scene per frame (PlayCanvas format), plus `sahne.json` and an MP4 preview.
   - The project page has a player, a share link and a ZIP download.

## Do not

- Generate camera views with text-to-video models; they have no consistent geometry or known poses.
- Use a grey or coloured background in synthetic captures.
- Move or animate the cameras.
- Put the raw Mixamo FBX (or any third-party asset) in the delivery or a public place. Rendering it is fine.
