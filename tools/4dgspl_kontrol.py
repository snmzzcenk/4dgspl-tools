#!/usr/bin/env python3
"""
4dgspl.at teslim denetleyicisi — çok kameralı bir çekimi yüklemeden önce motorun kurallarına göre kontrol eder.
4dgspl.at delivery checker — validates a multi-camera capture against the engine's rules before upload.

Kullanım / Usage:
    python3 4dgspl_kontrol.py teslim/                 # klasörde camNN.mp4 + kalibrasyon.zip (ya da calibration.zip)
    python3 4dgspl_kontrol.py teslim/ --kalibrasyon kalib.zip --json
    python3 4dgspl_kontrol.py teslim/ --dil tr        # çıktı dili (varsayılan: LANG tr ise tr, değilse en)

Denetlenenler / Checks:
  - Videolar: cam00.mp4, cam01.mp4 … (ya da cam00_aciklama.mp4); en az 4, önerilen 8; hepsi aynı çözünürlük,
    fps ve kare sayısında (ffprobe varsa).
  - Kalibrasyon: .zip içinde COLMAP cameras.txt + images.txt (PINHOLE / SIMPLE_PINHOLE) ya da 4dgs-cameras cameras.json;
    görüntü adları video adlarıyla eşleşir; odak uzaklığı piksel cinsinden (yatay görüş 5–150°); çözünürlük videolarla
    aynı; kameralar ortak bir merkeze bakar; 6+ kamerada yükseklik çeşitliliği ve halkada büyük boşluk uyarısı.
  - Fon: her videonun ilk karesinin köşeleri siyah olmalı (ffmpeg varsa). Gri fon motorda sis olur.

Çıkış kodu 0: hata yok (uyarı olabilir), 1: yüklemeden önce düzeltilmesi gereken hata.
Bağımlılık yok (Python 3.8+ standart kütüphanesi); ffprobe/ffmpeg varsa video denetimleri de yapılır. MIT lisansı.
Ayrıntı: https://4dgspl.at/ajan.html · https://4dgspl.at/cekim.html
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DIL = "en"
ETIKET = re.compile(r"^(cam\d{2})(?:_.*)?$", re.I)


def m(tr, en):
    return tr if DIL == "tr" else en


class Rapor:
    def __init__(self):
        self.satirlar = []   # (düzey, metin): HATA | UYARI | TAMAM

    def ekle(self, duzey, metin):
        self.satirlar.append((duzey, metin))

    def hata(self, tr, en):
        self.ekle("HATA", m(tr, en))

    def uyari(self, tr, en):
        self.ekle("UYARI", m(tr, en))

    def tamam(self, tr, en):
        self.ekle("TAMAM", m(tr, en))

    @property
    def hatali(self):
        return any(d == "HATA" for d, _ in self.satirlar)


# ---------------------------------------------------------------------------
# Küçük doğrusal cebir (numpy'sız)
# ---------------------------------------------------------------------------

def quat_matris(qw, qx, qy, qz):
    n = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz) or 1.0
    qw, qx, qy, qz = qw / n, qx / n, qy / n, qz / n
    return [[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]]


def nokta(a, b):
    return sum(x * y for x, y in zip(a, b))


def fark(a, b):
    return [x - y for x, y in zip(a, b)]


def boy(a):
    return math.sqrt(nokta(a, a))


def capraz(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def coz3(A, b):
    """3×3 doğrusal sistem (Cramer)."""
    def det(M):
        return (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
                + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]))
    d = det(A)
    if abs(d) < 1e-12:
        return None
    return [det([[b[r] if c == i else A[r][c] for c in range(3)] for r in range(3)]) / d for i in range(3)]


# ---------------------------------------------------------------------------
# Kalibrasyon (motorla aynı kurallar: pipeline/motor/kare_kare.py)
# ---------------------------------------------------------------------------

def colmap_oku(cameras_txt, images_txt):
    ic = {}
    for s in cameras_txt.splitlines():
        p = s.split()
        if not p or p[0].startswith("#"):
            continue
        model, W, H, par = p[1], int(p[2]), int(p[3]), list(map(float, p[4:]))
        if model == "PINHOLE":
            fx, fy, cx, cy = par[:4]
        elif model == "SIMPLE_PINHOLE":
            fx = fy = par[0]
            cx, cy = par[1:3]
        else:
            raise ValueError(m(f"COLMAP kamera modeli {model} desteklenmiyor; bozulmasız PINHOLE ya da SIMPLE_PINHOLE gerekli",
                               f"COLMAP camera model {model} is not supported; use undistorted PINHOLE or SIMPLE_PINHOLE"))
        ic[p[0]] = dict(fx=fx, fy=fy, cx=cx, cy=cy, W=W, H=H)
    satirlar = [s for s in images_txt.splitlines() if s.strip() and not s.startswith("#")]
    kameralar = {}
    for s in satirlar[::2] if len(satirlar) > 1 and len(satirlar[1].split()) != 10 else satirlar:
        p = s.split()
        if len(p) < 10:
            continue
        q = list(map(float, p[1:5]))
        k = dict(ic[p[8]])
        k.update(R=quat_matris(*q), t=list(map(float, p[5:8])), qnorm=boy(q))
        kameralar[Path(p[9]).stem] = k
    return kameralar


def json_oku(veri):
    if veri.get("convention", "opencv") != "opencv" or "cameras" not in veri or "image_size" not in veri:
        raise ValueError(m("cameras.json 4dgs-cameras biçiminde değil", "cameras.json is not in 4dgs-cameras format"))
    W, H = veri["image_size"]
    return {str(k["id"]): dict(fx=k["fx"], fy=k["fy"], cx=k["cx"], cy=k["cy"], W=W, H=H, R=k["R"], t=k["t"], qnorm=1.0)
            for k in veri["cameras"]}


def kalibrasyon_oku(yol):
    if zipfile.is_zipfile(yol):
        with zipfile.ZipFile(yol) as z:
            adlar = {Path(a).name: a for a in z.namelist()}
            if "cameras.json" in adlar:
                return json_oku(json.loads(z.read(adlar["cameras.json"])))
            if "cameras.txt" not in adlar or "images.txt" not in adlar:
                raise ValueError(m("zip içinde cameras.txt ve images.txt (ya da cameras.json) yok",
                                   "zip has no cameras.txt and images.txt (or cameras.json)"))
            return colmap_oku(z.read(adlar["cameras.txt"]).decode(), z.read(adlar["images.txt"]).decode())
    return json_oku(json.loads(Path(yol).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Videolar (ffprobe / ffmpeg isteğe bağlı)
# ---------------------------------------------------------------------------

def video_bilgisi(yol):
    c = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_read_packets:format=duration", "-of", "json", str(yol)],
                       capture_output=True, text=True, timeout=120)
    if c.returncode != 0:
        return None
    j = json.loads(c.stdout)
    s = j["streams"][0]
    pay, payda = s["r_frame_rate"].split("/")
    return dict(W=int(s["width"]), H=int(s["height"]), fps=round(float(pay) / float(payda or 1), 3),
                kare=int(s.get("nb_read_packets", 0)), sure=float(j.get("format", {}).get("duration", 0)))


def kose_parlakligi(yol):
    """İlk karenin dört köşesindeki (8×8 px) en parlak kanal değeri, 0–255."""
    c = subprocess.run(["ffmpeg", "-v", "error", "-i", str(yol), "-frames:v", "1", "-vf", "scale=64:36",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=120)
    if c.returncode != 0 or len(c.stdout) < 64 * 36 * 3:
        return None
    b = c.stdout
    en = 0
    for y0, x0 in ((0, 0), (0, 56), (28, 0), (28, 56)):
        for y in range(y0, y0 + 8):
            for x in range(x0, x0 + 8):
                i = (y * 64 + x) * 3
                en = max(en, b[i], b[i + 1], b[i + 2])
    return en


# ---------------------------------------------------------------------------

def denetle(klasor, kalib_yolu=None):
    r = Rapor()
    klasor = Path(klasor)
    videolar = {}
    for v in sorted(klasor.glob("*.mp4")) + sorted(klasor.glob("*.MP4")) + sorted(klasor.glob("*.mov")):
        e = ETIKET.match(v.stem)
        if e:
            videolar[e.group(1).lower()] = v
    if not videolar:
        r.hata(f"{klasor} içinde cam00.mp4, cam01.mp4 … adlı video yok.", f"No videos named cam00.mp4, cam01.mp4 … in {klasor}.")
        return r, {}
    etiketler = sorted(videolar)
    beklenen = [f"cam{i:02d}" for i in range(len(etiketler))]
    if etiketler != beklenen:
        r.uyari(f"Kamera etiketleri cam00'dan başlayıp ardışık değil: {', '.join(etiketler)}.",
                f"Camera labels are not consecutive from cam00: {', '.join(etiketler)}.")
    n = len(etiketler)
    if n < 4:
        r.hata(f"{n} kamera: en az 4 gerekli (önerilen 8).", f"{n} cameras: at least 4 required (8 recommended).")
    elif n < 6:
        r.uyari(f"{n} kamera: aradaki açılardan hayalet görüntü olabilir; önerilen 8.",
                f"{n} cameras: ghosting is likely between views; 8 recommended.")
    else:
        r.tamam(f"{n} kamera.", f"{n} cameras.")

    bilgi = {}
    if shutil.which("ffprobe"):
        for e in etiketler:
            b = video_bilgisi(videolar[e])
            if b is None:
                r.hata(f"{videolar[e].name} okunamadı (bozuk ya da desteklenmeyen video).",
                       f"{videolar[e].name} could not be read (corrupt or unsupported video).")
            else:
                bilgi[e] = b
        if bilgi:
            for alan, ad_tr, ad_en in (("W", "genişlik", "width"), ("H", "yükseklik", "height"), ("fps", "fps", "fps"),
                                       ("kare", "kare sayısı", "frame count")):
                degerler = {e: b[alan] for e, b in bilgi.items()}
                if len(set(degerler.values())) > 1:
                    r.hata(f"Videoların {ad_tr} değerleri farklı: {degerler}. Hepsi aynı olmalı (senkron çekim).",
                           f"Videos differ in {ad_en}: {degerler}. All must match (synchronized capture).")
            b0 = next(iter(bilgi.values()))
            r.tamam(f"Videolar: {b0['W']}×{b0['H']}, {b0['fps']} fps, {b0['kare']} kare, {b0['sure']:.1f} sn.",
                    f"Videos: {b0['W']}×{b0['H']}, {b0['fps']} fps, {b0['kare']} frames, {b0['sure']:.1f} s.")
            if b0["sure"] > 10.2:
                r.uyari("İşleme sunucusu şu an her çekimin en çok ilk 10 saniyesini işliyor; önemli hareket ilk 10 saniyede olsun.",
                        "The processing server currently uses up to the first 10 seconds of each capture; keep the key motion there.")
    else:
        r.uyari("ffprobe bulunamadı; çözünürlük/fps/kare sayısı denetlenmedi.", "ffprobe not found; resolution/fps/frame count not checked.")

    if shutil.which("ffmpeg"):
        acik = {}
        for e in etiketler:
            k = kose_parlakligi(videolar[e])
            if k is not None and k > 12:
                acik[e] = k
        if acik:
            r.uyari(f"Fon siyah değil (ilk karede köşe parlaklığı 0–255: {acik}). Gri ya da renkli fon motorda sis olur; "
                    "sentetik çekimde dünya rengi (0, 0, 0) olmalı. Gerçek çekimde bu uyarı beklenir.",
                    f"Background is not black (corner brightness 0–255 in the first frame: {acik}). A grey or coloured "
                    "background turns into fog; in synthetic captures set the world colour to (0, 0, 0). Expected for real footage.")
        else:
            r.tamam("Fon siyah (ilk karelerin köşeleri).", "Background is black (first-frame corners).")

    if kalib_yolu is None:
        for ad in ("kalibrasyon.zip", "calibration.zip", "kalibrasyon/cameras.json", "calibration/cameras.json"):
            if (klasor / ad).exists():
                kalib_yolu = klasor / ad
                break
    if kalib_yolu is None:
        r.uyari("Kalibrasyon dosyası yok (kalibrasyon.zip / calibration.zip). Dosya olmadan proje ancak --colmap ile gönderilebilir: "
                "sunucu görüntülerden hesaplamayı dener (en az 7–8 kamera, komşular en çok 45°, dokulu sahne; 6 ve altında çoğunlukla durur). "
                "Sentetik çekimde kalibrasyonu kamera verisinden yazmak çok daha güvenilir.",
                "No calibration file (kalibrasyon.zip / calibration.zip). Without one a project can only be submitted with --colmap: "
                "the server tries to estimate it from the images (7–8+ cameras at most 45° apart, textured scene; 6 or fewer usually fail). "
                "For synthetic captures writing calibration from the camera data is far more reliable.")
        return r, bilgi
    try:
        kameralar = kalibrasyon_oku(kalib_yolu)
    except (ValueError, KeyError, IndexError, UnicodeDecodeError, json.JSONDecodeError) as h:
        r.hata(f"Kalibrasyon okunamadı: {h}", f"Calibration could not be read: {h}")
        return r, bilgi
    if not kameralar:
        r.hata("Kalibrasyonda kamera yok.", "Calibration contains no cameras.")
        return r, bilgi

    # Eşleştirme: tam ad, camNN_ öneki ya da sayı eşitse sırayla (motorla aynı)
    if all(e in kameralar for e in etiketler):
        eslesme = {e: kameralar[e] for e in etiketler}
    else:
        onekli = {a.split("_", 1)[0].lower(): a for a in kameralar}
        if all(e in onekli for e in etiketler):
            eslesme = {e: kameralar[onekli[e]] for e in etiketler}
        elif len(kameralar) == n:
            r.uyari(f"Kalibrasyondaki adlar ({', '.join(sorted(kameralar)[:4])}…) video adlarıyla eşleşmiyor; sırayla eşleştirilecek. "
                    "images.txt'de NAME = cam00.png gibi olmalı.",
                    f"Calibration names ({', '.join(sorted(kameralar)[:4])}…) do not match the video names; they will be paired "
                    "in order. In images.txt NAME should be like cam00.png.")
            eslesme = dict(zip(etiketler, (kameralar[k] for k in sorted(kameralar))))
        else:
            r.hata(f"Kalibrasyonda {len(kameralar)} kamera, klasörde {n} video var; adlar da eşleşmiyor.",
                   f"Calibration has {len(kameralar)} cameras, folder has {n} videos, and the names do not match.")
            return r, bilgi

    sorun = 0
    for e, k in eslesme.items():
        fov = math.degrees(2 * math.atan(k["W"] / 2 / k["fx"])) if k["fx"] > 0 else 0
        if not 5 <= fov <= 150:
            sorun += 1
            r.hata(f"{e}: fx = {k['fx']:.0f} px, {k['W']} px genişlikte {fov:.2f}° yatay görüş veriyor. fx piksel cinsinden olmalı: "
                   "fx = odak_mm × genişlik_px / sensör_mm.",
                   f"{e}: fx = {k['fx']:.0f} px gives a {fov:.2f}° horizontal FOV at {k['W']} px. fx must be in pixels: "
                   "fx = focal_mm × width_px / sensor_mm.")
        if abs(k.get("qnorm", 1) - 1) > 0.01:
            r.uyari(f"{e}: kuaterniyon birim değil (|q| = {k['qnorm']:.3f}); normalize edilerek okunur.",
                    f"{e}: quaternion is not unit length (|q| = {k['qnorm']:.3f}); it will be normalized.")
        if e in bilgi and (bilgi[e]["W"], bilgi[e]["H"]) != (k["W"], k["H"]):
            sorun += 1
            r.hata(f"{e}: kalibrasyon {k['W']}×{k['H']}, video {bilgi[e]['W']}×{bilgi[e]['H']}; aynı olmalı.",
                   f"{e}: calibration is {k['W']}×{k['H']}, video is {bilgi[e]['W']}×{bilgi[e]['H']}; they must match.")
        if abs(k["cx"] - k["W"] / 2) > 0.1 * k["W"] or abs(k["cy"] - k["H"] / 2) > 0.1 * k["H"]:
            r.uyari(f"{e}: ana nokta ({k['cx']:.0f}, {k['cy']:.0f}) görüntü merkezinden uzak; lens kaydırması (shift) 0 olmalı.",
                    f"{e}: principal point ({k['cx']:.0f}, {k['cy']:.0f}) is far from the image centre; lens shift should be 0.")

    # Geometri: kamera merkezleri C = −Rᵀt, bakış yönü = R'nin 3. satırı, yukarı ≈ −(R'nin 2. satırı) ortalaması
    C = [[-sum(k["R"][j][i] * k["t"][j] for j in range(3)) for i in range(3)] for k in eslesme.values()]
    d = [k["R"][2] for k in eslesme.values()]
    if n >= 2:
        A = [[sum((1.0 if i == j else 0.0) - x[i] * x[j] for x in d) for j in range(3)] for i in range(3)]
        b = [sum(((1.0 if i == j else 0.0) - x[i] * x[j]) * c[j] for x, c in zip(d, C) for j in range(3)) for i in range(3)]
        merkez = coz3(A, b)
        if merkez:
            ters = []
            for e, c, x in zip(eslesme, C, d):
                h = fark(merkez, c)
                aci = math.degrees(math.acos(max(-1.0, min(1.0, nokta(x, h) / (boy(h) + 1e-9)))))
                if aci > 35:
                    ters.append(f"{e} ({aci:.0f}°)")
            if ters:
                r.uyari(f"Bu kameralar ortak merkeze bakmıyor: {', '.join(ters)}. Eksen kuralı (OpenCV: x sağ, y aşağı, z ileri; "
                        "dünya → kamera) ya da poz yanlış olabilir.",
                        f"These cameras do not look at the common centre: {', '.join(ters)}. The axis convention (OpenCV: x right, "
                        "y down, z forward; world → camera) or the pose may be wrong.")
            else:
                r.tamam("Kameralar ortak bir merkeze bakıyor.", "Cameras look at a common centre.")
            yukari = [-sum(k["R"][1][i] for k in eslesme.values()) for i in range(3)]
            yukari = [v / (boy(yukari) or 1) for v in yukari]
            goreli = [fark(c, merkez) for c in C]
            yuk = [nokta(g, yukari) for g in goreli]
            uzak = sorted(boy(g) for g in goreli)[len(goreli) // 2]
            if n >= 6 and max(yuk) - min(yuk) < 0.1 * uzak:
                r.uyari("Tüm kameralar aynı yükseklikte; başın üstü ve kol altları zayıf kalır. 8+ kamerada iki yükseklik kullanın.",
                        "All cameras are at the same height; the top of the head and under the arms stay weak. Use two heights with 8+ cameras.")
            duz = [fark(g, [y * u for u in yukari]) for g, y in zip(goreli, yuk)]
            e1 = [v / (boy(duz[0]) or 1) for v in duz[0]]
            e2 = capraz(yukari, e1)
            acilar = sorted(math.degrees(math.atan2(nokta(g, e2), nokta(g, e1))) % 360 for g in duz)
            bosluk = max([b2 - b1 for b1, b2 in zip(acilar, acilar[1:])] + [acilar[0] + 360 - acilar[-1]])
            if n >= 3 and bosluk > 75:
                r.uyari(f"Halkada {bosluk:.0f}°'lik kamerasız boşluk var; o yönden sahne bozuk görünür.",
                        f"There is a {bosluk:.0f}° gap in the camera ring; the scene will look broken from that direction.")
    if not sorun:
        r.tamam(f"Kalibrasyon okundu: {len(eslesme)} kamera ({Path(kalib_yolu).name}).",
                f"Calibration read: {len(eslesme)} cameras ({Path(kalib_yolu).name}).")
    return r, bilgi


def main():
    global DIL
    ap = argparse.ArgumentParser(description="4dgspl.at delivery checker / teslim denetleyicisi")
    ap.add_argument("klasor", help="camNN.mp4 videolarının bulunduğu klasör / folder with camNN.mp4 videos")
    ap.add_argument("--kalibrasyon", "--calibration", help="kalibrasyon .zip ya da cameras.json")
    ap.add_argument("--json", action="store_true", help="makine okunur çıktı / machine-readable output")
    ap.add_argument("--dil", "--lang", choices=["tr", "en"], default="tr" if os.environ.get("LANG", "").startswith("tr") else "en")
    a = ap.parse_args()
    DIL = a.dil
    r, _ = denetle(a.klasor, a.kalibrasyon)
    if a.json:
        print(json.dumps({"ok": not r.hatali, "bulgular": [{"duzey": d, "metin": t} for d, t in r.satirlar]}, ensure_ascii=False, indent=1))
    else:
        isaret = {"HATA": "✗", "UYARI": "!", "TAMAM": "✓"}
        for d, t in r.satirlar:
            print(f"{isaret[d]} {t}")
        print(m("\nSONUÇ: " + ("HATA — yüklemeden önce düzeltin." if r.hatali else "Yüklemeye hazır: https://4dgspl.at/panel.html"),
                "\nRESULT: " + ("ERROR — fix before uploading." if r.hatali else "Ready to upload: https://4dgspl.at/panel.html")))
    sys.exit(1 if r.hatali else 0)


if __name__ == "__main__":
    main()
