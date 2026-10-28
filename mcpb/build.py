#!/usr/bin/env python3
"""Build dist/4dgspl.mcpb (MCP Bundle) from manifest.json and the tools, and print its SHA-256 for server.json."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
out = ROOT / "dist" / "4dgspl.mcpb"
out.parent.mkdir(exist_ok=True)
FILES = [("mcpb/manifest.json", "manifest.json"), ("LICENSE", "LICENSE")] + [
    (f"tools/{f}", f"server/{f}") for f in ("4dgspl_mcp.py", "4dgspl_yukle.py", "4dgspl_kontrol.py")]
# Fixed timestamps and permissions: the same sources always give the same bytes, so fileSha256 in server.json can be
# checked by rebuilding.
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for src, name in FILES:
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, (ROOT / src).read_bytes())
print(out, manifest["version"], hashlib.sha256(out.read_bytes()).hexdigest())
