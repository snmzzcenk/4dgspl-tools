"""
4dgspl.at Blender rig betiği (beta) — 4–16 kameralı (önerilen 8) sanal çekim düzeni, kalibrasyon ve render.

Ne yapar:
  1. Sahnede "4DGS_Rig" koleksiyonuna, hedef noktaya bakan cam00…camNN kameralarını kurar.
  2. Kalibrasyonu 4dgspl.at'in okuduğu COLMAP metin biçiminde yazar:
       <cikti>/kalibrasyon/cameras.txt  (PINHOLE, kamera başına bir satır)
       <cikti>/kalibrasyon/images.txt   (dünya → kamera, OpenCV kuralı, metre; NAME = camNN.png)
       <cikti>/kalibrasyon.zip          (4dgspl.at proje sayfasına "kalibrasyon" olarak yüklenir)
  3. İsteğe bağlı: her kameradan sahnenin animasyonunu <cikti>/camNN.mp4 olarak render eder.

Kullanım (terminal, arayüzsüz):
    blender -b sahnem.blend -P 4dgspl_blender_rig.py -- --kamera 6 --cikti ./teslim --render
Kullanım (Blender içinde): Scripting → Text → Open → bu dosya → Run Script (AYARLAR bölümündeki değerlerle).

Seçenekler (-- sonrasında):
    --kamera N       kamera sayısı, 4–16 (varsayılan 8)
    --yaricap M      halka yarıçapı, metre (3.5)
    --yukseklik M    kamera yüksekliği, metre (1.5); 8+ kamerada iç içe iki yükseklik: çiftler 0.4 m alçak, tekler 0.6 m yüksek
                     (12+ kamerada 0.5 / 0.7 m) — docs/IDEAL_KAMERA_YERLESIMI.md
    --hedef M        kameraların baktığı noktanın yüksekliği, metre (1.0)
    --lens MM        odak uzaklığı, mm (35; sensör genişliği 36 mm)
    --cozunurluk WxH render çözünürlüğü (1920x1080)
    --cikti KLASOR   teslim klasörü (//teslim = .blend dosyasının yanında)
    --render         kameraları kurduktan sonra her kameradan MP4 render eder
    --mevcut         yeni rig kurmaz; sahnedeki camNN adlı kameraların kalibrasyonunu yazar
    --fon-koru       dünya arka planına dokunmaz (varsayılan: tam siyah, gücü 0 — gri fon motorda sis yapar)

Kurallar: kameralar render boyunca HAREKET ETMEZ; lens kaydırması (shift) 0, hareket bulanıklığı ve alan derinliği kapalı.
Koordinatlar: Blender dünyası (Z yukarı, metre) korunur; kamera eksenleri OpenCV'ye çevrilir (x sağ, y aşağı, z ileri).
Durum: BETA — matematik 4dgspl.at motorunun okuyucusuyla test edildi; Blender içinde henüz geniş çapta denenmedi.
Lisans: MIT. Kaynak ve kılavuz: https://4dgspl.at/cekim.html#sanal
"""
import math
import os
import sys
import zipfile

# --- AYARLAR (Blender içinden çalıştırırken buradan değiştirin) ---------------
AYARLAR = dict(kamera=8, yaricap=3.5, yukseklik=1.5, hedef=1.0, lens=35.0, cozunurluk=(1920, 1080),
               cikti="//teslim", render=False, mevcut=False, fon_koru=False)
SENSOR_MM = 36.0
KOLEKSIYON = "4DGS_Rig"


# --- Saf matematik (bpy gerektirmez; test edilebilir) ---------------------------

def halka_konumlari(n, yaricap, yukseklik, hedef_z):
    """cam00 sahnenin önünde (-Y), saat yönünün tersine eşit aralık. 8+ kamerada iç içe iki yükseklik."""
    konumlar = []
    for i in range(n):
        a = -math.pi / 2 + 2 * math.pi * i / n
        alt, ust = (0.5, 0.7) if n >= 12 else (0.4, 0.6)
        z = yukseklik + ((ust if i % 2 else -alt) if n >= 8 else 0.0)
        konumlar.append((yaricap * math.cos(a), yaricap * math.sin(a), z))
    return konumlar, (0.0, 0.0, hedef_z)


def _matvec(M, v):
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def rot_quat(R):
    """3×3 dönüş matrisi → (qw, qx, qy, qz), COLMAP sırası, qw ≥ 0."""
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s, (R[1][0] - R[0][1]) / s)
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2
        q = ((R[2][1] - R[1][2]) / s, 0.25 * s, (R[0][1] + R[1][0]) / s, (R[0][2] + R[2][0]) / s)
    elif R[1][1] > R[2][2]:
        s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2
        q = ((R[0][2] - R[2][0]) / s, (R[0][1] + R[1][0]) / s, 0.25 * s, (R[1][2] + R[2][1]) / s)
    else:
        s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2
        q = ((R[1][0] - R[0][1]) / s, (R[0][2] + R[2][0]) / s, (R[1][2] + R[2][1]) / s, 0.25 * s)
    q = _normalize(q)
    return [-x for x in q] if q[0] < 0 else q


def opencv_kalibrasyonu(matris_dunya, lens_mm, sensor_mm, W, H, sensor_fit="HORIZONTAL"):
    """Blender kamerasının matrix_world'ü (4×4, liste) → (fx, fy, cx, cy, R, t), dünya → kamera, OpenCV.

    Blender kamerası -Z yönüne bakar, +Y yukarıdır; OpenCV +Z ileri, +Y aşağı: R = diag(1, -1, -1) · R_bl.
    Sensör sığdırma: HORIZONTAL → sensör genişliği görüntü genişliğine (dikey/portre karede de), VERTICAL → yüksekliğe,
    AUTO → büyük kenara eşlenir. Pikseller kare.
    """
    C = [matris_dunya[i][3] for i in range(3)]
    sutunlar = [_normalize([matris_dunya[i][j] for i in range(3)]) for j in range(3)]  # ölçeği at
    R_bl = [list(s) for s in sutunlar]          # kamera→dünya'nın devriği = dünya→kamera (Blender ekseni)
    R = [R_bl[0], [-x for x in R_bl[1]], [-x for x in R_bl[2]]]
    t = [-x for x in _matvec(R, C)]
    kenar = {"HORIZONTAL": W, "VERTICAL": H}.get(sensor_fit, max(W, H))
    fx = lens_mm * kenar / sensor_mm
    return fx, fx, W / 2.0, H / 2.0, R, t


def colmap_metinleri(kameralar, W, H):
    """kameralar: [(ad, (fx, fy, cx, cy, R, t)), …] → (cameras.txt, images.txt)."""
    c = ["# 4dgspl.at Blender rig — PINHOLE, kamera başına bir satır", "# CAMERA_ID MODEL WIDTH HEIGHT fx fy cx cy"]
    im = ["# IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME (dünya → kamera, OpenCV, metre)", "# ikinci satır (2B noktalar) boş"]
    for i, (ad, (fx, fy, cx, cy, R, t)) in enumerate(kameralar, 1):
        c.append(f"{i} PINHOLE {W} {H} {fx:.6f} {fy:.6f} {cx:.6f} {cy:.6f}")
        q = rot_quat(R)
        im.append(f"{i} {q[0]:.9f} {q[1]:.9f} {q[2]:.9f} {q[3]:.9f} {t[0]:.9f} {t[1]:.9f} {t[2]:.9f} {i} {ad}.png")
        im.append("")
    return "\n".join(c) + "\n", "\n".join(im) + "\n"


# --- Blender tarafı -------------------------------------------------------------

def _secenekler():
    a = dict(AYARLAR)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    i = 0
    while i < len(argv):
        k = argv[i].lstrip("-")
        if k in ("render", "mevcut", "fon-koru"):
            a[k.replace("-", "_")] = True
        elif k == "cozunurluk":
            a[k] = tuple(int(x) for x in argv[i + 1].lower().split("x")); i += 1
        elif k == "cikti":
            a[k] = argv[i + 1]; i += 1
        elif k in a:
            a[k] = type(a[k])(argv[i + 1]); i += 1
        else:
            raise SystemExit(f"Bilinmeyen seçenek: {argv[i]}")
        i += 1
    if not 4 <= a["kamera"] <= 16 and not a["mevcut"]:
        raise SystemExit("Kamera sayısı 4 ile 16 arasında olmalı.")
    return a


def fonu_siyah_yap(bpy):
    """Dünya arka planı tam siyah, gücü 0; saydam film kapalı (2026-10-28: 0.05 gri fon ekranda ≈%25 gri çıktı,
    motor fonu Gaussian'larla doldurdu ve yeni açılardan sahne sise gömüldü)."""
    sahne = bpy.context.scene
    dunya = sahne.world or bpy.data.worlds.new("4DGS_Siyah")
    sahne.world = dunya
    dunya.use_nodes = True
    arka = next((d for d in dunya.node_tree.nodes if d.type == "BACKGROUND"), None) or dunya.node_tree.nodes.new("ShaderNodeBackground")
    arka.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    arka.inputs["Strength"].default_value = 0.0
    sahne.render.film_transparent = False
    print("[4dgspl] dünya arka planı tam siyah yapıldı (korumak için --fon-koru)")


def rig_kur(bpy, a):
    sahne = bpy.context.scene
    kol = bpy.data.collections.get(KOLEKSIYON) or bpy.data.collections.new(KOLEKSIYON)
    if kol.name not in sahne.collection.children:
        sahne.collection.children.link(kol)
    for o in list(kol.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    konumlar, hedef = halka_konumlari(a["kamera"], a["yaricap"], a["yukseklik"], a["hedef"])
    bos = bpy.data.objects.new("4DGS_Hedef", None)
    bos.location = hedef
    kol.objects.link(bos)
    for i, p in enumerate(konumlar):
        veri = bpy.data.cameras.new(f"cam{i:02d}")
        veri.lens, veri.sensor_width, veri.sensor_fit = a["lens"], SENSOR_MM, "HORIZONTAL"
        veri.shift_x = veri.shift_y = 0.0
        veri.dof.use_dof = False
        k = bpy.data.objects.new(f"cam{i:02d}", veri)
        k.location = p
        iz = k.constraints.new("TRACK_TO")
        iz.target, iz.track_axis, iz.up_axis = bos, "TRACK_NEGATIVE_Z", "UP_Y"
        kol.objects.link(k)
    bpy.context.view_layer.update()


def kameralar(bpy):
    ks = sorted((o for o in bpy.context.scene.objects if o.type == "CAMERA" and o.name.startswith("cam")), key=lambda o: o.name)
    if not ks:
        raise SystemExit("Sahnede camNN adlı kamera yok.")
    return ks


def kalibrasyon_yaz(bpy, ks, klasor):
    sahne = bpy.context.scene
    r = sahne.render
    W, H = round(r.resolution_x * r.resolution_percentage / 100), round(r.resolution_y * r.resolution_percentage / 100)
    if r.pixel_aspect_x != r.pixel_aspect_y:
        raise SystemExit("Piksel en-boy oranı 1 olmalı.")
    kayit = []
    for k in ks:
        if abs(k.data.shift_x) > 1e-6 or abs(k.data.shift_y) > 1e-6:
            raise SystemExit(f"{k.name}: lens kaydırması 0 olmalı.")
        M = [list(row) for row in k.matrix_world]
        sensor = k.data.sensor_height if k.data.sensor_fit == "VERTICAL" else k.data.sensor_width
        kayit.append((k.name, opencv_kalibrasyonu(M, k.data.lens, sensor, W, H, k.data.sensor_fit)))
    cameras_txt, images_txt = colmap_metinleri(kayit, W, H)
    kd = os.path.join(klasor, "kalibrasyon")
    os.makedirs(kd, exist_ok=True)
    for ad, metin in (("cameras.txt", cameras_txt), ("images.txt", images_txt)):
        with open(os.path.join(kd, ad), "w", encoding="utf-8") as f:
            f.write(metin)
    with zipfile.ZipFile(os.path.join(klasor, "kalibrasyon.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("cameras.txt", cameras_txt)
        z.writestr("images.txt", images_txt)
    print(f"[4dgspl] {len(ks)} kamera, {W}×{H} → {os.path.join(klasor, 'kalibrasyon.zip')}")


def render_al(bpy, ks, klasor):
    sahne = bpy.context.scene
    r = sahne.render
    r.use_motion_blur = False
    r.image_settings.file_format = "FFMPEG"
    r.ffmpeg.format, r.ffmpeg.codec = "MPEG4", "H264"
    r.ffmpeg.constant_rate_factor = "HIGH"
    eski = sahne.camera
    for k in ks:
        sahne.camera = k
        r.filepath = os.path.join(klasor, f"{k.name}.mp4")
        print(f"[4dgspl] render: {k.name} → {r.filepath}")
        bpy.ops.render.render(animation=True)
    sahne.camera = eski


def main():
    import bpy  # noqa: PLC0415  (yalnızca Blender içinde vardır)
    a = _secenekler()
    if not a["mevcut"]:
        r = bpy.context.scene.render
        r.resolution_x, r.resolution_y = a["cozunurluk"]
        r.resolution_percentage = 100
        rig_kur(bpy, a)
    if not a["fon_koru"]:
        fonu_siyah_yap(bpy)
    klasor = bpy.path.abspath(a["cikti"])
    os.makedirs(klasor, exist_ok=True)
    ks = kameralar(bpy)
    kalibrasyon_yaz(bpy, ks, klasor)
    if a["render"]:
        render_al(bpy, ks, klasor)
    print("[4dgspl] Bitti. 4dgspl.at'te projeyi açın; camNN.mp4 dosyalarını sırasıyla, kalibrasyon.zip'i kalibrasyon olarak yükleyin.")


if __name__ == "__main__":
    main()
