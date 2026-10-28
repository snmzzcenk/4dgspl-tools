#!/usr/bin/env python3
"""
4dgspl.at yükleme istemcisi — yapay zekâ ajanları (ve insanlar) için: teslim klasörünü denetler, proje açar, videoları ve
kalibrasyonu yükler, işleme gönderir, bitmesini bekler ve sonucu indirir. Ajan anahtarı gerekir.
4dgspl.at upload client — for AI agents (and people): validates the delivery folder, creates a project, uploads the videos
and calibration, submits, waits for processing and downloads the result. Requires an agent key.

Anahtar / Key: 4dgspl.at → Projelerim → Ajan anahtarları. Ortam değişkeni olarak verin (komut satırına yazmayın):
    export DGSPL_ANAHTAR=4dg_…          (DGSPL_KEY de olur / also accepted)

Kullanım / Usage:
    python3 4dgspl_yukle.py teslim --baslik "Dans eden robot" --gonder --bekle --indir sonuc
    python3 4dgspl_yukle.py teslim --kalite yuksek            # yalnızca yükler; panelden gözden geçirip gönderirsiniz
    python3 4dgspl_yukle.py --projeler
    python3 4dgspl_yukle.py --durum <proje_id>
    python3 4dgspl_yukle.py --sonuc <proje_id> --indir sonuc

Klasör: cam00.mp4, cam01.mp4 … (ya da cam00_aciklama.mp4) ve isteğe bağlı kalibrasyon.zip / calibration.zip.
Aynı klasörde 4dgspl_kontrol.py varsa yüklemeden önce çalıştırılır; hata varsa yükleme yapılmaz (--zorla ile geçilir).
Sınırlar: dosya başına 50 MB; ajanla günde 20 proje açma, 10 gönderme; aynı anda en çok 3 proje kuyrukta/işlenmekte.
Bağımlılık yok (Python 3.8+). MIT lisansı. Ayrıntı: https://4dgspl.at/ajan.html · https://4dgspl.at/en/agents.html
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://ghueniqorletddbvxlmr.supabase.co/functions/v1/ajan"
ETIKET = re.compile(r"^(cam\d{2})(?:_.*)?$", re.I)
KALIB_ADLARI = ("kalibrasyon.zip", "calibration.zip")
DIL = "en"


def m(tr, en):
    return tr if DIL == "tr" else en


class ApiHatasi(Exception):
    pass


def cagir(api, anahtar, islem, **alanlar):
    govde = json.dumps({"islem": islem, **alanlar}).encode()
    istek = urllib.request.Request(api, data=govde, method="POST", headers={
        "Authorization": f"Bearer {anahtar}", "Content-Type": "application/json", "User-Agent": "4dgspl_yukle/1"})
    for deneme in range(4):
        try:
            with urllib.request.urlopen(istek, timeout=120) as y:
                return json.loads(y.read())
        except urllib.error.HTTPError as h:
            try:
                ileti = json.loads(h.read()).get("hata", "")
            except ValueError:
                ileti = ""
            if h.code >= 500 and deneme < 3:
                time.sleep(3 * (deneme + 1))
                continue
            raise ApiHatasi(f"{islem}: HTTP {h.code} — {ileti or h.reason}") from None
        except urllib.error.URLError as h:
            if deneme < 3:
                time.sleep(3 * (deneme + 1))
                continue
            raise ApiHatasi(f"{islem}: {h.reason}") from None


def dosya_yukle(url, yol, tur):
    boyut = yol.stat().st_size
    with open(yol, "rb") as f:
        istek = urllib.request.Request(url, data=f, method="PUT", headers={
            "Content-Type": "video/mp4" if tur == "video" else "application/zip",
            "Content-Length": str(boyut), "x-upsert": "false", "User-Agent": "4dgspl_yukle/1"})
        try:
            with urllib.request.urlopen(istek, timeout=900) as y:
                y.read()
        except urllib.error.HTTPError as h:
            raise ApiHatasi(m(f"{yol.name} yüklenemedi: HTTP {h.code} {h.read()[:200]!r}",
                              f"{yol.name} upload failed: HTTP {h.code} {h.read()[:200]!r}")) from None


def indir(url, hedef):
    hedef.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "4dgspl_yukle/1"}), timeout=300) as y, \
            open(hedef, "wb") as f:
        while True:
            parca = y.read(1 << 20)
            if not parca:
                break
            f.write(parca)


def denetleyici():
    yol = Path(__file__).with_name("4dgspl_kontrol.py")
    if not yol.exists():
        return None
    spec = importlib.util.spec_from_file_location("dgspl_kontrol", yol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def klasoru_oku(klasor):
    videolar = {}
    for v in sorted(klasor.iterdir()):
        e = ETIKET.match(v.stem)
        if v.is_file() and v.suffix.lower() in (".mp4", ".mov") and e:
            videolar[e.group(1).lower()] = v
    kalib = next((klasor / a for a in KALIB_ADLARI if (klasor / a).exists()), None)
    return videolar, kalib


def durum_satiri(d):
    il = d.get("ilerleme") or {}
    parcalar = [d["durum"]]
    if d.get("kuyruk_sirasi"):
        parcalar.append(m(f"kuyrukta {d['kuyruk_sirasi']}. sırada", f"queue position {d['kuyruk_sirasi']}"))
    if il:
        parcalar.append(f"{il['asama']} %{il['yuzde']:.0f} {il.get('mesaj') or ''}".strip())
    if not d.get("isci_cevrimici") and d["durum"] in ("kuyrukta", "isleniyor"):
        parcalar.append(m("işleme sunucusu çevrimdışı", "processing server offline"))
    if d.get("not"):
        parcalar.append(d["not"])
    return " · ".join(parcalar)


def bekle(api, anahtar, pid, dakika):
    son = None
    bitis = time.time() + dakika * 60
    while time.time() < bitis:
        d = cagir(api, anahtar, "durum", proje_id=pid)
        satir = durum_satiri(d)
        if satir != son:
            print(time.strftime("%H:%M:%S"), satir, flush=True)
            son = satir
        if d["durum"] in ("tamamlandi", "hata"):
            return d
        time.sleep(15)
    print(m(f"{dakika} dk içinde bitmedi; sonra --durum {pid} ile bakın.", f"Not finished within {dakika} min; check later with --durum {pid}."))
    return None


def sonucu_indir(api, anahtar, pid, hedef):
    s = cagir(api, anahtar, "sonuc", proje_id=pid)
    hedef = Path(hedef)
    (hedef / "kareler").mkdir(parents=True, exist_ok=True)
    (hedef / "sahne.json").write_text(json.dumps(s["sahne"], ensure_ascii=False, indent=1), encoding="utf-8")
    if s.get("onizleme_mp4"):
        indir(s["onizleme_mp4"], hedef / "onizleme.mp4")
    for i, k in enumerate(s["kareler"], 1):
        indir(k["url"], hedef / "kareler" / k["ad"])
        if i % 10 == 0 or i == len(s["kareler"]):
            print(m(f"  kareler {i}/{len(s['kareler'])}", f"  frames {i}/{len(s['kareler'])}"), flush=True)
    print(m(f"Sonuç indirildi: {hedef} ({len(s['kareler'])} kare, sahne.json, onizleme.mp4). Proje sayfası: {s['proje_sayfasi']}",
            f"Result downloaded: {hedef} ({len(s['kareler'])} frames, sahne.json, onizleme.mp4). Project page: {s['proje_sayfasi']}"))


def main():
    global DIL
    ap = argparse.ArgumentParser(description="4dgspl.at upload client / yükleme istemcisi")
    ap.add_argument("klasor", nargs="?", help="camNN.mp4 + kalibrasyon.zip klasörü / delivery folder")
    ap.add_argument("--baslik", "--title", help="proje adı / project title (varsayılan: klasör adı)")
    ap.add_argument("--kalite", "--quality", choices=["hizli", "yuksek", "en_yuksek"], default="hizli")
    ap.add_argument("--notlar", "--notes")
    ap.add_argument("--gonder", "--submit", action="store_true", help="yükledikten sonra işleme gönder / submit after upload")
    ap.add_argument("--bekle", "--wait", action="store_true", help="bitmesini bekle / wait for processing")
    ap.add_argument("--bekle-dk", "--wait-min", type=int, default=180)
    ap.add_argument("--indir", "--download", metavar="KLASOR", help="tamamlanınca sonucu indir / download result here")
    ap.add_argument("--projeler", "--projects", action="store_true")
    ap.add_argument("--durum", "--status", metavar="PROJE_ID")
    ap.add_argument("--sonuc", "--result", metavar="PROJE_ID")
    ap.add_argument("--zorla", "--force", action="store_true", help="denetleyici hatalarına rağmen yükle / upload despite checker errors")
    ap.add_argument("--api", default=os.environ.get("DGSPL_API", API))
    ap.add_argument("--dil", "--lang", choices=["tr", "en"], default="tr" if os.environ.get("LANG", "").startswith("tr") else "en")
    a = ap.parse_args()
    DIL = a.dil
    anahtar = (os.environ.get("DGSPL_ANAHTAR") or os.environ.get("DGSPL_KEY") or "").strip()
    if not re.fullmatch(r"4dg_[0-9a-f]{40}", anahtar):
        sys.exit(m("DGSPL_ANAHTAR ortam değişkeninde geçerli bir ajan anahtarı yok (4dgspl.at → Projelerim → Ajan anahtarları).",
                   "No valid agent key in the DGSPL_ANAHTAR (or DGSPL_KEY) environment variable (4dgspl.at → Projelerim → Ajan anahtarları)."))
    try:
        if a.projeler:
            for p in cagir(a.api, anahtar, "projeler")["projeler"]:
                print(f"{p['proje_id']}  {p['durum']:<10}  {p['kamera_sayisi']:>2} cam  {p['baslik']}")
            return
        if a.durum:
            d = cagir(a.api, anahtar, "durum", proje_id=a.durum)
            print(durum_satiri(d))
            print(json.dumps(d, ensure_ascii=False, indent=1))
            return
        if a.sonuc:
            sonucu_indir(a.api, anahtar, a.sonuc, a.indir or "sonuc")
            return
        if not a.klasor:
            ap.error(m("klasör gerekli (ya da --projeler / --durum / --sonuc)", "folder required (or --projeler / --durum / --sonuc)"))
        klasor = Path(a.klasor)
        videolar, kalib = klasoru_oku(klasor)
        etiketler = sorted(videolar)
        if not etiketler or etiketler != [f"cam{i:02d}" for i in range(len(etiketler))]:
            sys.exit(m(f"{klasor} içinde cam00'dan başlayan ardışık videolar yok: {etiketler}",
                       f"{klasor} has no consecutive videos starting at cam00: {etiketler}"))
        fps = None
        mod = denetleyici()
        if mod:
            mod.DIL = DIL
            rapor, bilgi = mod.denetle(klasor, kalib)
            for d, t in rapor.satirlar:
                print({"HATA": "✗", "UYARI": "!", "TAMAM": "✓"}[d], t)
            if rapor.hatali and not a.zorla:
                sys.exit(m("Denetleyici hata buldu; düzeltin ya da --zorla kullanın.", "The checker found errors; fix them or use --zorla."))
            fps = next(iter(bilgi.values()), {}).get("fps")
        else:
            print(m("! 4dgspl_kontrol.py bu betiğin yanında yok; denetim atlandı (https://4dgspl.at/araclar/4dgspl_kontrol.py).",
                    "! 4dgspl_kontrol.py is not next to this script; validation skipped (https://4dgspl.at/araclar/4dgspl_kontrol.py)."))
        for v in list(videolar.values()) + ([kalib] if kalib else []):
            if v.stat().st_size > 50 * 1024 * 1024:
                sys.exit(m(f"{v.name} 50 MB'tan büyük; bit hızını düşürün (ör. ffmpeg -crf 23).",
                           f"{v.name} is larger than 50 MB; lower the bitrate (e.g. ffmpeg -crf 23)."))

        p = cagir(a.api, anahtar, "proje_ac", baslik=a.baslik or klasor.resolve().name, kamera_sayisi=len(etiketler),
                  fps=round(fps) if fps else None, kalite=a.kalite, notlar=a.notlar)
        pid = p["proje_id"]
        print(m(f"Proje açıldı: {pid} · {p['proje_sayfasi']}", f"Project created: {pid} · {p['proje_sayfasi']}"))
        isler = [("video", e, videolar[e]) for e in etiketler] + ([("kalibrasyon", None, kalib)] if kalib else [])
        for tur, kamera, yol in isler:
            adres = cagir(a.api, anahtar, "yukleme_adresi", proje_id=pid, tur=tur, kamera=kamera, dosya_adi=yol.name,
                          boyut=yol.stat().st_size)
            dosya_yukle(adres["url"], yol, tur)
            cagir(a.api, anahtar, "dosya_kaydet", proje_id=pid, tur=tur, kamera=kamera, yol=adres["yol"], dosya_adi=yol.name)
            print(f"  ✓ {kamera or m('kalibrasyon', 'calibration')}  {yol.name}  {yol.stat().st_size / 2**20:.1f} MB", flush=True)
        if not a.gonder:
            print(m(f"Yüklendi. Göndermek için: panelden \"İşleme gönder\" ya da bu komutu --gonder ile çalıştırın. {p['proje_sayfasi']}",
                    f"Uploaded. To submit: \"İşleme gönder\" in the dashboard, or re-run with --gonder. {p['proje_sayfasi']}"))
            return
        g = cagir(a.api, anahtar, "gonder", proje_id=pid)
        print(m(f"İşleme gönderildi (kuyrukta {g.get('sira')}. sırada).", f"Submitted (queue position {g.get('sira')})."))
        if a.bekle or a.indir:
            d = bekle(a.api, anahtar, pid, a.bekle_dk)
            if d and d["durum"] == "tamamlandi" and a.indir:
                sonucu_indir(a.api, anahtar, pid, a.indir)
            elif d and d["durum"] == "hata":
                sys.exit(1)
    except ApiHatasi as h:
        sys.exit(f"✗ {h}")


if __name__ == "__main__":
    main()
