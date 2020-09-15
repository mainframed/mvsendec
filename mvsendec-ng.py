#!/usr/bin/env python3

# rewrite of mvsendec.c by Paul Edwards 
# support for variable record length added
# Philip Young
# GPL v3

import argparse
import sys
import ebcdic
import magic
import os
import logging
import zipfile
from io import BytesIO
from pprint import pprint


JOBCARD = '''//MVSNDNG  JOB CLASS=A,MSGCLASS=H,MSGLEVEL=(1,1),
//         USER={},PASSWORD={},NOTIFY=PHIL
'''

DELETE_JCL = '''//DELETE   EXEC PGM=IDCAMS,REGION=1024K
//SYSPRINT DD  SYSOUT=A
//SYSIN    DD  *
{}/* IF THERE WAS NO DATASET TO DELETE, RESET CC           */
 IF LASTCC = 8 THEN
   DO
       SET LASTCC = 0
       SET MAXCC = 0
   END
/*
'''

CREATE_PDS = '''//BRCREATE EXEC PGM=IEFBR14
{}'''

iefbr14_ddn = '''//{ddn:<8} DD  DSN={pds},
//             DISP=(NEW,CATLG,DELETE),
//             UNIT={unit},VOL=SER={ser},SPACE=(TRK,({trks},,{dirs})),
//             DCB=(RECFM={recm},LRECL={lrecl},BLKSIZE={blk})
'''

#max len 
IDCAMS_DELETE = " DELETE {} NONVSAM SCRATCH PURGE\n"


DECODE_JCL = '''//ENCODE{enc:<2} EXEC PGM=MVSENDEC,PARM='decb dd:in dd:out'
//STEPLIB  DD  DSN=SYS2.LINKLIB,DISP=SHR
//IN       DD  *
{zipped_hex}
/*
//OUT      DD  DSN={zipfile},DISP=SHR
//SYSPRINT DD  SYSOUT=*
//SYSTERM  DD  SYSOUT=*
//SYSIN    DD  DUMMY
//*
'''

UNZIP = '''//UNZP{enc:<4} EXEC PGM=MINIUNZ,PARM='ZIPIN PDSOUT'
//STEPLIB    DD DSN=SYS2.LINKLIB,DISP=SHR
//STDOUT     DD SYSOUT=*
//ZIPIN      DD DSN={infile},DISP=SHR
//PDSOUT     DD DSN={outpd},DISP=SHR           
//SYSUT1     DD DSN={infile},DISP=SHR
'''

UPDATE = '''
//UPDTE{enc:<3} EXEC PGM=IEBUPDTE,REGION=1024K,PARM=NEW
//SYSUT2   DD  DSN={outpd},DISP=SHR
//SYSPRINT DD  SYSOUT=*
//SYSIN    DD  DATA,DLM='##'
'''

def make_temp_zip(files):
    mem_zip = BytesIO()
    logging.debug("Generating zip file")
    with zipfile.ZipFile(mem_zip, mode="w",compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            logging.debug("compressing {}".format(f['member']))
            zf.writestr(f['member'], f['file_import'])
    logging.debug("Done")
    return mem_zip.getvalue()

def list_files(dir):
    # https://stackoverflow.com/questions/19932130/iterate-through-folders-then-subfolders-and-print-filenames-with-path-to-text-f
    r = []
    for root, dirs, files in os.walk(dir):
        for name in files:
#            logging.debug("Adding: {}".format(os.path.join(root, name)))
            r.append(os.path.join(root, name))
    return r

def parse_folders(f='', no_skip = False, ignore = [], hlq=''):
    logging.debug("parsing file: {} | no skip: {}  | ignore list: {} | hlq: {}".format(f, no_skip, ignore, hlq))
    os.path.getsize(f)
    ds = f.replace("../","").replace("./", "").replace(" ","")

    if not no_skip and os.path.splitext(ds.split("/")[-1].upper())[0][0] == '.':
        logging.debug("hidden file ignored")
        # ignore hidden files/folder at root
        return False

    elif not no_skip and ds[0] == '.':
        logging.debug("hidden folder/file ignored")
        # ignore hidden files/folder at root
        return False

    for d in ds.split("/")[:-1]:
        if not no_skip and d[0] == '.':
            logging.debug("hidden folder ignored")
            return False
        elif d in ignore:
            logging.debug("file/folder in ignore list ignored")
            return False
        hlq += "." + d.upper().replace("_","")[:8]
        if len(hlq) > 44:
            logging.debug("Max HLQ length (44) reached: {}".format(hlq))
            break    


    member =  os.path.splitext(ds.split("/")[-1].upper())[0].replace(".","").replace("_","")[:8]
    filemagic = magic.Magic(mime_encoding=True).from_file(f)
    return({'file':f,'type':filemagic,'pds':hlq, 'member':member, 'size': os.path.getsize(f)})



parser = argparse.ArgumentParser(description='The next gen mvsendec.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('-u', '--username',default="herc01", help="tk4- username used for JCL submission to reader port" )
parser.add_argument('-p', '--password',default="cul8tr" , help="tk4- password used for JCL submission to reader port")
parser.add_argument('-d', '--pds',default="HERC01.UNZIPPED", help="Unallocated dataset where files will be places")
parser.add_argument('-t', '--temp', default="HERC01.TMP", help="temp dataset for storing zip file")
parser.add_argument('--debug', help="show verbose output",  action="store_const", dest="loglevel", const=logging.DEBUG, default=logging.WARNING) 
parser.add_argument('--charset', choices=["text","binary"], help="Force charset for all files instead of using libmagic")
parser.add_argument('--flat', help="by default folders get their own qualifier, if you want all files to go in one PDS use this flag", action='store_true' )
parser.add_argument('--no-skip', help="dont skip hidden files/folders")
parser.add_argument('--ignore', help="ignore folders that contain x, can be used multiple times: --ignore FOO --ignore Bar", action='append', default=[])
parser.add_argument('--lrecl', help="set record length instead of calculating defaults")
parser.add_argument('--recfm', help="set record format instead of calculating defaults")
parser.add_argument('--unit', default=3390)
parser.add_argument('--ser', default='PUB013')
parser.add_argument('HLQ', help="This is the HLQ/qualifiers for the PDS(s) that will be created. i.e. 'FUN.TIMES' or 'TESTING'.")
parser.add_argument('file', nargs='*')
args = parser.parse_args()

if not args.file:
    parser.error("No files provided. HLQ: {}".format(args.HLQ))
elif "/" in args.HLQ:
    parser.error("No HLQ provided. HLQ: {}".format(args.HLQ))

logging.basicConfig(level=args.loglevel)
logging.debug("Initiating mvsendec-ng")

all_files = {}
files = []
for infile in args.file:
    if os.path.isdir(infile):  
        files.extend(list_files(infile))
    elif os.path.isfile(infile):  
        files.append(infile)
    else:  
        print("{} is not a file".format)

charset = args.charset
c = []
filesDict = {}
filesDict[args.HLQ] = {}
filesDict[args.HLQ]['files'] = []
for f in files:

    if "/" in f:
        fd = parse_folders(f=f, no_skip = args.no_skip, ignore = args.ignore, hlq=args.HLQ)
        if fd:  
            if fd['pds'] not in filesDict:
                filesDict[fd['pds']] = {}
                filesDict[fd['pds']]['files'] = []
                filesDict[fd['pds']]['files'].append({'file' : fd['file'], 'type' : fd['type'], 'member' : fd['member'], 'size': fd['size']})
            else:
                filesDict[fd['pds']]['files'].append({'file' : fd['file'], 'type' : fd['type'], 'member' : fd['member'], 'size': fd['size']})
            
    else:
        logging.debug("parsing file: {} | no skip: {}  | ignore list: {} | hlq: {}".format(f, args.no_skip, args.ignore, args.HLQ))
        
        if not args.no_skip and f[0] == '.':
            logging.debug("hidden file ignored")
            continue

        elif f in args.ignore:
            logging.debug("file/folder in ignore list ignored")
            continue
        
        member =  os.path.splitext(f.upper())[0].replace(".","").replace("_","")[:8]
        filemagic = magic.Magic(mime_encoding=True).from_file(f)
        filesDict[args.HLQ]['files'].append({'file':f,'type':filemagic,'member':member, 'size': os.path.getsize(f)})


if args.flat:
    newdict = {}
    newdict[args.HLQ] = {}
    newdict[args.HLQ]['files'] = []
    for i in filesDict:
        for j in filesDict[i]['files']:
            newdict[args.HLQ]['files'].append(j)
    filesDict = newdict

    

for pds in filesDict:
    tsize = 0
    numfiles = 0
    filesDict[pds]['charset'] = 'ascii'
    for filed in filesDict[pds]['files']:
        tsize += filed['size']
        numfiles += 1
        if filed['type'] in ['binary','ebcdic','unknown-8bit']:
            filesDict[pds]['charset'] = 'binary'
    if args.charset:
        logging.debug('Forcing chaset to: {}'.format(args.charset))
        filesDict[pds]['charset'] = args.charset
    if filesDict[pds]['charset'].lower() == 'ascii':
        filesDict[pds]['recfm'] = 'VB'
        filesDict[pds]['lrecl'] = 255
    else:
        filesDict[pds]['recfm'] = 'FB'
        filesDict[pds]['lrecl'] = 80

    if args.lrecl:
        filesDict[pds]['lrecl'] = int(args.lrecl)

    if args.recfm:
        filesDict[pds]['recfm'] = args.recfm

    filesDict[pds]['numfiles'] = numfiles
    filesDict[pds]['totaldir'] = (numfiles//6) + 10

logging.debug("Gathering files")
for pds in filesDict:
    for filed in filesDict[pds]['files']:
        logging.debug("Processing {} Type:{} lrecl: {}".format(filed['file'], filed['type'], filesDict[pds]['lrecl']))
        if filed['type'] in ['binary','ebcdic','unknown-8bit']:
            logging.debug("Reading binary file")
            with open(filed['file'], 'rb') as f:
                filed['file_import'] = f.read()
            filed['max_len'] = 80

        else:
            logging.debug("Opening: {}".format(filed['file']))
            with open(filed['file'], 'rb') as f:
                text = f.readlines()
            filed['file_import'] = bytearray()
            filed['file_ascii'] = text
            filed['max_len'] = 0
            for l in text:
                line ="{:<{lrecl}}".format(l.rstrip().decode(filed['type']),lrecl=filesDict[pds]['lrecl']-4)
                filed['file_import'] +=  line.encode('cp1140')
                if len(l.rstrip()) > filed['max_len']:
                    filed['max_len'] = len(l.rstrip())
            filed['size'] = len(filed['file_import'])

for pds in filesDict:
    tsize = 0
    max_len = 0
    for filed in filesDict[pds]['files']:
        tsize += filed['size']
        if filed['max_len'] < max_len:
            max_len = filed['max_len']
    filesDict[pds]['tsize'] = tsize
    # bestblocksize = INTEGER(half-track-blocksize/LRECL)*LRECL 
    # http://www.mvsforums.com/helpboards/viewtopic.php?t=28
    filesDict[pds]['blksize'] = (27998//filesDict[pds]['lrecl'])*filesDict[pds]['lrecl']
    filesDict[pds]['tracks'] = (tsize//27998) 
    filesDict[pds]['max_len'] = max_len

logging.debug("creating zip files")


zsize = 0
for pds in filesDict:
    if len(filesDict[pds]['files']) == 0:
        continue
    zip_file = make_temp_zip(filesDict[pds]['files'])
    hexed = [(zip_file.hex()[i:i+80].upper()) for i in range(0, len(zip_file.hex()), 80)]
    filesDict[pds]['zsize'] = len(zip_file)
    filesDict[pds]['zipped'] = hexed
    with open('test.zip', 'wb') as f:
        f.write(zip_file)
    zsize += len(zip_file)

logging.debug("creating jcl")
jcl = JOBCARD.format(args.username.upper(), args.password.upper())
del_zip = IDCAMS_DELETE.format(args.HLQ+'.ZIPS')
ztrks = (zsize//27998) + 10
zdirs = (len(filesDict) // 6) + 10
ddn = 1
iefbr = iefbr14_ddn.format(ddn, ddn = "ZIPFILE", pds=args.HLQ+'.ZIPS',unit=args.unit,ser=args.ser,trks=ztrks,dirs=zdirs,recm='FB',lrecl='80',blk= (27998//80)*80)


for pds in filesDict:
    if len(filesDict[pds]['files']) == 0:
        continue
    del_zip += IDCAMS_DELETE.format(pds)
    iefbr += iefbr14_ddn.format(ddn = "FILE"+str(ddn), pds=pds,unit=args.unit,ser=args.ser,trks=filesDict[pds]['tracks'],dirs=filesDict[pds]['totaldir'],recm=filesDict[pds]['recfm'],lrecl=filesDict[pds]['lrecl'],blk=filesDict[pds]['blksize'])
    ddn += 1

jcl += DELETE_JCL.format(del_zip)
jcl += CREATE_PDS.format(iefbr)


# either it ascii and they're all less than 80 use IEBUPDTE
# otherwise use zip/mvsencode
ddn = 1
for pds in filesDict:
    if len(filesDict[pds]['files']) == 0:
        continue

    if filesDict[pds]['charset'] == 'ascii' and filesDict[pds]['max_len'] <= 80:
        jcl += UPDATE.format(enc=ddn,outpd=pds)
        for files in filesDict[pds]['files']:
            jcl += "./ ADD NAME={},LIST=ALL\n".format(files['member'])
            for l in files['file_ascii']:
                jcl += l.decode('utf-8')
            

    else:
        jcl += DECODE_JCL.format(enc=ddn, zipped_hex='\n'.join(filesDict[pds]['zipped']),zipfile=args.HLQ+'.ZIPS(FILE{})'.format(ddn))
        jcl += UNZIP.format(enc=ddn, infile=args.HLQ+'.ZIPS(FILE{})'.format(ddn), outpd=pds)
    
    ddn += 1

print(jcl)



