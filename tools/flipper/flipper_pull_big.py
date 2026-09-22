import sys, time
import serial

PORT, REMOTE, OUT, SIZE = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
ser = serial.Serial(PORT, 115200, timeout=1)
try:
    # wake CLI + drain welcome banner
    ser.write(b"\r"); time.sleep(0.3)
    t0 = time.time(); last = time.time()
    while time.time() - t0 < 8:
        c = ser.read(ser.in_waiting or 1)
        if c:
            last = time.time()
        if time.time() - last > 1.5:
            break
    ser.reset_input_buffer()
    ser.write(("storage read " + REMOTE + "\r").encode())
    buf = b""; t1 = time.time(); last = time.time()
    while time.time() - t1 < 300:
        c = ser.read(65536)
        if c:
            buf += c; last = time.time()
            if len(buf) >= SIZE + 8:
                break
        elif time.time() - last > 6:
            break
    start = -1
    for m in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4', b'\x0a\x0d\x0d\x0a'):
        i = buf.find(m)
        if i != -1:
            start = i; break
    if start == -1:
        idx = buf.find(b"Size:")
        if idx != -1:
            nl = buf.find(b"\n", idx)
            if nl != -1:
                start = nl + 1
    if start == -1:
        print("NO START buflen", len(buf)); sys.exit(1)
    data = buf[start:start + SIZE]
    with open(OUT, "wb") as f:
        f.write(data)
    print("OK wrote", len(data), "of", SIZE, "buflen", len(buf))
finally:
    ser.close()
