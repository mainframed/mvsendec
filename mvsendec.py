#!/usr/bin/env python3

# rewrite of mvsendec.c by Paul Edwards 
# support for variable record length added
# Philip Young
# GPL v3


import sys
import ebcdic

outbuf = []
lrecl = 80

if len(sys.argv) < 4:
    print("usage: mvsendec <encb/decb/enct/dect> [<lrecl>] <infile> <outfile>")
    sys.exit(1)

arg = sys.argv[1].lower()
fp = sys.argv[2]
fq = sys.argv[3]

if len(sys.argv) == 5:
    fp = sys.argv[3]
    fq = sys.argv[4]
    lrecl = int(sys.argv[2])

if arg in ['encb', 'decb', 'dect']:
    with open(fp, 'rb') as f:
        hexdata = f.read()

if arg == "enct":
    with open(fp, 'rb') as f:
        text = f.readlines()
    for l in text:
        line ="{:<{lrecl}}".format(l.rstrip().decode('utf-8'),lrecl=lrecl)
        hexedt = line.encode('cp1140').hex()
        t = [(hexedt[i:i+80]) for i in range(0, len(hexedt), 80)]
        outbuf.append(t[0])
        outbuf.append(t[1])
elif arg == "encb":
    outbuf = [(hexdata.hex()[i:i+80]) for i in range(0, len(hexdata.hex()), 80)]
elif arg == "decb":
    outbuf = bytearray.fromhex(hexdata.decode('utf-8').replace("\n",""))
elif arg == "dect":
    t = bytearray.fromhex(hexdata.decode('utf-8').replace("\n",""))
    d = t.decode('cp1140')
    outbuf = [(d[i:i+80]) for i in range(0, len(d), lrecl)]
else:
    print("need to specify encode or decode (binary or text)")
    sys.exit(1)

if arg in ['encb','enct', 'dect']:
    with open(fq, 'w') as f:
        for item in outbuf:
            f.write("%s\n" % item.upper())
else:
    with open(fq, 'wb') as f:
            f.write(outbuf)
