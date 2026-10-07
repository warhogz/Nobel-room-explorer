# Census of the raw 'Scene' stream of a .max file: counts ReferenceMaker records per class
# (independent of what 3ds Max actually manages to load).
import collections
import struct
import sys

sys.argv = sys.argv  # usage: scene_census.py file.max
import importlib.util

spec = importlib.util.spec_from_file_location("ole", __file__.replace("scene_census.py", "ole_streams_lib.py"))


def load_ole(path):
    data = open(path, "rb").read()
    SS = 1 << struct.unpack_from("<H", data, 30)[0]
    MS = 1 << struct.unpack_from("<H", data, 32)[0]
    n_fat = struct.unpack_from("<I", data, 44)[0]
    dir_start = struct.unpack_from("<I", data, 48)[0]
    mini_cutoff = struct.unpack_from("<I", data, 56)[0]
    minifat_start = struct.unpack_from("<I", data, 60)[0]
    difat_start = struct.unpack_from("<I", data, 68)[0]
    n_difat = struct.unpack_from("<I", data, 72)[0]
    sec = lambda i: data[(i + 1) * SS:(i + 2) * SS]
    fat_secs = list(struct.unpack_from("<109I", data, 76))
    d = difat_start
    for _ in range(n_difat):
        vals = struct.unpack("<%dI" % (SS // 4), sec(d))
        fat_secs += vals[:-1]
        d = vals[-1]
    fat = []
    for s in [s for s in fat_secs if s < 0xFFFFFFFA][:n_fat]:
        fat += struct.unpack("<%dI" % (SS // 4), sec(s))

    def chain(start):
        out = []
        while start < 0xFFFFFFFA and len(out) < len(fat):
            out.append(start)
            start = fat[start]
        return out

    def rd(start, size):
        return b"".join(sec(s) for s in chain(start))[:size]

    dirdata = rd(dir_start, 10 ** 9)
    ents = {}
    for i in range(len(dirdata) // 128):
        e = dirdata[i * 128:(i + 1) * 128]
        nlen = struct.unpack_from("<H", e, 64)[0]
        if e[66]:
            ents[e[:max(nlen - 2, 0)].decode("utf-16-le", "replace")] = (
                struct.unpack_from("<I", e, 116)[0], struct.unpack_from("<Q", e, 120)[0])
    root = ents["Root Entry"]
    mini = rd(*root)
    minifat = []
    for s in chain(minifat_start):
        minifat += struct.unpack("<%dI" % (SS // 4), sec(s))

    def get(name):
        start, size = ents[name]
        if size >= mini_cutoff:
            return rd(start, size)
        out = []
        while start < 0xFFFFFFFA and len(out) * MS < size:
            out.append(mini[start * MS:(start + 1) * MS])
            start = minifat[start]
        return b"".join(out)[:size]

    return get


def chunks(buf, off, end):
    """yield (id, is_container, payload_start, payload_end)"""
    while off + 6 <= end:
        cid, ln = struct.unpack_from("<HI", buf, off)
        hdr = 6
        if ln == 0:
            ln = struct.unpack_from("<Q", buf, off + 6)[0]
            hdr = 14
            cont = bool(ln & (1 << 63))
            ln &= ~(1 << 63)
        else:
            cont = bool(ln & 0x80000000)
            ln &= 0x7FFFFFFF
        if ln < hdr or off + ln > end:
            raise ValueError("bad chunk at %d id=%x len=%d" % (off, cid, ln))
        yield cid, cont, off + hdr, off + ln
        off += ln


def class_dir(buf):
    out = []
    for cid, cont, a, b in chunks(buf, 0, len(buf)):
        if not cont:
            continue
        entry = {}
        for cid2, c2, a2, b2 in chunks(buf, a, b):
            if cid2 == 0x2060:
                dll, c1, c2_, sc = struct.unpack_from("<iIII", buf, a2)
                entry.update(dll=dll, cls=(c1, c2_), super=sc)
            elif cid2 == 0x2042:
                entry["name"] = buf[a2:b2].decode("utf-16-le", "replace")
        out.append(entry)
    return out


if __name__ == "__main__":
    get = load_ole(sys.argv[1])
    cd = class_dir(get("ClassDirectory3"))
    print("classes in ClassDirectory3:", len(cd))
    scene = get("Scene")
    print("Scene stream bytes:", len(scene))
    top = list(chunks(scene, 0, len(scene)))
    print("top-level chunks:", [(hex(c), cont, b - a) for c, cont, a, b in top][:10])
    counts = collections.Counter()
    sizes = collections.Counter()
    n = 0
    for c, cont, a, b in top:
        if not cont:
            continue
        for cid, c2, a2, b2 in chunks(scene, a, b):
            n += 1
            name = cd[cid]["name"] if cid < len(cd) else "0x%x" % cid
            counts[name] += 1
            sizes[name] += b2 - a2
    print("records:", n)
    for name, k in counts.most_common():
        print("%7d  %10d KB  %s" % (k, sizes[name] // 1024, name))
