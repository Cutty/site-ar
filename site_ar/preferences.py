# Copyright (c) 2016 Joe Vernaci
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import logging


from . import UNSET
from . import util
from .exceptions import  PreferencesError, PreferencesKeyError, \
        PreferencesTypeError


log = logging.getLogger(__name__)


def add_prefs_schema_up(db):
    """Preferences key,value schema up template."""
    db.add_table(
            'preferences',
            db.col('key', 'TEXT', primary_key=True),
            db.col('value', 'TEXT'))


def add_prefs_schema_down(db):
    """Preferences key,value schema down template."""
    db.del_table('preferences')


class PrefStore(object):
    def __init__(self, key, value_type, required, default, value, dirty,
            on_change, user_data, help):
        """Initializer for preference storage object.

        Args:
            key: string preference key.
            value_type: value type or function that can parse value string.
            required: bool if preference must have value.
            default: default value.
            value: initialized value.
            dirty: bool tracking if preference is dirty compared to database.
            on_change: callback on value change in the with arguments
                preference, new value, user_data.
            user_data: on_change user data.
            help: help string.
        """
        self.key = key
        self.value_type = value_type
        self.required = required
        self.default = default
        self.dirty = dirty
        self.on_change = on_change
        self.user_data = user_data
        self.help = help

        self._value = None
        self.value = value

    def __str__(self):
        return ('PrefStore(key={} value_type={} required={} default={} '
                'value={} dirty={})'.format(self.key, self.value_type,
                self.required, self.default, self.value, self.dirty))


    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value
        # Notify on_change if set.
        if self.on_change is not None:
            self.on_change(self, value, self.user_data)


class Preferences(object):
    def __init__(self, db=None):
        """Preference manager initializer.  db is not required since so may be
        instantiated in global scope before the database is ready.

        Args:
            db (optional): DBDriver object.
        """
        self.loaded = False
        self.data = {}
        self.db = db

    def __getitem__(self, item):
        return self.get(item)

    def __setitem__(self, item, value):
        return self.set(item, value)

    def _check_key(self, key):
        if key.lower() not in self.data.keys():
            raise PreferencesKeyError('preferences key {} does not exist'.
                    format(key))
        return key.lower()

    def set_db(self, db):
        """Set DBDriver object."""
        self.db = db

    def _load_key_value(self, key, value):
        """Load key value pair into preferences.  This is called when loading
        values from the database.  The two except blocks below are non-fatal
        as they could be due to code changes and we don't want to crash.
        """
        try:
            # Use set to do type checking.
            self.set(key, value)
            # set will mark this data as dirty but it really is clean.
            self.data[key.lower()].dirty = False
        except PreferencesKeyError:
            # A preference was removed or has not been loaded yet,
            # preferences table may need a cleaning.
            log.info('key {} found in database but not in '
                    'preferences'.format(key))
        except PreferencesTypeError:
            # A preference type has changed so reset back to the default.
            pref = self.data[key.lower()]
            type_name = getattr(pref.value_type, '__name__',
                    repr(pref.value_type))
            log.warn('invalid value \'{}\' for key {} of type {}'.format(
                    value, key, type_name))
            log.warn('setting default for key {}'.format(key))
            pref.value = pref.default
            pref.dirty = False

    def _load_key(self, key):
        """Load key from database into preferences."""
        sql = 'SELECT * FROM preferences WHERE key=\'{}\''.format(
                key.lower())
        db_data = self.db.execall(sql)

        if len(db_data) != 0:
            key, value = db_data[0]
            self._load_key_value(key, value)

    def add(self, key, value_type, required, default=UNSET, on_change=None,
            user_data=None, help=None):
        """Add preference definition into manager.

        Args:
            key: case-insensitive unique string preference key.  Actual case
                sensitivity preserved for display purposes.
            value_type: value type or function that can parse value string.
            required: bool if preference must have value.
            default (optional): preference default value.  If required is False
                this may be set to UNSET.
            on_change: callback on value change in the with arguments
                preference, new value, user_data.
            user_data: on_change user data.
            help: help string.

        Returns:
            None.
        """
        if not callable(value_type):
            raise PreferencesError('value_type must be callable')
        elif value_type is bool:
            value_type = util.boolstr

        if required and default is UNSET:
            raise PreferencesError('required preferences must have a default')

        if key.lower() in self.data.keys():
            msg = 'duplicate (case insensitive) key {}'.format(key)
            raise PreferencesError(msg)

        # check default value for correct type.
        if default is not UNSET:
            try:
                default = value_type(default)
            except (PreferencesTypeError, TypeError, ValueError):
                type_name = getattr(value_type, '__name__', repr(value_type))
                raise PreferencesTypeError(
                        'invalid default value \'{}\' for type {}'.format(
                        default, type_name))

        self.data[key.lower()] = PrefStore(key=key, value_type=value_type,
                required=required, default=default, value=default,
                dirty=True, on_change=on_change, user_data=user_data,
                help=help)

        # If preferences are added after the database ia loaded check for
        # an existing value.  This could happen if 'on demand' imports are
        # used.
        if self.loaded:
            self._load_key(key)

    def keys(self):
        """List of case-insensitive unique key strings."""
        return [x.key for x in self.data.itervalues()]

    def prefs(self):
        """List of preference key, value pairs."""
        return [(x.key, x.value) for x in self.data.values()]

    def iterprefs(self):
        """Iterator for prefs."""
        prefiter = self.data.itervalues()
        for pref in prefiter:
            yield (pref.key, pref.value)

    def get_pref(self, key):
        """Preference storage object by key."""
        return self.data[key]

    def get(self, key):
        """Preference value by key."""
        key = self._check_key(key)
        return self.data[key].value

    def convert(self, key_pref, value):
        """Convert value for perference using value_type.

        Args:
            key_pref: key string or PrefStore.
            value: string value to convert.

        Returns:
            converted and validated value.
        """
        if isinstance(key_pref, PrefStore):
            pref = key_pref
        else:
            pref = self.data[self._check_key(key_pref)]

        if pref.required is True and value is UNSET:
            raise PreferencesTypeError(
                    'preference {} must have a value'.format(pref.key))

        if value is not UNSET:
            try:
                value = pref.value_type(value)
            except (PreferencesTypeError, TypeError, ValueError):
                type_name = getattr(pref.value_type, '__name__',
                        repr(pref.value_type))
                raise PreferencesTypeError(
                        'invalid value \'{}\' for type {}'.format(value,
                        type_name))

        return value

    def set(self, key, value):
        """Set perference value by key."""
        log.debug('set called on {} with {}({})'.format(key,
                type(value).__name__, value))

        pref = self.data[self._check_key(key)]
        value = self.convert(pref, value)

        log.debug('set value converted to {}({})'.format(
                type(value).__name__, value))

        # avoid unnecessary writes to db.
        if pref.value != value:
            pref.value = value
            pref.dirty = True

        return value

    def reset(self, key):
        """Reset preference to its default."""
        key = self._check_key(key)
        pref = self.data[key]
        if pref.value != pref.default:
            pref.value = pref.default
            pref.dirty = True
        return pref.default

    def load(self):
        """Load all preferences from database."""
        sql = 'SELECT * FROM preferences'
        db_data = self.db.execall(sql)

        for key, value in db_data:
            self._load_key_value(key, value)

        # All loaded preferences are now marked as clean from _load_key_value.

        # Any preference that have a value of UNSET should be marked as
        # clean since it must not have an entry in the database.
        for pref in self.data.itervalues():
            if pref.value is UNSET:
                pref.dirty = False

        self.loaded = True

    def save(self, key=None):
        """Save preferences to database.  Database must have correct tables
        in place.

        Args:
            key (optional): key string to save.  If omitted all preferences
                will be saved.
        """
        if key is not None:
            key = self._check_key(key)
            keys = (key,)
        else:
            keys = self.data.keys()

        for key in keys:
            value = self.data[key].value
            if value is not UNSET:
                sql = ('INSERT OR REPLACE INTO preferences (key, value) '
                        'VALUES (\'{}\', \'{}\');')
                self.db.execute(sql.format(key, value))
            else:
                sql = 'DELETE FROM preferences WHERE key = \'{}\';'
                self.db.execute(sql.format(key))

        self.db.commit()

        for pref in self.data.itervalues():
            pref.dirty = False

    def dump(self):
        """Dump all preferences to log."""
        for pref in self.data.itervalues():
            log.debug(pref)
