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
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(ROOT / "mcpb" / "manifest.json", "manifest.json")
    z.write(ROOT / "LICENSE", "LICENSE")
    for f in ("4dgspl_mcp.py", "4dgspl_yukle.py", "4dgspl_kontrol.py"):
        z.write(ROOT / "tools" / f, f"server/{f}")
print(out, manifest["version"], hashlib.sha256(out.read_bytes()).hexdigest())
