# -*- coding: utf-8 -*-
#
# GPL License and Copyright Notice ============================================
#  This file is part of Wrye Bash.
#
#  Wrye Bash is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  Wrye Bash is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Wrye Bash.  If not, see <https://www.gnu.org/licenses/>.
#
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2021 Wrye Bash Team
#  https://github.com/wrye-bash
#
# =============================================================================
from __future__ import division

import io
import zlib
from collections import defaultdict

from ._mergeability import is_esl_capable
from .. import balt, bolt, bush, bass, load_order
from ..bolt import GPath, deprint, structs_cache
from ..brec import ModReader, MreRecord, SubrecordBlob, null1
from ..exception import CancelError, ModError

# BashTags dir ----------------------------------------------------------------
def get_tags_from_dir(plugin_name):
    """Retrieves a tuple containing a set of added and a set of deleted
    tags from the 'Data/BashTags/PLUGIN_NAME.txt' file, if it is
    present.

    :param plugin_name: The name of the plugin to check the tag file for.
    :return: A tuple containing two sets of added and deleted tags."""
    # Check if the file even exists first
    tag_files_dir = bass.dirs[u'tag_files']
    tag_file = tag_files_dir.join(plugin_name.body + u'.txt')
    if not tag_file.isfile(): return set(), set()
    removed, added = set(), set()
    # BashTags files must be in UTF-8 (or ASCII, obviously)
    with tag_file.open(u'r', encoding=u'utf-8') as ins:
        for tag_line in ins:
            # Strip out comments and skip lines that are empty as a result
            tag_line = tag_line.split(u'#')[0].strip()
            if not tag_line: continue
            for tag_entry in tag_line.split(u','):
                # Guard against things (e.g. typos) like 'TagA,,TagB'
                if not tag_entry: continue
                tag_entry = tag_entry.strip()
                # If it starts with a minus, it's removing a tag
                if tag_entry[0] == u'-':
                    # Guard against a typo like '- C.Water'
                    removed.add(tag_entry[1:].strip())
                else:
                    added.add(tag_entry)
    return added, removed

def save_tags_to_dir(plugin_name, plugin_tag_diff):
    """Compares plugin_tags to plugin_old_tags and saves the diff to
    Data/BashTags/PLUGIN_NAME.txt.

    :param plugin_name: The name of the plugin to modify the tag file for.
    :param plugin_tag_diff: A tuple of two sets, as returned by diff_tags,
        representing a diff of all bash tags currently applied to the
        plugin in question vs. all bash tags applied to the plugin
        by its description and the LOOT masterlist / userlist.."""
    tag_files_dir = bass.dirs[u'tag_files']
    tag_files_dir.makedirs()
    tag_file = tag_files_dir.join(plugin_name.body + u'.txt')
    # Calculate the diff and ignore the minus when sorting the result
    tag_diff_add, tag_diff_del = plugin_tag_diff
    processed_diff = sorted(tag_diff_add | {u'-' + t for t in tag_diff_del},
                            key=lambda t: t[1:] if t[0] == u'-' else t)
    # While BashTags files can be UTF-8, our generated files are only ever
    # going to be ASCII, so write them with that encoding
    with tag_file.open(u'w', encoding=u'ascii') as out:
        # Stick a header in there to indicate that it's machine-generated
        # Also print the version, which could be helpful
        out.write(u'# Generated by Wrye Bash %s\n' % bass.AppVersion)
        out.write(u', '.join(processed_diff) + u'\n')

def diff_tags(plugin_new_tags, plugin_old_tags):
    """Returns two sets, the first containing all added tags and the second all
    removed tags."""
    return plugin_new_tags - plugin_old_tags, plugin_old_tags - plugin_new_tags

#--Mod Checker ----------------------------------------------------------------
_cleaning_wiki_url = (u'[[!https://tes5edit.github.io/docs/7-mod-cleaning-and'
                      u'-error-checking.html|Tome of xEdit]]')

def checkMods(showModList=False, showCRC=False, showVersion=True,
              mod_checker=None):
    """Checks currently loaded mods for certain errors / warnings.
    mod_checker should be the instance of ModChecker, to scan."""
    from . import modInfos
    active = set(load_order.cached_active_tuple())
    imported_ = modInfos.imported
    removeEslFlag = set()
    warning = u'=== <font color=red>'+_(u'WARNING:')+u'</font> '
    #--Header
    log = bolt.LogFile(io.StringIO())
    log.setHeader(u'= '+_(u'Check Mods'),True)
    if bush.game.check_esl:
        log(_(u'This is a report on your currently installed or '
              u'active mods.'))
    else:
        log(_(u'This is a report on your currently installed, active, '
              u'or merged mods.'))
    #--Mergeable/NoMerge/Deactivate tagged mods
    if bush.game.check_esl:
        shouldMerge = modInfos.mergeable
    else:
        shouldMerge = active & modInfos.mergeable
    if bush.game.check_esl:
        for m, modinf in modInfos.items():
            if not modinf.is_esl():
                continue # we check .esl extension and ESL flagged mods
            if not is_esl_capable(modinf, modInfos, reasons=None):
                removeEslFlag.add(m)
    shouldDeactivateA, shouldDeactivateB = [], []
    for x in active:
        tags = modInfos[x].getBashTags()
        if u'Deactivate' in tags: shouldDeactivateA.append(x)
        if u'NoMerge' in tags and x in modInfos.mergeable:
            shouldDeactivateB.append(x)
    shouldActivateA = [x for x in imported_ if x not in active and
                u'MustBeActiveIfImported' in modInfos[x].getBashTags()]
    #--Mods with invalid TES4 version
    valid_vers = bush.game.Esp.validHeaderVersions
    invalidVersion = [(x, unicode(round(modInfos[x].header.version, 6)))
                      for x in active if round(
            modInfos[x].header.version, 6) not in valid_vers]
    #--Look for dirty edits
    shouldClean = {}
    scan = []
    dirty_msgs = [(x, modInfos[x].getDirtyMessage()) for x in active]
    for x, y in dirty_msgs:
        if y[0]:
            shouldClean[x] = y[1]
        elif mod_checker:
            scan.append(modInfos[x])
    if mod_checker:
        try:
            with balt.Progress(_(u'Scanning for Dirty Edits...'),u'\n'+u' '*60, parent=mod_checker, abort=True) as progress:
                ret = ModCleaner.scan_Many(scan,ModCleaner.ITM|ModCleaner.UDR,progress)
                for i,mod in enumerate(scan):
                    udrs,itms,fog = ret[i]
                    if mod.name == GPath(u'Unofficial Oblivion Patch.esp'): itms.discard((GPath(u'Oblivion.esm'),0x00AA3C))
                    if mod.isBP(): itms = set()
                    if udrs or itms:
                        cleanMsg = []
                        if udrs:
                            cleanMsg.append(u'UDR(%i)' % len(udrs))
                        if itms:
                            cleanMsg.append(u'ITM(%i)' % len(itms))
                        cleanMsg = u', '.join(cleanMsg)
                        shouldClean[mod.name] = cleanMsg
        except CancelError:
            pass
    # below is always empty with current implementation
    shouldCleanMaybe = [(x, y[1]) for x, y in dirty_msgs if
                        not y[0] and y[1] != u'']
    for mod in tuple(shouldMerge):
        if u'NoMerge' in modInfos[mod].getBashTags():
            shouldMerge.discard(mod)
    if shouldMerge:
        if bush.game.check_esl:
            log.setHeader(u'=== '+_(u'ESL Capable'))
            log(_(u'Following mods could be assigned an ESL flag but '
                  u'are not ESL flagged.'))
        else:
            log.setHeader(u'=== ' + _(u'Mergeable'))
            log(_(u'Following mods are active, but could be merged into '
                  u'the bashed patch.'))
        for mod in sorted(shouldMerge):
            log(u'* __%s__' % mod)
    if removeEslFlag:
        log.setHeader(u'=== ' + _(u'Incorrect ESL Flag'))
        log(_(u'Following mods have an ESL flag, but do not qualify. '
              u"Either remove the flag with 'Remove ESL Flag', or "
              u"change the extension to '.esp' if it is '.esl'."))
        for mod in sorted(removeEslFlag):
            log(u'* __%s__' % mod)
    if shouldDeactivateB:
        log.setHeader(u'=== '+_(u'NoMerge Tagged Mods'))
        log(_(u'Following mods are tagged NoMerge and should be '
              u'deactivated and imported into the bashed patch but '
              u'are currently active.'))
        for mod in sorted(shouldDeactivateB):
            log(u'* __%s__' % mod)
    if shouldDeactivateA:
        log.setHeader(u'=== '+_(u'Deactivate Tagged Mods'))
        log(_(u'Following mods are tagged Deactivate and should be '
              u'deactivated and imported into the bashed patch but '
              u'are currently active.'))
        for mod in sorted(shouldDeactivateA):
            log(u'* __%s__' % mod)
    if shouldActivateA:
        log.setHeader(u'=== '+_(u'MustBeActiveIfImported Tagged Mods'))
        log(_(u'Following mods to work correctly have to be active as '
              u'well as imported into the bashed patch but are '
              u'currently only imported.'))
        for mod in sorted(shouldActivateA):
            log(u'* __%s__' % mod)
    if shouldClean:
        log.setHeader(
            u'=== ' + _(u'Mods that need cleaning with %s') %
            bush.game.Xe.full_name)
        log(_(u'Following mods have identical to master (ITM) '
              u'records, deleted records (UDR), or other issues that '
              u'should be fixed with %(xedit_name)s. Visit the '
              u'%(cleaning_wiki_url)s for more information.') % {
            u'cleaning_wiki_url': _cleaning_wiki_url,
            u'xedit_name': bush.game.Xe.full_name})
        for mod in sorted(shouldClean):
            log(u'* __%s:__  %s' % (mod, shouldClean[mod]))
    if shouldCleanMaybe:
        log.setHeader(
            u'=== ' + _(u'Mods with special cleaning instructions'))
        log(_(u'Following mods have special instructions for cleaning '
              u'with %s') % bush.game.Xe.full_name)
        for mod in sorted(shouldCleanMaybe):
            log(u'* __%s:__  %s' % mod) # mod is a tuple here
    elif mod_checker and not shouldClean:
        log.setHeader(
            u'=== ' + _(u'Mods that need cleaning with %s') %
            bush.game.Xe.full_name)
        log(_(u'Congratulations, all mods appear clean.'))
    if invalidVersion:
        # Always an ASCII byte string, so this is fine
        header_sig_ = unicode(bush.game.Esp.plugin_header_sig,
                              encoding=u'ascii')
        ver_list = u', '.join(
            sorted(unicode(v) for v in bush.game.Esp.validHeaderVersions))
        log.setHeader(
            u'=== ' + _(u'Mods with non-standard %s versions') %
            header_sig_)
        log(_(u"The following mods have a %s version that isn't "
              u'recognized as one of the standard versions '
              u'(%s). It is untested what effects this can have on '
              u'%s.') % (header_sig_, ver_list, bush.game.displayName))
        for mod in sorted(invalidVersion):
            log(u'* __%s:__  %s' % mod) # mod is a tuple here
    #--Missing/Delinquent Masters
    if showModList:
        log(u'\n' + modInfos.getModList(showCRC, showVersion,
                                        wtxt=True).strip())
    else:
        log.setHeader(warning+_(u'Missing/Delinquent Masters'))
        previousMods = set()
        for mod in load_order.cached_active_tuple():
            loggedMod = False
            for master in modInfos[mod].masterNames:
                if master not in active:
                    label_ = _(u'MISSING')
                elif master not in previousMods:
                    label_ = _(u'DELINQUENT')
                else:
                    label_ = u''
                if label_:
                    if not loggedMod:
                        log(u'* %s' % mod)
                        loggedMod = True
                    log(u'  * __%s__ %s' %(label_,master))
            previousMods.add(mod)
    return log.out.getvalue()

#------------------------------------------------------------------------------
_wrld_types = frozenset((b'CELL', b'WRLD'))
class ModCleaner(object):
    """Class for cleaning ITM and UDR edits from mods. ITM detection does not
    currently work with PBash."""
    UDR     = 0x01  # Deleted references
    ITM     = 0x02  # Identical to master records
    FOG     = 0x04  # Nvidia Fog Fix
    ALL = UDR|ITM|FOG
    DEFAULT = UDR|ITM

    class UdrInfo(object):
        # UDR info
        # (UDR fid, UDR Type, UDR Parent Fid, UDR Parent Type, UDR Parent Parent Fid, UDR Parent Block, UDR Paren SubBlock)
        def __init__(self,fid,Type=None,parentFid=None,parentEid=u'',
                     parentType=None,parentParentFid=None,parentParentEid=u'',
                     pos=None):
            self.fid = fid
            self.type = Type
            self.parentFid = parentFid
            self.parentEid = parentEid
            self.parentType = parentType
            self.pos = pos
            self.parentParentFid = parentParentFid
            self.parentParentEid = parentParentEid

        # Implement rich comparison operators, __cmp__ is deprecated
        def __eq__(self, other):
            return self.fid == other.fid
        def __ne__(self, other):
            return self.fid != other.fid
        def __lt__(self, other):
            return self.fid < other.fid
        def __le__(self, other):
            return self.fid <= other.fid
        def __gt__(self, other):
            return self.fid > other.fid
        def __ge__(self, other):
            return self.fid >= other.fid


    def __init__(self,modInfo):
        self.modInfo = modInfo
        self.itm = set()    # Fids for Identical To Master records
        self.udr = set()    # Fids for Deleted Reference records
        self.fog = set()    # Fids for Cells needing the Nvidia Fog Fix

    def scan(self,what=ALL,progress=bolt.Progress(),detailed=False):
        """Scan this mod for dirty edits.
           return (UDR,ITM,FogFix)"""
        udr,itm,fog = ModCleaner.scan_Many([self.modInfo],what,progress,detailed)[0]
        if what & ModCleaner.UDR:
            self.udr = udr
        if what & ModCleaner.ITM:
            self.itm = itm
        if what & ModCleaner.FOG:
            self.fog = fog
        return udr,itm,fog

    @staticmethod
    def scan_Many(modInfos, what=DEFAULT, progress=bolt.Progress(),
        detailed=False, __unpacker=structs_cache[u'=12s2f2l2f'].unpack,
        __wrld_types=_wrld_types, __unpacker2=structs_cache[u'2i'].unpack):
        """Scan multiple mods for dirty edits"""
        if len(modInfos) == 0: return []
        if not (what & (ModCleaner.UDR|ModCleaner.FOG)):
            return [(set(), set(), set())] * len(modInfos)
        # Python can't do ITM scanning
        doUDR = what & ModCleaner.UDR
        doFog = what & ModCleaner.FOG
        progress.setFull(max(len(modInfos),1))
        ret = []
        for i,modInfo in enumerate(modInfos):
            progress(i,_(u'Scanning...') + u'\n%s' % modInfo.name)
            itm = set()
            fog = set()
            #--UDR stuff
            udr = {}
            parents_to_scan = defaultdict(set)
            if len(modInfo.masterNames) > 0:
                subprogress = bolt.SubProgress(progress,i,i+1)
                if detailed:
                    subprogress.setFull(max(modInfo.size*2,1))
                else:
                    subprogress.setFull(max(modInfo.size,1))
                #--Scan
                parentType = None
                parentFid = None
                parentParentFid = None
                # Location (Interior = #, Exteror = (X,Y)
                with ModReader(modInfo.name,modInfo.getPath().open(u'rb')) as ins:
                    try:
                        insAtEnd = ins.atEnd
                        insTell = ins.tell
                        insUnpackRecHeader = ins.unpackRecHeader
                        while not insAtEnd():
                            subprogress(insTell())
                            header = insUnpackRecHeader()
                            _rsig = header.recType
                            #(type,size,flags,fid,uint2) = ins.unpackRecHeader()
                            if _rsig == b'GRUP':
                                groupType = header.groupType
                                if groupType == 0 and header.label not in __wrld_types:
                                    # Skip Tops except for WRLD and CELL groups
                                    header.skip_blob(ins)
                                elif detailed:
                                    if groupType == 1:
                                        # World Children
                                        parentParentFid = header.label
                                        parentType = 1 # Exterior Cell
                                        parentFid = None
                                    elif groupType == 2:
                                        # Interior Cell Block
                                        parentType = 0 # Interior Cell
                                        parentParentFid = parentFid = None
                                    elif groupType in {6,8,9,10}:
                                        # Cell Children, Cell Persistent Children,
                                        # Cell Temporary Children, Cell VWD Children
                                        parentFid = header.label
                                    else: # 3,4,5,7 - Topic Children
                                        pass
                            else:
                                header_fid = header.fid
                                if doUDR and header.flags1 & 0x20 and _rsig in (
                                    b'ACRE',               #--Oblivion only
                                    b'ACHR',b'REFR',        #--Both
                                    b'NAVM',b'PHZD',b'PGRE', #--Skyrim only
                                    ):
                                    if not detailed:
                                        udr[header_fid] = ModCleaner.UdrInfo(header_fid)
                                    else:
                                        udr[header_fid] = ModCleaner.UdrInfo(
                                            header_fid, _rsig, parentFid, u'',
                                            parentType, parentParentFid, u'',
                                            None)
                                        parents_to_scan[parentFid].add(header_fid)
                                        if parentParentFid:
                                            parents_to_scan[parentParentFid].add(header_fid)
                                if doFog and _rsig == b'CELL':
                                    nextRecord = insTell() + header.blob_size()
                                    while insTell() < nextRecord:
                                        subrec = SubrecordBlob(ins, _rsig, mel_sigs={b'XCLL'})
                                        if subrec.mel_data is not None:
                                            color, near, far, rotXY, rotZ, \
                                            fade, clip = __unpacker(
                                                subrec.mel_data)
                                            if not (near or far or clip):
                                                fog.add(header_fid)
                                else:
                                    header.skip_blob(ins)
                        if parents_to_scan:
                            # Detailed info - need to re-scan for CELL and WRLD infomation
                            ins.seek(0)
                            baseSize = modInfo.size
                            while not insAtEnd():
                                subprogress(baseSize+insTell())
                                header = insUnpackRecHeader()
                                _rsig = header.recType
                                if _rsig == b'GRUP':
                                    if header.groupType == 0 and header.label not in __wrld_types:
                                        header.skip_blob(ins)
                                else:
                                    fid = header.fid
                                    if fid in parents_to_scan:
                                        record = MreRecord(header,ins,True)
                                        eid = u''
                                        for subrec in record.iterate_subrecords(mel_sigs={b'EDID', b'XCLC'}):
                                            if subrec.mel_sig == b'EDID':
                                                eid = bolt.decoder(subrec.mel_data)
                                            elif subrec.mel_sig == b'XCLC':
                                                pos = __unpacker2(
                                                    subrec.mel_data[:8])
                                        for udrFid in parents_to_scan[fid]:
                                            if _rsig == b'CELL':
                                                udr[udrFid].parentEid = eid
                                                if udr[udrFid].parentType == 1:
                                                    # Exterior Cell, calculate position
                                                    udr[udrFid].pos = pos
                                            elif _rsig == b'WRLD':
                                                udr[udrFid].parentParentEid = eid
                                    else:
                                        header.skip_blob(ins)
                    except CancelError:
                        raise
                    except:
                        deprint(u'Error scanning %s, file read pos: %i:\n' % (modInfo, ins.tell()), traceback=True)
                        udr = itm = fog = None
                #--Done
            ret.append((udr.values() if udr is not None else None,itm,fog))
        return ret

#------------------------------------------------------------------------------
class NvidiaFogFixer(object):
    """Fixes cells to avoid nvidia fog problem."""
    def __init__(self,modInfo):
        self.modInfo = modInfo
        self.fixedCells = set()

    def fix_fog(self, progress, __unpacker=structs_cache[u'=12s2f2l2f'].unpack,
                __wrld_types=_wrld_types,
                __packer=structs_cache[u'12s2f2l2f'].pack):
        """Duplicates file, then walks through and edits file as necessary."""
        progress.setFull(self.modInfo.size)
        fixedCells = self.fixedCells
        fixedCells.clear()
        #--File stream
        minfo_path = self.modInfo.getPath()
        #--Scan/Edit
        with ModReader(self.modInfo.name,minfo_path.open(u'rb')) as ins:
            with minfo_path.temp.open(u'wb') as  out:
                def copy(bsize):
                    buff = ins.read(bsize)
                    out.write(buff)
                while not ins.atEnd():
                    progress(ins.tell())
                    header = ins.unpackRecHeader()
                    _rsig = header.recType
                    #(type,size,str0,fid,uint2) = ins.unpackRecHeader()
                    out.write(header.pack_head())
                    if _rsig == b'GRUP':
                        if header.groupType != 0: #--Ignore sub-groups
                            pass
                        elif header.label not in __wrld_types:
                            copy(header.blob_size())
                    #--Handle cells
                    elif _rsig == b'CELL':
                        nextRecord = ins.tell() + header.blob_size()
                        while ins.tell() < nextRecord:
                            subrec = SubrecordBlob(ins, _rsig)
                            if subrec.mel_sig == b'XCLL':
                                color, near, far, rotXY, rotZ, fade, clip = \
                                    __unpacker(subrec.mel_data)
                                if not (near or far or clip):
                                    near = 0.0001
                                    subrec.mel_data = __packer(color, near,
                                        far, rotXY, rotZ, fade, clip)
                                    fixedCells.add(header.fid)
                            subrec.packSub(out, subrec.mel_data)
                    #--Non-Cells
                    else:
                        copy(header.blob_size())
        #--Done
        if fixedCells:
            self.modInfo.makeBackup()
            minfo_path.untemp()
            self.modInfo.setmtime(crc_changed=True) # fog fixes
        else:
            minfo_path.temp.remove()

#------------------------------------------------------------------------------
class ModDetails(object):
    """Details data for a mods file. Similar to TesCS Details view."""
    def __init__(self):
        # group_records[group] = [(fid0, eid0), (fid1, eid1),...]
        self.group_records = defaultdict(list)

    def readFromMod(self, modInfo, progress=None,
            __unpacker=structs_cache[u'I'].unpack):
        """Extracts details from mod file."""
        def getRecordReader():
            """Decompress record data as needed."""
            blob_siz = header.blob_size()
            if not MreRecord.flags1_(header.flags1).compressed:
                new_rec_data = ins.read(blob_siz)
            else:
                size_check = __unpacker(ins.read(4))[0]
                new_rec_data = zlib.decompress(ins.read(blob_siz - 4))
                if len(new_rec_data) != size_check:
                    raise ModError(ins.inName,
                        u'Mis-sized compressed data. Expected %d, got '
                        u'%d.' % (blob_siz, len(new_rec_data)))
            return ModReader(modInfo.name, io.BytesIO(new_rec_data))
        progress = progress or bolt.Progress()
        group_records = self.group_records
        records = group_records[bush.game.Esp.plugin_header_sig]
        complex_groups = {b'CELL', b'DIAL', b'WRLD'}
        if bush.game.fsName in (u'Fallout4', u'Fallout4VR'):
            complex_groups.add(b'QUST')
        with ModReader(modInfo.name, modInfo.abs_path.open(u'rb')) as ins:
            while not ins.atEnd():
                header = ins.unpackRecHeader()
                _rsig = header.recType
                if _rsig == b'GRUP':
                    label = header.label
                    progress(1.0 * ins.tell() / modInfo.size,
                             _(u'Scanning: %s') % label.decode(u'ascii'))
                    records = group_records[label]
                    if label in complex_groups: # skip these groups
                        header.skip_blob(ins)
                else:
                    eid = u''
                    next_record = ins.tell() + header.blob_size()
                    recs = getRecordReader()
                    while not recs.atEnd():
                        subrec = SubrecordBlob(recs, _rsig, mel_sigs={b'EDID'})
                        if subrec.mel_data is not None:
                            # FIXME copied from readString
                            eid = u'\n'.join(bolt.decoder(
                                x, bolt.pluginEncoding,
                                avoidEncodings=(u'utf8', u'utf-8')) for x
                                in subrec.mel_data.rstrip(null1).split(b'\n'))
                            break
                    records.append((header.fid, eid))
                    ins.seek(next_record) # we may have break'd at EDID
        del group_records[bush.game.Esp.plugin_header_sig]
