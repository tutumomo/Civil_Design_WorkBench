"""國土測繪中心 WMTS 抓圖並逐像素重投影到 TWD97 TM2（EPSG:3826）。踩坑見 docs\\踩坑紀錄.md C 節"""
import io, time, requests, numpy as np
from PIL import Image
from pyproj import Transformer
to97 = Transformer.from_crs(4326, 3826, always_xy=True)
from97 = Transformer.from_crs(3826, 4326, always_xy=True)
S = requests.Session(); S.headers["User-Agent"] = "civil-design-basemap/1.0"

def merc_px(lon, lat, z):
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi) / 2 * n

def fetch_twd97(layer, z, mode, E0, N0, E1, N1, res, log=print):
    """回傳 PIL 影像，左上角=(E0,N1)，每像素 res 公尺，正北朝上"""
    lo, la = from97.transform([E0, E1, E0, E1], [N0, N0, N1, N1])
    px, py = merc_px(np.array(lo), np.array(la), z)
    tx0, tx1, ty0, ty1 = int(px.min() // 256) - 1, int(px.max() // 256) + 1, int(py.min() // 256) - 1, int(py.max() // 256) + 1
    bg = (0, 0, 0, 0) if mode == "RGBA" else (255, 255, 255)
    mos = Image.new(mode, ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), bg)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            r = None
            for k in range(3):
                try:
                    r = S.get(f"https://wmts.nlsc.gov.tw/wmts/{layer}/default/GoogleMapsCompatible/{z}/{ty}/{tx}", timeout=30)
                    r.raise_for_status(); break
                except Exception: r = None; time.sleep(1 + k)
            ct = r.headers.get("Content-Type", "") if r is not None else ""
            if r is not None and r.content and ct.startswith("image/") and "gif" not in ct:
                mos.paste(Image.open(io.BytesIO(r.content)).convert(mode), ((tx - tx0) * 256, (ty - ty0) * 256))
            time.sleep(0.08)
    arr = np.asarray(mos)
    cols, rows = int(round((E1 - E0) / res)), int(round((N1 - N0) / res))
    EE, NN = np.meshgrid(E0 + (np.arange(cols) + 0.5) * res, N1 - (np.arange(rows) + 0.5) * res)
    lon, lat = from97.transform(EE.ravel(), NN.ravel())
    qx, qy = merc_px(np.asarray(lon), np.asarray(lat), z)
    ix = np.clip(np.floor(qx - tx0 * 256).astype(int), 0, arr.shape[1] - 1)
    iy = np.clip(np.floor(qy - ty0 * 256).astype(int), 0, arr.shape[0] - 1)
    log(f"{layer} z{z}: {(tx1 - tx0 + 1) * (ty1 - ty0 + 1)} tiles")
    return Image.fromarray(arr[iy, ix].reshape(rows, cols, -1).squeeze(), mode)
