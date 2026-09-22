import sys, time
import serial
PORT = sys.argv[1]; CMDS = sys.argv[2:]
ser = serial.Serial(PORT, 115200, timeout=1)
try:
    ser.write(b"\r"); time.sleep(0.3)
    t0 = time.time(); last = time.time()
    while time.time() - t0 < 8:
        c = ser.read(ser.in_waiting or 1)
        if c: last = time.time()
        if time.time() - last > 1.5: break
    for cmd in CMDS:
        ser.reset_input_buffer()
        ser.write((cmd + "\r").encode())
        t1 = time.time(); last = time.time(); out = b""
        while time.time() - t1 < 10:
            c = ser.read(ser.in_waiting or 1)
            if c: out += c; last = time.time()
            if time.time() - last > 1.2: break
        print("### " + cmd)
        print(out.decode(errors="replace"))
finally:
    ser.close()
