# Minimal OLE/CFB directory lister: prints every stream of a .max file with its size,
# plus the decoded DocumentSummaryInformation strings (Max puts scene totals there).
import re
import struct
import sys

path = sys.argv[1]
data = open(path, "rb").read()
assert data[:8] == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", "not an OLE file"
sec_shift = struct.unpack_from("<H", data, 30)[0]
mini_shift = struct.unpack_from("<H", data, 32)[0]
SS = 1 << sec_shift
MS = 1 << mini_shift
n_fat = struct.unpack_from("<I", data, 44)[0]
dir_start = struct.unpack_from("<I", data, 48)[0]
mini_cutoff = struct.unpack_from("<I", data, 56)[0]
minifat_start = struct.unpack_from("<I", data, 60)[0]
difat_start = struct.unpack_from("<I", data, 68)[0]
n_difat = struct.unpack_from("<I", data, 72)[0]


def sec(i):
    off = (i + 1) * SS
    return data[off:off + SS]


fat_secs = list(struct.unpack_from("<109I", data, 76))
d = difat_start
for _ in range(n_difat):
    vals = struct.unpack("<%dI" % (SS // 4), sec(d))
    fat_secs += vals[:-1]
    d = vals[-1]
fat_secs = [s for s in fat_secs if s < 0xFFFFFFFA][:n_fat]
fat = []
for s in fat_secs:
    fat += struct.unpack("<%dI" % (SS // 4), sec(s))


def chain(start):
    out = []
    while start < 0xFFFFFFFA and len(out) < len(fat):
        out.append(start)
        start = fat[start]
    return out


def read_stream(start, size):
    return b"".join(sec(s) for s in chain(start))[:size]


dirdata = read_stream(dir_start, 10 ** 9)
entries = []
for i in range(len(dirdata) // 128):
    e = dirdata[i * 128:(i + 1) * 128]
    nlen = struct.unpack_from("<H", e, 64)[0]
    name = e[:max(nlen - 2, 0)].decode("utf-16-le", "replace")
    typ = e[66]
    start = struct.unpack_from("<I", e, 116)[0]
    size = struct.unpack_from("<Q", e, 120)[0]
    if typ:
        entries.append((name, typ, start, size))

root = entries[0]
ministream = read_stream(root[2], root[3])
minifat = []
for s in chain(minifat_start):
    minifat += struct.unpack("<%dI" % (SS // 4), sec(s))


def read_any(start, size):
    if size >= mini_cutoff:
        return read_stream(start, size)
    out = []
    while start < 0xFFFFFFFA and len(out) * MS < size:
        out.append(ministream[start * MS:(start + 1) * MS])
        start = minifat[start]
    return b"".join(out)[:size]


print("file size %d, sector %d" % (len(data), SS))
for name, typ, start, size in entries:
    print("%-45r type=%d size=%12d" % (name, typ, size))

for name, typ, start, size in entries:
    if "DocumentSummaryInformation" in name:
        raw = read_any(start, size)
        strs = re.findall(rb"(?:[\x20-\x7e]\x00){3,}", raw)
        print("\n--- %r strings (utf-16) ---" % name)
        for s in strs:
            print(s.decode("utf-16-le"))
        strs8 = re.findall(rb"[\x20-\x7e]{4,}", raw)
        print("--- ascii ---")
        for s in strs8[:400]:
            print(s.decode("ascii"))
