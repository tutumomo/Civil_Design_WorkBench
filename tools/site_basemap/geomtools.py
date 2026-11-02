"""向量化與幾何整形：平滑、去文字凸塊、去階梯、建物正交化"""
import math, numpy as np, cv2

def smooth_mask(m, px):
    """先開後閉，去掉寬度 < px 的凸刺(地號文字)與凹缺"""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px, px))
    return cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k)

def despeckle(P, tol=0.35, iters=12, closed=True):
    """去除階梯狀小折角：刪掉「頂點到前後點連線的偏差 < tol」且「前後邊長 >= tol」的頂點。

    電子地圖在 z19 的原始解析度約 0.27 m，建物輪廓本身就是階梯；Douglas-Peucker
    以 0.4 m 容差簡化後，階梯原封不動留成折線。這裡把「偏離整體走向、但沒有真正
    轉角」的頂點收回來——真實的方正轉角（偏差以公尺計）不會被刪。
    closed=True 視為閉合環（多邊形）；closed=False 為折線且不動兩端點。
    """
    P = np.asarray(P, float)
    if len(P) < 3:
        return P
    pts = [p for p in P]
    for _ in range(iters):
        n = len(pts)
        if n < 3:
            break
        keep = []
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                keep.append(pts[i]); continue
            ia, ic = (i - 1) % n, (i + 1) % n
            a, b, c = pts[ia], pts[i], pts[ic]
            la = math.hypot(b[0] - a[0], b[1] - a[1])
            lc = math.hypot(c[0] - b[0], c[1] - b[1])
            if min(la, lc) < tol:          # 邊太短，可能是真的尖角，保守保留
                keep.append(b); continue
            vx, vy = c[0] - a[0], c[1] - a[1]
            L = math.hypot(vx, vy)
            if L < 1e-9:
                keep.append(b); continue
            dev = abs((b[0] - a[0]) * vy - (b[1] - a[1]) * vx) / L   # b 到 ac 的垂直距離
            keep.append(b if dev >= tol else None)
        new = [p for p in keep if p is not None]
        if len(new) == len(pts) or len(new) < 3:
            break
        pts = new
    return np.array(pts)

def contours(m, eps_px, min_area_px, holes=False):
    """回傳 [(外框, [內洞...])]，座標為像素，已用 Douglas-Peucker 簡化"""
    mode = cv2.RETR_CCOMP if holes else cv2.RETR_EXTERNAL
    cs, hier = cv2.findContours(m.astype(np.uint8), mode, cv2.CHAIN_APPROX_NONE)
    out = []
    if hier is None: return out
    for i, c in enumerate(cs):
        if hier[0][i][3] != -1 or cv2.contourArea(c) < min_area_px: continue
        outer = cv2.approxPolyDP(c, eps_px, True)[:, 0, :].astype(float)
        hs, j = [], hier[0][i][2]
        while holes and j != -1:
            if cv2.contourArea(cs[j]) >= min_area_px:
                hs.append(cv2.approxPolyDP(cs[j], eps_px, True)[:, 0, :].astype(float))
            j = hier[0][j][0]
        if len(outer) >= 3: out.append((outer, hs))
    return out

def _isect(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    det = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(det) < 1e-6: return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / det
    return p1 + t * d1

def regularize(P, tol_deg=12.0, theta=None):
    """建物正交化：依主軸方向，把偏差 < tol_deg 的牆邊拉成正交直線；斜邊保留原方向。
    P: (n,2) 公尺座標(不重複首點)。回傳新的 (m,2)；失敗時回傳原值。"""
    P = np.asarray(P, float)
    P = despeckle(P)          # 先去階梯：階梯的 H/V 邊交替成組，正交化會形同虛設
    n = len(P)
    if n < 4: return P
    c0 = P.mean(0); Q = P - c0
    if theta is None:
        theta = math.radians(cv2.minAreaRect(Q.astype(np.float32))[2])
    cs, sn = math.cos(theta), math.sin(theta)
    R = np.array([[cs, sn], [-sn, cs]]); Q = Q @ R.T            # 旋到主軸座標
    tol = math.radians(tol_deg); edges = []
    for i in range(n):
        a, b = Q[i], Q[(i + 1) % n]; d = b - a; L = np.hypot(*d)
        if L < 1e-6: continue
        ang = math.atan2(d[1], d[0]) % math.pi
        cls = "H" if min(ang, math.pi - ang) < tol else ("V" if abs(ang - math.pi / 2) < tol else None)
        edges.append([cls, a, b, L])
    if len(edges) < 3: return P
    k = next((i for i in range(len(edges)) if edges[i][0] is None or edges[i][0] != edges[i - 1][0]), 0)
    edges = edges[k:] + edges[:k]
    groups = []
    for e in edges:
        if groups and e[0] is not None and groups[-1][0] == e[0]: groups[-1][1].append(e)
        else: groups.append([e[0], [e]])
    lines = []
    for cls, es in groups:
        w = np.array([e[3] for e in es]); mids = np.array([(e[1] + e[2]) / 2 for e in es])
        if cls == "H": lines.append((np.array([0.0, (mids[:, 1] * w).sum() / w.sum()]), np.array([1.0, 0.0])))
        elif cls == "V": lines.append((np.array([(mids[:, 0] * w).sum() / w.sum(), 0.0]), np.array([0.0, 1.0])))
        else: lines.append((es[0][1], (es[0][2] - es[0][1]) / es[0][3]))
    out = []
    for i in range(len(lines)):
        p = _isect(lines[i - 1], lines[i])
        out.append(p if p is not None else groups[i][1][0][1])
    out = np.array(out)
    if len(out) < 3: return P
    area = lambda X: 0.5 * abs(np.dot(X[:, 0], np.roll(X[:, 1], -1)) - np.dot(X[:, 1], np.roll(X[:, 0], -1)))
    if abs(area(out) - area(Q)) > 0.15 * area(Q) or np.abs(out).max() > np.abs(Q).max() * 1.5: return P
    return out @ R + c0

def chaikin_keep_corners(P, iters=2, corner_deg=35.0, tol=0.2):
    """開放折線的有界 Chaikin 平滑：端點與轉角(轉向 > corner_deg)原樣保留；
    其餘頂點切角長度 d = min(25% 鄰段長, tol / sin(轉向/2))，保證每次切角偏移 ≤ tol(公尺)。
    （第一版固定切 25%，長線段緩彎偏移達 1.1 m，已修正）"""
    P = np.asarray(P, float)
    if len(P) < 3: return P
    def turn(a, b, c):
        u, v = b - a, c - b; nu, nv = np.hypot(*u), np.hypot(*v)
        if nu < 1e-9 or nv < 1e-9: return 0.0
        return math.acos(max(-1.0, min(1.0, float(np.dot(u, v) / nu / nv))))
    hard = [True] + [math.degrees(turn(P[i - 1], P[i], P[i + 1])) > corner_deg for i in range(1, len(P) - 1)] + [True]
    for _ in range(iters):
        n = len(P); L = np.hypot(*(np.diff(P, axis=0).T))
        cut = np.zeros(n)
        for k in range(1, n - 1):
            if hard[k]: continue
            th = turn(P[k - 1], P[k], P[k + 1])
            cut[k] = min(0.25 * L[k - 1], 0.25 * L[k], tol / max(math.sin(th / 2), 1e-6))
        Q, H = [], []
        for k in range(n - 1):
            a, b = P[k], P[k + 1]; u = (b - a) / max(L[k], 1e-9)
            if hard[k] or cut[k] == 0: Q.append(a); H.append(hard[k])
            else: Q.append(a + u * cut[k]); H.append(False)
            if not hard[k + 1] and cut[k + 1] > 0: Q.append(b - u * cut[k + 1]); H.append(False)
        Q.append(P[-1]); H.append(True)
        P, hard = np.array(Q), H
    return P

def max_deviation(P_new, P_ref):
    """平滑前後最大偏移 (m)：取兩線 Hausdorff 距離作品質指標"""
    from shapely.geometry import LineString
    return LineString(P_new).hausdorff_distance(LineString(P_ref))
