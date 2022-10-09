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
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2022 Wrye Bash Team
#  https://github.com/wrye-bash
#
# =============================================================================
"""Houses abstract base classes and some APIs for representing records and
subrecords in memory."""

import copy
import io
import zlib
from collections import defaultdict

from . import utils_constants
from .basic_elements import SubrecordBlob, unpackSubHeader
from .mod_io import ModReader
from .utils_constants import int_unpacker
from .. import bolt, exception
from ..bolt import decoder, struct_pack, sig_to_str
from ..bolt import float_or_none, int_or_zero, str_or_none

def _str_to_bool(value, __falsy=frozenset(
    ['', 'none', 'false', 'no', '0', '0.0'])):
    return value.strip().lower() not in __falsy

# Cross game dict, mapping attribute -> csv (de)serializer/csv column header
attr_csv_struct = {
    'aimArc': [float_or_none, _('Aim Arc')],
    'ammoUse': [int_or_zero, _('Ammunition Use')],
    'animationAttackMultiplier': [float_or_none,
                                  _('Animation Attack Multiplier')],
    'animationMultiplier': [float_or_none, _('Animation Multiplier')],
    'armorRating': [int_or_zero, _('Armor Rating')],
    'attackShotsPerSec': [float_or_none, _('Attack Shots Per Second')],
    'baseVatsToHitChance': [int_or_zero, _('Base VATS To-Hit Chance')],
    'calcMax': [int_or_zero, _('CalcMax')],
    'calcMin': [int_or_zero, _('CalcMin')],
    'clipRounds': [int_or_zero, _('Clip Rounds')],
    'clipsize': [int_or_zero, _('Clip Size')],
    'cost': [int_or_zero, _('Cost')],
    'criticalDamage': [int_or_zero, _('Critical Damage')],
    'criticalEffect': [int_or_zero, _('Critical Effect')],
    'criticalMultiplier': [float_or_none, _('Critical Multiplier')],
    'damage': [int_or_zero, _('Damage')],
    'dr': [int_or_zero, _('Damage Resistance')],
    'dt': [float_or_none, _('Damage Threshold')],
    'duration': [int_or_zero, _('Duration')],
    'eid': [str_or_none, _('Editor Id')],
    'enchantPoints': [int_or_zero, _('Enchantment Points')],
    'fireRate': [float_or_none, _('Fire Rate')],
    'flags': [int_or_zero, _('Flags')],
    'full': [str_or_none, _('Name')],
    'group_combat_reaction': [str_or_none, _('Group Combat Reaction')],
    'health': [int_or_zero, _('Health')],
    'iconPath': [str_or_none, _('Icon Path')],
    'impulseDist': [float_or_none, _('Impulse Distance')],
    'jamTime': [float_or_none, _('Jam Time')],
    'killImpulse': [float_or_none, _('Kill Impulse')],
    'level': [str_or_none, _('Level Type')],
    'level_offset': [int_or_zero, _('Offset')],
    'limbDmgMult': [float_or_none, _('Limb Damage Multiplier')],
    'maxRange': [float_or_none, _('Maximum Range')],
    'minRange': [float_or_none, _('Minimum Range')],
    'minSpread': [float_or_none, _('Minimum Spread')],
    'mod': [str_or_none, _('Modifier')],
    'model.modPath': [str_or_none, _('Model Path')],
    'model.modb': [float_or_none, _('Bound Radius')],
    'offset': [int_or_zero, _('Offset')],
    'overrideActionPoint': [float_or_none, _('Override - Action Point')],
    'overrideDamageToWeaponMult': [float_or_none,
        _('Override - Damage To Weapon Multiplier')],
    'projPerShot': [int_or_zero, _('Projectiles Per Shot')],
    'projectileCount': [int_or_zero, _('Projectile Count')],
    'quality': [float_or_none, _('Quality')],
    'reach': [float_or_none, _('Reach')],
    'regenRate': [float_or_none, _('Regeneration Rate')],
    'reloadTime': [float_or_none, _('Reload Time')],
    'rumbleDuration': [float_or_none, _('Rumble - Duration')],
    'rumbleLeftMotorStrength': [float_or_none,
                                _('Rumble - Left Motor Strength')],
    'rumbleRightMotorStrength': [float_or_none,
                                 _('Rumble - Right Motor Strength')],
    'rumbleWavelength': [float_or_none, _('Rumble - Wavelength')],
    'semiAutomaticFireDelayMax': [float_or_none,
                                  _('Maximum Semi-Automatic Fire Delay')],
    'semiAutomaticFireDelayMin': [float_or_none,
                                  _('Minumum Semi-Automatic Fire Delay')],
    'sightFov': [float_or_none, _('Sight Fov')],
    'sightUsage': [float_or_none, _('Sight Usage')],
    'skillReq': [int_or_zero, _('Skill Requirement')],
    'speed': [float_or_none, _('Speed')],
    'spell_flags': [int_or_zero, _('Spell Flags')],
    'spell_flags.disallowAbsorbReflect': [_str_to_bool,
                                          _('Disallow Absorb and Reflect')],
    'spell_flags.ignoreLOS': [_str_to_bool, _('Area Effect Ignores LOS')],
    'spell_flags.immuneToSilence': [_str_to_bool, _('Immune To Silence')],
    'spell_flags.noAutoCalc': [_str_to_bool, _('Manual Cost')],
    'spell_flags.scriptEffectAlwaysApplies': [_str_to_bool,
                                              _('Script Always Applies')],
    'spell_flags.startSpell': [_str_to_bool, _('Start Spell')],
    'spell_flags.touchExplodesWOTarget': [_str_to_bool,
                                          _('Touch Explodes Without Target')],
    'spellType': [str_or_none, _('Spell Type')],
    'spread': [float_or_none, _('Spread')],
    'stagger': [float_or_none, _('Stagger')],
    'strength': [int_or_zero, _('Strength')],
    'strengthReq': [int_or_zero, _('Strength Requirement')],
    'uses': [int_or_zero, _('Uses')], 'value': [int_or_zero, _('Value')],
    'vatsAp': [float_or_none, _('VATS AP')],
    'vatsDamMult': [float_or_none, _('VATS Damage Multiplier')],
    'vatsSkill': [float_or_none, _('VATS Skill')],
    'weight': [float_or_none, _('Weight')],
}

# Note: these two formats *must* remain in the %d/%s style! f-strings will
# break with Flags etc. due to them not implementing __format__
for _k, _v in attr_csv_struct.items():
    if _v[0] is int_or_zero: # should also cover Flags
        _v.append(lambda x: '"%d"' % x)
    else: # also covers floats which should be wrapped in Rounder (see __str__)
        _v.append(lambda x: '"%s"' % x)
del _k, _v
attr_csv_struct[u'enchantPoints'][2] = lambda x: ( # can be None
    '"None"' if x is None else f'"{x:d}"')

#------------------------------------------------------------------------------
# Mod Element Sets ------------------------------------------------------------
class MelSet(object):
    """Set of mod record elements."""

    def __init__(self,*elements):
        # Filter out None, produced by static deciders like fnv_only
        self.elements = [e for e in elements if e is not None]
        self.defaulters = {}
        self.loaders = {}
        self.formElements = set()
        for element in self.elements:
            element.getDefaulters(self.defaulters,'')
            element.getLoaders(self.loaders)
            element.hasFids(self.formElements)
        for sig_candidate in self.loaders:
            if len(sig_candidate) != 4 or not isinstance(sig_candidate, bytes):
                raise SyntaxError(f"Invalid signature '{sig_candidate}': "
                    f"Signatures must be bytestrings and 4 bytes in length.")

    def getSlotsUsed(self):
        """This function returns all of the attributes used in record instances
        that use this instance."""
        # Use a set to discard duplicates - saves memory!
        return list({s for element in self.elements
                     for s in element.getSlotsUsed()})

    def check_duplicate_attrs(self, curr_rec_sig):
        """This will raise a SyntaxError if any record attributes occur in more
        than one element. However, this is sometimes intended behavior (e.g.
        Oblivion's MreSoun uses it to upgrade an old subrecord to a newer one).
        In such cases, set the MreRecord class variable _has_duplicate_attrs to
        True for that record type (after carefully checking that there are no
        unwanted duplicate attributes)."""
        all_slots = set()
        for element in self.elements:
            element_slots = set(element.getSlotsUsed())
            duplicate_slots = sorted(all_slots & element_slots)
            if duplicate_slots:
                raise SyntaxError(
                    u'Duplicate element attributes in record type %s: %s. '
                    u'This most likely points at an attribute collision, make '
                    u'sure to choose unique attribute names!' % (
                        curr_rec_sig, repr(duplicate_slots)))
            all_slots.update(element_slots)

    def getDefault(self,attr):
        """Returns default instance of specified instance. Only useful for
        MelGroup and MelGroups."""
        return self.defaulters[attr].getDefault()

    def dumpData(self,record, out):
        """Dumps state into out. Called by getSize()."""
        for element in self.elements:
            try:
                element.dumpData(record,out)
            except:
                bolt.deprint(u'Error dumping data: ', traceback=True)
                bolt.deprint(u'Occurred while dumping '
                             u'<%(eid)s[%(signature)s:%(fid)s]>' % {
                    u'signature': record.rec_str,
                    u'fid': f'{record.fid}',
                    u'eid': (record.eid + u' ') if getattr(record, u'eid',
                                                           None) else u'',
                })
                for attr in record.__slots__:
                    attr1 = getattr(record, attr, None)
                    if attr1 is not None:
                        bolt.deprint(u'> %s: %r' % (attr, attr1))
                raise

    def mapFids(self, record, mapper, save_fids=False):
        """Maps fids of subelements."""
        for element in self.formElements:
            element.mapFids(record, mapper, save_fids)

    def with_distributor(self, distributor_config):
        # type: (dict) -> MelSet
        """Adds a distributor to this MelSet. See _MelDistributor for more
        information. Convenience method that avoids having to import and
        explicitly construct a _MelDistributor. This is supposed to be chained
        immediately after MelSet.__init__.

        :param distributor_config: The config to pass to the distributor.
        :return: self, for ease of construction."""
        # Make a copy, that way one distributor config can be used for multiple
        # record classes. _MelDistributor may modify its parameter, so not
        # making a copy wouldn't be safe in such a scenario.
        from .advanced_elements import _MelDistributor # avoid circular import
        distributor = _MelDistributor(distributor_config.copy())
        self.elements += (distributor,)
        distributor.getLoaders(self.loaders)
        distributor.set_mel_set(self)
        return self

#------------------------------------------------------------------------------
# Records ---------------------------------------------------------------------
#------------------------------------------------------------------------------
class MreRecord(object):
    """Generic Record. flags1 are game specific see comments."""
    subtype_attr = {b'EDID': u'eid', b'FULL': u'full', b'MODL': u'model'}
    flags1_ = bolt.Flags.from_names(
        # {Sky}, {FNV} 0x00000000 ACTI: Collision Geometry (default)
        ( 0,'esm'), # {0x00000001}
        # {Sky}, {FNV} 0x00000004 ARMO: Not playable
        ( 2,'isNotPlayable'), # {0x00000004}
        # {FNV} 0x00000010 ????: Form initialized (Runtime only)
        ( 4,'formInitialized'), # {0x00000010}
        ( 5,'deleted'), # {0x00000020}
        # {Sky}, {FNV} 0x00000040 ACTI: Has Tree LOD
        # {Sky}, {FNV} 0x00000040 REGN: Border Region
        # {Sky}, {FNV} 0x00000040 STAT: Has Tree LOD
        # {Sky}, {FNV} 0x00000040 REFR: Hidden From Local Map
        # {TES4} 0x00000040 ????:  Actor Value
        # Constant HiddenFromLocalMap BorderRegion HasTreeLOD ActorValue
        ( 6,'borderRegion'), # {0x00000040}
        # {Sky} 0x00000080 TES4: Localized
        # {Sky}, {FNV} 0x00000080 PHZD: Turn Off Fire
        # {Sky} 0x00000080 SHOU: Treat Spells as Powers
        # {Sky}, {FNV} 0x00000080 STAT: Add-on LOD Object
        # {TES4} 0x00000080 ????:  Actor Value
        # Localized IsPerch AddOnLODObject TurnOffFire TreatSpellsAsPowers  ActorValue
        ( 7,'turnFireOff'), # {0x00000080}
        ( 7,'hasStrings'), # {0x00000080}
        # {Sky}, {FNV} 0x00000100 ACTI: Must Update Anims
        # {Sky}, {FNV} 0x00000100 REFR: Inaccessible
        # {Sky}, {FNV} 0x00000100 REFR for LIGH: Doesn't light water
        # MustUpdateAnims Inaccessible DoesntLightWater
        ( 8,'inaccessible'), # {0x00000100}
        # {Sky}, {FNV} 0x00000200 ACTI: Local Map - Turns Flag Off, therefore it is Hidden
        # {Sky}, {FNV} 0x00000200 REFR: MotionBlurCastsShadows
        # HiddenFromLocalMap StartsDead MotionBlur CastsShadows
        ( 9,'castsShadows'), # {0x00000200}
        # New Flag for FO4 and SSE used in .esl files
        ( 9, 'eslFile'), # {0x00000200}
        # {Sky}, {FNV} 0x00000400 LSCR: Displays in Main Menu
        # PersistentReference QuestItem DisplaysInMainMenu
        (10,'questItem'), # {0x00000400}
        (10,'persistent'), # {0x00000400}
        (11,'initiallyDisabled'), # {0x00000800}
        (12,'ignored'), # {0x00001000}
        # {FNV} 0x00002000 ????: No Voice Filter
        (13,'noVoiceFilter'), # {0x00002000}
        # {FNV} 0x00004000 STAT: Cannot Save (Runtime only) Ignore VC info
        (14,'cannotSave'), # {0x00004000}
        # {Sky}, {FNV} 0x00008000 STAT: Has Distant LOD
        (15,'visibleWhenDistant'), # {0x00008000}
        # {Sky}, {FNV} 0x00010000 ACTI: Random Animation Start
        # {Sky}, {FNV} 0x00010000 REFR light: Never fades
        # {FNV} 0x00010000 REFR High Priority LOD
        # RandomAnimationStart NeverFades HighPriorityLOD
        (16,'randomAnimationStart'), # {0x00010000}
        # {Sky}, {FNV} 0x00020000 ACTI: Dangerous
        # {Sky}, {FNV} 0x00020000 REFR light: Doesn't light landscape
        # {Sky} 0x00020000 SLGM: Can hold NPC's soul
        # {Sky}, {FNV} 0x00020000 STAT: Use High-Detail LOD Texture
        # {FNV} 0x00020000 STAT: Radio Station (Talking Activator)
        # {FNV} 0x00020000 STAT: Off limits (Interior cell)
        # Dangerous OffLimits DoesntLightLandscape HighDetailLOD CanHoldNPC RadioStation
        (17,'dangerous'), # {0x00020000}
        (18,'compressed'), # {0x00040000}
        # {Sky}, {FNV} 0x00080000 STAT: Has Currents
        # {FNV} 0x00080000 STAT: Platform Specific Texture
        # {FNV} 0x00080000 STAT: Dead
        # CantWait HasCurrents PlatformSpecificTexture Dead
        (19,'cantWait'), # {0x00080000}
        # {Sky}, {FNV} 0x00100000 ACTI: Ignore Object Interaction
        (20,'ignoreObjectInteraction'), # {0x00100000}
        # {???} 0x00200000 ????: Used in Memory Changed Form
        # {Sky}, {FNV} 0x00800000 ACTI: Is Marker
        (23,'isMarker'), # {0x00800000}
        # {FNV} 0x01000000 ????: Destructible (Runtime only)
        (24,'destructible'), # {0x01000000} {FNV}
        # {Sky}, {FNV} 0x02000000 ACTI: Obstacle
        # {Sky}, {FNV} 0x02000000 REFR: No AI Acquire
        (25,'obstacle'), # {0x02000000}
        # {Sky}, {FNV} 0x04000000 ACTI: Filter
        (26,'navMeshFilter'), # {0x04000000}
        # {Sky}, {FNV} 0x08000000 ACTI: Bounding Box
        # NavMesh BoundingBox
        (27,'boundingBox'), # {0x08000000}
        # {Sky}, {FNV} 0x10000000 STAT: Show in World Map
        # {FNV} 0x10000000 STAT: Reflected by Auto Water
        # {FNV} 0x10000000 STAT: Non-Pipboy
        # MustExitToTalk ShowInWorldMap NonPipboy',
        (28,'nonPipboy'), # {0x10000000}
        # {Sky}, {FNV} 0x20000000 ACTI: Child Can Use
        # {Sky}, {FNV} 0x20000000 REFR: Don't Havok Settle
        # {FNV} 0x20000000 REFR: Refracted by Auto Water
        # ChildCanUse DontHavokSettle RefractedbyAutoWater
        (29,'refractedbyAutoWater'), # {0x20000000}
        # {Sky}, {FNV} 0x40000000 ACTI: GROUND
        # {Sky}, {FNV} 0x40000000 REFR: NoRespawn
        # NavMeshGround NoRespawn
        (30,'noRespawn'), # {0x40000000}
        # {Sky}, {FNV} 0x80000000 REFR: MultiBound
        # MultiBound
        (31,'multiBound'), # {0x80000000}
    )
    __slots__ = ('header', '_rec_sig', 'fid', 'flags1', 'size', 'flags2',
                 'changed', 'data', 'inName')
    isKeyedByEid = False
    #--Set at end of class data definitions.
    type_class = {}
    # Record types that have a complex child structure (e.g. CELL), are part of
    # such a complex structure (e.g. REFR) or are the file header (TES3/TES4)
    simpleTypes = set()
    # Maps subrecord signatures to a set of record signatures that can contain
    # those subrecords
    subrec_sig_to_record_sig = defaultdict(set)

    def __init__(self, header, ins=None, *, do_unpack=False):
        self.header = header
        self._rec_sig = header.recType
        self.fid = header.fid # type: utils_constants.FormId
        self.flags1 = MreRecord.flags1_(header.flags1)
        self.size = header.size
        self.flags2 = header.flags2
        self.changed = False
        self.data = None
        self.inName = ins and ins.inName
        if ins: # Load data from ins stream
            file_offset = ins.tell()
            ##: Couldn't we toss this data if we unpacked it? (memory!)
            self.data = ins.read(self.size, self._rec_sig,
                                 file_offset=file_offset)
            if not do_unpack: return  #--Read, but don't analyze.
            if self.__class__ is MreRecord: return  # nothing to be done
            ins_ins, ins_size = ins.ins, ins.size
            ins_debug_offset = ins.debug_offset
            try: # swap the wrapped io stream with our (decompressed) data
                ins.ins, ins.size = self.getDecompressed()
                ins.debug_offset = ins_debug_offset + file_offset
                self.loadData(ins, ins.size, file_offset=file_offset)
            finally: # restore the wrapped stream to read next record
                ins.ins, ins.size = ins_ins, ins_size
                ins.debug_offset = ins_debug_offset

    def __repr__(self):
        reid = (self.eid + ' ') if getattr(self, 'eid', None) else ''
        return f'<{reid}[{self.rec_str}:{self.fid}]>'

    def group_key(self): ##: we need an MreRecord mixin - too many ifs
        """Return a key for indexing the record on the parent (MobObjects)
        grup."""
        record_id = self.fid
        if self.isKeyedByEid and record_id.is_null():
            record_id = self.eid
        return record_id

    def getTypeCopy(self):
        """Return a copy of self - MreRecord base class will find and return an
        instance of the appropriate subclass (!)"""
        subclass = MreRecord.type_class[self._rec_sig]
        myCopy = subclass(self.header)
        myCopy.data = self.data
        with ModReader(self.inName, *self.getDecompressed()) as reader:
            myCopy.loadData(reader, reader.size) # load the data to rec attrs
        myCopy.changed = True
        myCopy.data = None
        return myCopy

    def mergeFilter(self, modSet):
        """This method is called by the bashed patch mod merger. The
        intention is to allow a record to be filtered according to the
        specified modSet. E.g. for a list record, items coming from mods not
        in the modSet could be removed from the list."""

    def getDecompressed(self, *, __unpacker=int_unpacker):
        """Return (decompressed if necessary) record data wrapped in BytesIO.
        Return also the length of the data."""
        if not self.flags1.compressed:
            return io.BytesIO(self.data), len(self.data)
        decompressed_size, = __unpacker(self.data[:4])
        decomp = zlib.decompress(self.data[4:])
        if len(decomp) != decompressed_size:
            raise exception.ModError(self.inName,
                f'Mis-sized compressed data. Expected {decompressed_size}, '
                f'got {len(decomp)}.')
        return io.BytesIO(decomp), len(decomp)

    def loadData(self, ins, endPos, *, file_offset=0):
        """Loads data from input stream. Called by load().

        Subclasses should actually read the data, but MreRecord just skips over
        it (assuming that the raw data has already been read to itself. To force
        reading data into an array of subrecords, use iterate_subrecords())."""
        ins.seek(endPos)

    def iterate_subrecords(self, mel_sigs=frozenset()):
        """This is for MreRecord only. Iterates over data unpacking them to
        subrecords - DEPRECATED.

        :type mel_sigs: set"""
        if not self.data: return
        with ModReader(self.inName, *self.getDecompressed()) as reader:
            _rec_sig_ = self._rec_sig
            readAtEnd = reader.atEnd
            while not readAtEnd(reader.size,_rec_sig_):
                subrec = SubrecordBlob(reader, _rec_sig_, mel_sigs)
                if not mel_sigs or subrec.mel_sig in mel_sigs:
                    yield subrec

    def updateMasters(self, masterset_add):
        """Updates set of master names according to masters actually used."""
        raise exception.AbstractError(
            f'updateMasters called on skipped type {self.rec_str}')

    def setChanged(self,value=True):
        """Sets changed attribute to value. [Default = True.]"""
        self.changed = value

    def getSize(self):
        """Return size of self.data, after, if necessary, packing it."""
        if not self.changed: return self.size
        #--Pack data and return size.
        out = io.BytesIO()
        self.dumpData(out)
        self.data = out.getvalue()
        if self.flags1.compressed:
            dataLen = len(self.data)
            comp = zlib.compress(self.data,6)
            self.data = struct_pack('=I', dataLen) + comp
        self.size = len(self.data)
        self.setChanged(False)
        return self.size

    def dumpData(self,out):
        """Dumps state into data. Called by getSize(). This default version
        just calls subrecords to dump to out."""
        if self.data is None:
            raise exception.StateError(f'Dumping empty record. [{self.inName}:'
                                       f' {self.rec_str} {self.fid}]')
        for subrecord in self.iterate_subrecords():
            subrecord.packSub(out, subrecord.mel_data)

    @property
    def rec_str(self):
        """Decoded record signature - **only** use in exceptions and co."""
        return sig_to_str(self._rec_sig)

    def dump(self,out):
        """Dumps all data to output stream."""
        if self.changed:
            raise exception.StateError(f'Data changed: {self.rec_str}')
        if not self.data and not self.flags1.deleted and self.size > 0:
            raise exception.StateError(
                f'Data undefined: {self.rec_str} {self.fid}')
        #--Update the header so it 'packs' correctly
        self.header.size = self.size
        if self._rec_sig != b'GRUP':
            self.header.flags1 = self.flags1
            self.header.fid = self.fid
        out.write(self.header.pack_head())
        if self.size > 0: out.write(self.data)

    #--Accessing subrecords ---------------------------------------------------
    def getSubString(self, mel_sig_):
        """Returns the (stripped) string for a zero-terminated string
        record."""
        # Common subtype expanded in self?
        attr = MreRecord.subtype_attr.get(mel_sig_)
        value = None # default
        # If not MreRecord, then we will have info in data.
        if self.__class__ != MreRecord:
            if attr not in self.__slots__: return value
            return getattr(self, attr)
        for subrec in self.iterate_subrecords(mel_sigs={mel_sig_}):
            value = bolt.cstrip(subrec.mel_data)
            break
        return decoder(value)

    # Classmethods ------------------------------------------------------------
    @classmethod
    def parse_csv_line(cls, csv_fields, index_dict, reuse=False):
        if not reuse:
            attr_dict = {att: attr_csv_struct[att][0](csv_fields[dex]) for
                         att, dex in index_dict.items()}
            return attr_dict
        else:
            for att, dex in index_dict.items():
                index_dict[att] = attr_csv_struct[att][0](csv_fields[dex])
            return index_dict

#------------------------------------------------------------------------------
class MelRecord(MreRecord):
    """Mod record built from mod record elements."""
    #--Subclasses must define as MelSet(*mels)
    melSet: MelSet = None
    rec_sig: bytes = None
    # If set to False, skip the check for duplicate attributes for this
    # subrecord. See MelSet.check_duplicate_attrs for more information.
    _has_duplicate_attrs = False
    __slots__ = ()

    def __init__(self, header, ins=None, *, do_unpack=False):
        if self.__class__.rec_sig != header.recType:
            raise ValueError(f'Initialize {type(self)} with header.recType '
                             f'{header.recType}')
        for element in self.__class__.melSet.elements:
            element.setDefault(self)
        MreRecord.__init__(self, header, ins, do_unpack=do_unpack)

    def getTypeCopy(self):
        """Return a copy of self - we must be loaded, data will be discarded"""
        myCopy = copy.deepcopy(self)
        myCopy.changed = True
        myCopy.data = None
        return myCopy

    @classmethod
    def validate_record_syntax(cls):
        """Performs validations on this record's definition."""
        if not cls._has_duplicate_attrs:
            cls.melSet.check_duplicate_attrs(cls.rec_sig)

    @classmethod
    def getDefault(cls, attr):
        """Returns default instance of specified instance. Only useful for
        MelGroup and MelGroups."""
        return cls.melSet.getDefault(attr)

    def loadData(self, ins, endPos, *, file_offset=0):
        """Loads data from input stream."""
        loaders = self.__class__.melSet.loaders
        # Load each subrecord
        ins_at_end = ins.atEnd
        while not ins_at_end(endPos, self._rec_sig):
            sub_type, sub_size = unpackSubHeader(ins, self._rec_sig,
                                                 file_offset=file_offset)
            try:
                loader = loaders[sub_type]
                try:
                    loader.load_mel(self, ins, sub_type, sub_size,
                                    self._rec_sig, sub_type) # *debug_strs
                    continue
                except Exception as er:
                    error = er
            except KeyError: # loaders[sub_type]
                # Wrap this error to make it more understandable
                error = f'Unexpected subrecord: {self.rec_str}.' \
                        f'{sig_to_str(sub_type)}'
            file_offset += ins.tell()
            bolt.deprint(self.error_string('loading', file_offset, sub_size,
                                           sub_type))
            if isinstance(error, str):
                raise exception.ModError(ins.inName, error)
            raise exception.ModError(ins.inName, f'{error!r}') from error

    def error_string(self, op, file_offset=None, sub_size=None, sub_type=None):
        """Return a human-readable description of this record to use in error
        messages."""
        msg = f'Error {op} {self.rec_str} record and/or subrecord: ' \
              f'{self.fid}\n  eid = {getattr(self, "eid", "<<NO EID>>")}'
        if file_offset is None:
            return msg
        li = [msg, f'subrecord = {sig_to_str(sub_type)}',
              f'subrecord size = {sub_size}', f'file pos = {file_offset}']
        return '\n  '.join(li)

    def dumpData(self,out):
        """Dumps state into out. Called by getSize()."""
        self.__class__.melSet.dumpData(self,out)

    def mapFids(self, mapper, save_fids):
        """Applies mapper to fids of sub-elements. Will replace fid with mapped value if save == True."""
        self.__class__.melSet.mapFids(self, mapper, save_fids)

    def updateMasters(self, masterset_add):
        """Updates set of master names according to masters actually used."""
        masterset_add(self.fid)
        for element in self.__class__.melSet.formElements:
            element.mapFids(self, masterset_add)
