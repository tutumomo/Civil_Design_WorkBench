import struct, sys
p = r"D:\公司案件.AI\SolidCraft範例\U型溝渠\U型溝渠.stl"
data = open(p, "rb").read()
n = struct.unpack("<I", data[80:84])[0]
print("triangles:", n)
off = 84
vol = 0.0
for i in range(n):
    vals = struct.unpack("<12fH", data[off:off+50])
    v = [(vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), (vals[9], vals[10], vals[11])]
    a, b, c = v
    vol += (a[0]*(b[1]*c[2]-b[2]*c[1]) - a[1]*(b[0]*c[2]-b[2]*c[0]) + a[2]*(b[0]*c[1]-b[1]*c[0]))/6.0
    off += 50
print("mesh signed volume mm3:", abs(vol))
L, W, H = 10000, 840, 720
print("outer:", L*W*H)
print("theory void removed:", L*600*600)
print("theory result:", L*W*H - L*600*600)
print("model reported: 2491199999.999999")
