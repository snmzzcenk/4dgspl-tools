#!/usr/bin/env python3
"""
4dgspl.at MCP sunucusu — Claude Code, Codex, Cursor ve diğer MCP istemcileri 4dgspl.at'i araç olarak kullanır: teslim
klasörünü denetler, proje açıp yükler, işleme gönderir, durumu izler ve sonucu indirir.
4dgspl.at MCP server — lets Claude Code, Codex, Cursor and other MCP clients use 4dgspl.at as a tool: validate a
delivery folder, create a project and upload it, submit it for processing, follow its status and download the result.

Kurulum / Install (aynı klasörde 4dgspl_yukle.py ve 4dgspl_kontrol.py gerekir / needs the two scripts next to it):
    mkdir -p ~/.4dgspl && cd ~/.4dgspl && curl -O https://4dgspl.at/araclar/4dgspl_mcp.py \\
      -O https://4dgspl.at/araclar/4dgspl_yukle.py -O https://4dgspl.at/araclar/4dgspl_kontrol.py
    claude mcp add 4dgspl --env DGSPL_ANAHTAR=4dg_… -- python3 ~/.4dgspl/4dgspl_mcp.py
    codex mcp add 4dgspl --env DGSPL_ANAHTAR=4dg_… -- python3 ~/.4dgspl/4dgspl_mcp.py

Anahtar / Key: 4dgspl.at → Projelerim → Ajan anahtarları. Anahtarsız da rehber ve denetim araçları çalışır.
Without a key the guide and checker tools still work.
Taşıma: stdio, satır başına bir JSON-RPC 2.0 iletisi (Model Context Protocol). Bağımlılık yok (Python 3.8+). MIT lisansı.
"""
import contextlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

SURUM = "0.1.0"
PROTOKOLLER = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
BURASI = Path(__file__).resolve().parent


def _yukle_modul(ad, dosya):
    yol = BURASI / dosya
    if not yol.exists():
        return None
    spec = importlib.util.spec_from_file_location(ad, yol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


YUKLE = _yukle_modul("dgspl_yukle", "4dgspl_yukle.py")
KONTROL = _yukle_modul("dgspl_kontrol", "4dgspl_kontrol.py")
if YUKLE:
    YUKLE.DIL = "en"
if KONTROL:
    KONTROL.DIL = "en"

REHBER = """4dgspl.at turns synchronized multi-camera video into 4D Gaussian Splatting (4DGS): a 3D video that plays in the
browser and can be watched from any angle. Docs: https://4dgspl.at/en/agents.html

Input (one folder): cam00.mp4, cam01.mp4 … (4–16 cameras, 8 recommended, same resolution/fps/frame count, synchronized,
cameras never move) + kalibrasyon.zip with COLMAP cameras.txt (PINHOLE, pixels) and images.txt (world→camera, OpenCV),
image names cam00.png … Pure black background (0,0,0) for synthetic scenes; matte materials; subject fills 70–85 % of the
frame height. The server currently processes the first 4 seconds at 15 fps (60 frames). ≤ 50 MB per file.

No cameras? Build the scene in Blender and let the rig script make the capture:
  curl -O https://4dgspl.at/araclar/4dgspl_blender_rig.py
  blender -b scene.blend -P 4dgspl_blender_rig.py -- --kamera 8 --yaricap 3.5 --cikti //teslim --render
(8-camera ring at two heights, camNN.mp4 per camera, exact COLMAP calibration; Mixamo FBX characters import directly.)
Text-to-video models are NOT suitable (no consistent geometry or known camera poses). A single video is not enough.

Tools: check_delivery(folder) → upload_project(folder, submit=true) → project_status(project_id) until "tamamlandi"
(done) or "hata" (error) → download_result(project_id, dest). Status values: taslak (draft), kuyrukta (queued),
isleniyor (processing), tamamlandi (done), hata (error).

Pricing: every new account gets 5 free jobs (≤ 10 s each, quality "hizli" = Fast). Then credits: 1 credit = 1 second
at hizli, yuksek (High) ×3, en_yuksek (Highest) ×8. Submitting without enough credit returns HTTP 402.
Agent key: the user creates it at https://4dgspl.at/panel.html → "Ajan anahtarları" and sets DGSPL_ANAHTAR in this
server's environment. Never ask the user to paste the key into chat.
Output: browser player + public share link + embed code on the project page; per-frame 3DGS files (compressed.ply),
sahne.json and an MP4 preview in download_result."""

ARACLAR = [
    {"name": "get_4dgs_guide",
     "description": "Explain how 4dgspl.at converts multi-camera video or a Blender render into 4D Gaussian Splatting (4DGS / "
                    "volumetric video): input rules, Blender rig command for users without cameras, pricing, workflow. Call this "
                    "first when a user wants a 3D/volumetric video that can be watched from any angle. No key needed.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "check_delivery",
     "description": "Validate a local delivery folder before upload: camNN.mp4 names, resolution, fps, frame count, calibration "
                    "zip (COLMAP), camera layout and black background. No key needed.",
     "inputSchema": {"type": "object", "required": ["folder"],
                     "properties": {"folder": {"type": "string", "description": "Path to the folder with cam00.mp4 … and kalibrasyon.zip"}}}},
    {"name": "upload_project",
     "description": "Create a 4dgspl.at project from a local delivery folder and upload all camera videos and the calibration. "
                    "With submit=true it is queued for processing right away (uses a free job or credits). Requires DGSPL_ANAHTAR.",
     "inputSchema": {"type": "object", "required": ["folder"],
                     "properties": {"folder": {"type": "string"},
                                    "title": {"type": "string", "description": "Project title (default: folder name)"},
                                    "quality": {"type": "string", "enum": ["hizli", "yuksek", "en_yuksek"], "default": "hizli",
                                                "description": "hizli = Fast (free jobs use this), yuksek = High ×3, en_yuksek = Highest ×8"},
                                    "notes": {"type": "string"},
                                    "submit": {"type": "boolean", "default": False},
                                    "force": {"type": "boolean", "default": False, "description": "Upload even if the checker reports errors"}}}},
    {"name": "submit_project",
     "description": "Submit an uploaded draft project for processing. Requires DGSPL_ANAHTAR.",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "string"}}}},
    {"name": "project_status",
     "description": "Status of a project: queue position, processing stage and progress, cost estimate for drafts. Poll every "
                    "30–60 s while queued or processing. Requires DGSPL_ANAHTAR.",
     "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "string"}}}},
    {"name": "list_projects",
     "description": "List the user's 4dgspl.at projects with id, status and camera count. Requires DGSPL_ANAHTAR.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "download_result",
     "description": "Download a finished project's per-frame 3D Gaussian Splatting files (compressed.ply), sahne.json and MP4 "
                    "preview into a local folder; also returns the project page with the browser player. Requires DGSPL_ANAHTAR.",
     "inputSchema": {"type": "object", "required": ["project_id"],
                     "properties": {"project_id": {"type": "string"},
                                    "dest": {"type": "string", "default": "4dgs_result", "description": "Local folder"}}}},
]


class AracHatasi(Exception):
    pass


def _anahtar():
    a = (os.environ.get("DGSPL_ANAHTAR") or os.environ.get("DGSPL_KEY") or "").strip()
    if not re.fullmatch(r"4dg_[0-9a-f]{40}", a):
        raise AracHatasi("No valid agent key. Ask the user to create one at https://4dgspl.at/panel.html → \"Ajan anahtarları\" "
                         "(free account: email or Google sign-in) and add it to this MCP server's environment as DGSPL_ANAHTAR, "
                         "e.g. claude mcp add 4dgspl --env DGSPL_ANAHTAR=4dg_… -- python3 4dgspl_mcp.py. Never paste the key into chat.")
    return a


def _modul(mod, dosya):
    if not mod:
        raise AracHatasi(f"{dosya} must be next to 4dgspl_mcp.py: curl -O https://4dgspl.at/araclar/{dosya}")
    return mod


def _api():
    return os.environ.get("DGSPL_API", _modul(YUKLE, "4dgspl_yukle.py").API)


def _cagir(islem, **alanlar):
    return YUKLE.cagir(_api(), _anahtar(), islem, **alanlar)


def arac_calistir(ad, g):
    """Aracı çalıştırır; (metin, hata_mi) döndürür. Betiklerin ekrana yazdıkları stdout'u (protokol kanalı) bozmasın diye
    toplanıp yanıta eklenir."""
    gunluk = []

    class _Toplayici:
        def write(self, s):
            gunluk.append(s)

        def flush(self):
            pass

    try:
        with contextlib.redirect_stdout(_Toplayici()):
            sonuc = _arac(ad, g)
        ek = "".join(gunluk).strip()
        return (f"{ek}\n\n{sonuc}" if ek else sonuc), False
    except AracHatasi as h:
        return str(h), True
    except Exception as h:  # ApiHatasi ve beklenmeyenler
        ek = "".join(gunluk).strip()
        return (f"{ek}\n\n" if ek else "") + f"Error: {h}", True


def _arac(ad, g):
    if ad == "get_4dgs_guide":
        return REHBER
    if ad == "check_delivery":
        klasor = Path(os.path.expanduser(g["folder"]))
        if not klasor.is_dir():
            raise AracHatasi(f"{klasor} is not a folder")
        _modul(YUKLE, "4dgspl_yukle.py")
        _, kalib = YUKLE.klasoru_oku(klasor)
        rapor, _ = _modul(KONTROL, "4dgspl_kontrol.py").denetle(klasor, kalib)
        isaret = {"HATA": "ERROR", "UYARI": "WARNING", "TAMAM": "OK"}
        satirlar = [f"{isaret[d]}: {t}" for d, t in rapor.satirlar]
        return ("Result: errors found, fix them before uploading." if rapor.hatali else "Result: ready to upload.") + "\n" + "\n".join(satirlar)
    if ad == "upload_project":
        _modul(YUKLE, "4dgspl_yukle.py")
        p = YUKLE.klasoru_yukle(_api(), _anahtar(), os.path.expanduser(g["folder"]), g.get("title"), g.get("quality") or "hizli",
                                g.get("notes"), bool(g.get("force")))
        metin = f"Project created and uploaded: project_id={p['proje_id']}\nProject page: {p['proje_sayfasi']}"
        if g.get("submit"):
            metin += "\n" + YUKLE.gonder_metni(_cagir("gonder", proje_id=p["proje_id"]))
            metin += "\nNext: call project_status every 30–60 s until the status is tamamlandi (done), then download_result."
        else:
            metin += "\nNot submitted yet: call submit_project, or the user can press \"İşleme gönder\" on the project page."
        return metin
    if ad == "submit_project":
        _modul(YUKLE, "4dgspl_yukle.py")
        return YUKLE.gonder_metni(_cagir("gonder", proje_id=g["project_id"]))
    if ad == "project_status":
        _modul(YUKLE, "4dgspl_yukle.py")
        d = _cagir("durum", proje_id=g["project_id"])
        return YUKLE.durum_satiri(d) + "\n" + json.dumps(d, ensure_ascii=False, indent=1)
    if ad == "list_projects":
        _modul(YUKLE, "4dgspl_yukle.py")
        pr = _cagir("projeler")["projeler"]
        if not pr:
            return "No projects yet."
        return "\n".join(f"{p['proje_id']}  {p['durum']}  {p['kamera_sayisi']} cameras  {p['baslik']}" for p in pr)
    if ad == "download_result":
        _modul(YUKLE, "4dgspl_yukle.py")
        hedef = os.path.expanduser(g.get("dest") or "4dgs_result")
        YUKLE.sonucu_indir(_api(), _anahtar(), g["project_id"], hedef)
        return f"Files are in {Path(hedef).resolve()}"
    raise AracHatasi(f"Unknown tool: {ad}")


def isle(ileti):
    """Bir JSON-RPC iletisini işler; yanıt (dict) ya da bildirimse None döndürür."""
    yontem, kimlik, p = ileti.get("method"), ileti.get("id"), ileti.get("params") or {}
    if kimlik is None:   # bildirim (notifications/initialized, notifications/cancelled …)
        return None
    if yontem == "initialize":
        istenen = p.get("protocolVersion")
        sonuc = {"protocolVersion": istenen if istenen in PROTOKOLLER else PROTOKOLLER[0],
                 "capabilities": {"tools": {"listChanged": False}},
                 "serverInfo": {"name": "4dgspl", "title": "4dgspl.at — 4D Gaussian Splatting", "version": SURUM},
                 "instructions": "Use get_4dgs_guide first. 4dgspl.at converts synchronized multi-camera video (or a Blender "
                                 "multi-camera render) into 4D Gaussian Splatting that plays in the browser."}
    elif yontem == "ping":
        sonuc = {}
    elif yontem == "tools/list":
        sonuc = {"tools": ARACLAR}
    elif yontem == "tools/call":
        metin, hata = arac_calistir(p.get("name"), p.get("arguments") or {})
        sonuc = {"content": [{"type": "text", "text": metin}], "isError": hata}
    elif yontem in ("resources/list", "prompts/list"):
        sonuc = {yontem.split("/")[0]: []}
    else:
        return {"jsonrpc": "2.0", "id": kimlik, "error": {"code": -32601, "message": f"Method not found: {yontem}"}}
    return {"jsonrpc": "2.0", "id": kimlik, "result": sonuc}


def main():
    for satir in sys.stdin:
        satir = satir.strip()
        if not satir:
            continue
        try:
            ileti = json.loads(satir)
        except ValueError:
            yanit = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            yanit = [y for y in map(isle, ileti) if y] if isinstance(ileti, list) else isle(ileti)
        if yanit:
            sys.stdout.write(json.dumps(yanit, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
