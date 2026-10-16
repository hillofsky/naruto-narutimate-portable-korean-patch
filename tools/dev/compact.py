# Recovered SUB52K FIX2 ISO helpers, without historical entrypoint.
from pathlib import Path
import hashlib,importlib.util,os,struct
SECTOR=2048
DAT='PSP_GAME/USRDIR/naruto.dat'
IDX='PSP_GAME/USRDIR/naruto.idx'

def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):
            h.update(b)
    return h.hexdigest()

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:
        raise RuntimeError('Cannot import '+str(path))
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

def get_root_extent(iso):
    with Path(iso).open('rb') as f:
        f.seek(16*SECTOR)
        p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b'CD001':
        raise RuntimeError('Not ISO9660 primary descriptor')
    r=p[156:190]
    return int.from_bytes(r[2:6],'little'),int.from_bytes(r[10:14],'little')

def dirents(f,lba,size):
    f.seek(lba*SECTOR)
    data=f.read(size)
    entries=[];pos=0
    while pos<len(data):
        n=data[pos]
        if n==0:
            pos=(pos//SECTOR+1)*SECTOR
            continue
        r=data[pos:pos+n]
        if len(r)<34:
            raise RuntimeError('Short ISO9660 directory record')
        ident=r[33:33+r[32]]
        name='.' if ident==b'\x00' else ('..' if ident==b'\x01' else ident.decode('ascii','replace').split(';',1)[0])
        entries.append(dict(name=name,lba=int.from_bytes(r[2:6],'little'),
                            size=int.from_bytes(r[10:14],'little'),is_dir=bool(r[25]&2)))
        pos+=n
    return entries

def scan_live_extents(source, cut):
    root=get_root_extent(source)
    files=[];dirs=[];seen=set()
    with Path(source).open('rb') as f:
        def walk(path,lba,size,depth):
            if depth>15:raise RuntimeError('Excessive directory depth')
            key=(lba,size)
            if key in seen:return
            seen.add(key)
            dirs.append((path or '/',lba*SECTOR,lba*SECTOR+size))
            for e in dirents(f,lba,size):
                if e['name'] in ('.','..'):continue
                name=(path+'/'+e['name']).lstrip('/')
                a=e['lba']*SECTOR;b=a+e['size']
                if e['is_dir']:
                    walk(name,e['lba'],e['size'],depth+1)
                else:
                    files.append((name,a,b))
        walk('',*root,0)
    protected={DAT.casefold(),IDX.casefold()}
    beyond=[]
    for name,a,b in files:
        if b>cut and name.casefold() not in protected:
            beyond.append((name,a,b))
    for name,a,b in dirs:
        if b>cut:
            beyond.append((name,a,b))
    if beyond:
        raise RuntimeError('Unsafe compaction: live source file/dir after DAT start: '+repr(beyond[:12]))
    return files,dirs

def extent_from_record(f,rec):
    """Read authoritative ISO9660 directory-record fields from disk.

    Stage15 find_path() guarantees record_offset, but its returned dictionary
    does not expose 'lba' and 'size'. Both PVD and Joliet directory entries
    encode the file LBA and length at bytes +2/+10, respectively.
    """
    if not isinstance(rec,dict) or 'record_offset' not in rec:
        raise RuntimeError('stage15.find_path missing record_offset: '+repr(rec))
    offset=rec['record_offset']
    if not isinstance(offset,int) or offset<0:
        raise RuntimeError('Invalid ISO record offset: '+repr(offset))
    f.seek(offset)
    head=f.read(34)
    if len(head)<34 or head[0]<34:
        raise RuntimeError('ISO9660 directory record truncated at '+str(offset))
    le_lba=int.from_bytes(head[2:6],'little')
    be_lba=int.from_bytes(head[6:10],'big')
    le_size=int.from_bytes(head[10:14],'little')
    be_size=int.from_bytes(head[14:18],'big')
    if le_lba!=be_lba or le_size!=be_size:
        raise RuntimeError('ISO directory endian mismatch at '+str(offset))
    if le_size==0:
        raise RuntimeError('Zero-length ISO file record at '+str(offset))
    end=le_lba*SECTOR+le_size
    f.seek(0,os.SEEK_END)
    if end>f.tell():
        raise RuntimeError('File extent outside ISO: '+repr((le_lba,le_size,end)))
    return (le_lba,le_size)

def get_extent(f,mod15,vds,path):
    found=[]
    for vd in vds:
        if vd['type'] not in (1,2):
            continue
        d=mod15.find_path(f,vd,path.split('/'))
        if d is not None:
            found.append(d)
    if not found:
        raise RuntimeError('Missing file in ISO: '+path)
    loc={extent_from_record(f,x) for x in found}
    if len(loc)!=1:
        raise RuntimeError('Primary/Joliet extents disagree for '+path+': '+repr(loc))
    return found,next(iter(loc))

def stream_region(src,start,size,dst,chunk=8*1024*1024):
    h=hashlib.sha256()
    src.seek(start)
    rem=size
    while rem:
        b=src.read(min(rem,chunk))
        if not b:raise RuntimeError('Unexpected EOF streaming segment')
        dst.write(b);h.update(b);rem-=len(b)
    return h.hexdigest()

def align_stream(f):
    f.seek(0,os.SEEK_END)
    off=f.tell()
    rem=off%SECTOR
    if rem:f.write(bytes(SECTOR-rem))
    return f.tell()

def hash_iso_segment(path,lba,size):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        f.seek(lba*SECTOR);remain=size
        while remain:
            b=f.read(min(remain,8*1024*1024))
            if not b:raise RuntimeError('Truncated output')
            h.update(b);remain-=len(b)
    return h.hexdigest()
