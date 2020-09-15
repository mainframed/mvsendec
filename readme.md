# mvsendec.py

Python script to work with tk4- `MVSENDEC` program which is basically a C implementation of pythons `bytearray.fromhex()`.


## Usage
Take any file, text or binary, and convert it with mvsendec.py:

`mvsendec.py enct infile outfile`

You can pass an optional record length field to change the length of the records read:

`mvsendec.py enct 160 infile outfile`

Then take the outfile and place it in a dataset on tk4-. Then use this job to convert it back:

```
//ENCODE   JOB CLASS=A,MSGCLASS=H,MSGLEVEL=(1,1),
//         USER=HERC01,PASSWORD=CUL8TR
//MVSENDEC EXEC PGM=MVSENDEC,PARM='decb dd:in dd:out'
//STEPLIB  DD  DSN=SYS2.LINKLIB,DISP=SHR
//IN       DD  *
<<<mvsendec output goes here>>>
/*
//OUT      DD DSN=HERC01.JCLLIB(NEWFILE),DISP=SHR
//SYSPRINT DD  SYSOUT=*
//SYSTERM  DD  SYSOUT=*
//SYSIN    DD  DUMMY
//*
```

The parms on the job act the exact same way as arguments on the command line.


