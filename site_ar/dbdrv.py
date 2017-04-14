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

import collections
import functools
import logging
import operator
import sqlite3
import textwrap


from . import UNSET
from .exceptions import DBDriverError, MigrationError, RowDOError
from .util import terms_split


log = logging.getLogger(__name__)


class SQLiteColumn(object):
    def __init__(self, name, sql_type, **kwargs):
        """Initializer for abstract column type for sqlite schema.

        Args:
            name: name of column.
            sql_type: string type as understood by sqlite.
            **kwargs: keyword args optionally containing keys: primary_key,
                unique, not_null, check, or autoincrement.  Each key is a bool
                to add the corresponding keywords/constrains.
        """
        foreign_key = kwargs.get('foreign_key', None)
        if foreign_key is not None:
            self._str = 'FOREIGN KEY({}) REFERENCES {}'.format(name,
                    foreign_key)
            return

        args = [name, sql_type]

        if kwargs.get('primary_key', False):
            args.append('PRIMARY KEY')

        if kwargs.get('unique', False):
            args.append('UNIQUE')

        if kwargs.get('not_null', False):
            args.append('NOT NULL')

        if kwargs.get('check', False):
            args.append('CHECK')

        if kwargs.get('autoincrement', False):
            args.append('AUTOINCREMENT')

        self._str = ' '.join(args)

    def __str__(self):
        return self._str


class SQLiteDriver(object):
    def __init__(self, path):
        """Initializer for higher-level SQLite interface.

        Args:
            path: string path to database.
        """
        self._path = path
        self._conn = None
        self.rdo_ctors = {}
        self.open()

        # Alias to the SQLiteColumn class.
        self.col = SQLiteColumn

    def _check_conn(self):
        """Check and raise exception if not connected to database."""
        if not self._conn:
            raise DBDriverError('Not connected to database: {}'.format(
                    self._path))

    def open(self):
        """Open connection to database."""
        self._conn = sqlite3.connect(self._path)
        # Ideally this object would track if there are any outstanding
        # transactions (python 3.2+ does this).  For now just enable
        # automatic commits.  Disable this if needed during development.
        self._conn.isolation_level = None

    def close(self):
        """Close connection to database.  Does nothing if already closed."""
        if self._conn:
            self._conn.close()

    def cursor(self):
        """Returns a new cursor to the database."""
        self._check_conn()
        return self._conn.cursor()

    def execute(self, sql, *args, **kwargs):
        """Create a cursor and execute a sql statement.

        Args:
            sql: sql command.
            *args: Parameterized arguments used as SQL literals.
            **kwargs: If kwargs contains key row_factory the value will be set
                as the cursor row_factory.

        Returns:
            sqlite3.Cursor after SQL statement execution.
        """
        cursor = self.cursor()
        if kwargs.has_key('row_factory'):
            cursor.row_factory = kwargs['row_factory']

        cursor.execute(sql, *args)
        return cursor

    def execall(self, sql, *args, **kwargs):
        """Create a cursor and fetch all results from a sql statement.

        Args:
            sql: sql command.
            *args: Parameterized arguments used as SQL literals.
            **kwargs: If kwargs contains key row_factory the value will be set
                as the cursor row_factory.

        Returns:
            List results from SQL statement execution.
        """
        return self.execute(sql, *args, **kwargs).fetchall()

    def sr_execute(self, sql, *args, **kwargs):
        """Create a cursor and execute a sql statement using default row
        factory.

        Args:
            sql: sql command.
            *args: Parameterized arguments used as SQL literals.

        Returns:
            sqlite3.Cursor after SQL statement execution with row_factory set
            to sqlite3.Row.
        """
        kwargs['row_factory'] = sqlite3.Row
        return self.execute(sql, *args, **kwargs)

    def sr_execall(self, sql, *args, **kwargs):
        """Create a cursor and fetch all rows from a sql statement using
        default row factory.

        Args:
            sql: sql command.
            *args: Parameterized arguments used as SQL literals.

        Returns:
            List of sqlite3.Row objects from SQL statement execution.
        """
        kwargs['row_factory'] = sqlite3.Row
        return self.execall(sql, *args, **kwargs)

    def commit(self):
        """Commit to database"""
        self._check_conn()
        self._conn.commit()

    def get_version(self):
        """Returns version stored in PRAGMA user_version"""
        cursor = self.execute('PRAGMA user_version')
        return cursor.fetchone()[0]

    def set_version(self, version):
        """Stores version in PRAGMA user_version

        Args:
            version: 31-bit unsigned int.

        Returns:
            version
        """
        version = int(version)
        # user_version is a signed 32 bit number, need to change to a
        # negative value to use bit 31.  Python int may also be larger
        # 32 bits so just check bounds.
        if version < 0 or version > ((1 << 31) - 1):
            raise ValueError('version {} out of range'.format(hex(version)))

        self.execute('PRAGMA user_version = {}'.format(version))
        return version

    def get_schema(self):
        """Returns list of sql statements for database schema."""
        sql = '''\
            SELECT sql FROM
                (SELECT * FROM sqlite_master UNION ALL
                SELECT * FROM sqlite_temp_master)
            WHERE type=='table'
            ORDER BY tbl_name, type DESC, name'''
        return self.execall(sql)

    def get_schema_str(self):
        """Returns single string of sql statements for database schema."""
        schema = self.get_schema()
        return '\n'.join(map(operator.itemgetter(0), schema))

    def tables(self):
        """Returns tuple of table names in database."""
        # Using single quotes on this sql causes vim to treat the rest of
        # the as a string.
        sql = """\
            SELECT name FROM sqlite_master
            WHERE type IN ('table','view')
            AND name NOT LIKE 'sqlite_%'"""
        ret = self.execall(sql)
        return zip(*ret)[0]

    def add_table(self, name, *cols):
        """Creates new table in database.

        Args:
            name: table name string.
            *cols: positional arguments of SQLiteColumn objects defining
                table.
        """
        col_str = textwrap.dedent(',\n    '.join(map(str, cols)))
        col_str = ',\n    '.join(map(str, cols))
        sql = 'CREATE TABLE {} (\n    {}\n);'.format(name, col_str)
        self.execute(sql)

    def del_table(self, name):
        """Drops existing table from database.

        Args:
            name: table name string.
        """
        sql = 'DROP TABLE {};'.format(name)
        self.execute(sql)

    def ins_rdo(self, table, rdo, or_replace=False):
        """Insert RowDO into table.

        Args:
            table: table name string.
            rdo: RowDO object to insert.
            or_replace (optional): bool to add 'OR REPLACE' to SQL statement.
                table requires primary key which can not autoincrement.
        """
        if not isinstance(rdo, RowDO):
            raise TypeError('rdo must be type RowDO')
        cols, values = zip(*rdo.set_items())
        sql = ['INSERT']
        if or_replace:
            sql += ['OR', 'REPLACE']
        sql += ['INTO', str(table), str(cols), 'VALUES']
        sql.append('({})'.format(', '.join(['?',] * len(values))))
        sql = ' '.join(sql)
        self.execute(sql, values)

    def get_single_column(self, column, table, where=None):
        """Gets column of data from table.

        Args:
            column: column name string.
            table: table name string.
            where (optional): SQL statement for WHERE clause expression.

        Returns:
            tuple of results.
        """
        sql = 'SELECT {} FROM {}'.format(column, table)
        if where is not None:
            sql += ' WHERE {}'.format(where)

        data = self.execall(sql)
        if len(data) != 0:
            data = zip(*data)[0]
        return data

    def row_iter(self, sql, *args):
        """Create an iterator of sqlite3.Row objects.

        Args:
            sql: sql command.
            *args: Parameterized arguments used as SQL literals.

        Returns:
            iterator of sqlite3.Row objects.  Each .next will execute a
            fetchone on the cursor.
        """
        cursor = self.sr_execute(sql, *args)
        return iter(cursor.fetchone, None)

    def rdo_iter(self, rdo_constructor, sql, *args):
        """Create an iterator of RowDO objects.

        Args:
            rdo_constructor: RowDO constructor for the table.
            sql: sql command.
            *args: Parameterized arguments used as SQL literals.

        Returns:
            iterator of RowDO objects.  Each .next will execute a fetchone
            on the cursor.
        """
        for row in self.row_iter(sql, *args):
            yield rdo_constructor().from_row(row)

    def _exec_search_iter(self, table, sql, nocase=True, rdo=True):
        """Create an iterator from SELECT results.

        Args:
            table: table name string.
            sql: sql command.
            nocase (optional): True to disable case sensitivity.
            rdo (optional): True to return RowDO, False to return sqlite3.Row
                objects.

        Returns:
            iterator of objects.  Each .next will execute a fetchone on the
            cursor.
        """
        if nocase is True:
            sql += ' COLLATE NOCASE'

        if rdo is True:
            rdo_constructor = self.rdo_ctors[table]
            return self.rdo_iter(rdo_constructor, sql)
        else:
            return self.row_iter(sql)

    def search_iter(self, table, where, nocase=True, rdo=True):
        """Create an iterator from SELECT results.

        Args:
            table: table name string.
            where: SQL statement for WHERE clause expression.
            nocase (optional): True to disable case sensitivity.
            rdo (optional): True to return RowDO, False to return sqlite3.Row
                objects.

        Returns:
            iterator of objects.  Each .next will execute a fetchone on the
            cursor.
        """
        sql = 'SELECT * FROM {} WHERE {}'.format(table, where)
        return self._exec_search_iter(table, sql, nocase, rdo)

    @staticmethod
    def column_like(column, terms):
        """Create a LIKE clause statement.

        Args:
            column: column name string.
            terms: list of terms for LIKE clause statement.

        Returns:
            SQL statement string.
        """
        return ['{} LIKE \'%{}%\''.format(column, x) for x in terms]

    def search_terms_iter(self, table, column, all_terms=None, any_terms=None,
            not_terms=None, nocase=True, rdo=True):
        """Create an iterator of search results.

        Note: All *_terms will be ANDed together.

        Args:
            table: table name string.
            column: column name string.
            all_terms (optional): list of all terms for LIKE clause statement.
            any_terms (optional): list of any terms for LIKE clause statement.
            not_terms (optional): list of not terms for LIKE clause statement.
            nocase (optional): True to disable case sensitivity.
            rdo (optional): True to return RowDO, False to return sqlite3.Row
                objects.

        Returns:
            iterator of objects.  Each .next will execute a fetchone on the
            cursor.
        """
        if not isinstance(table, basestring) or table == '':
            raise DBDriverError('invalid table: \'{}\''.format(table))
        elif not self.rdo_ctors.has_key(table):
            raise DBDriverError('unknown table: \'{}\''.format(table))

        if not isinstance(column, basestring) or column == '':
            raise DBDriverError('invalid column: \'{}\''.format(column))

        all_terms = self.column_like(column, terms_split(all_terms))
        any_terms = self.column_like(column, terms_split(any_terms))
        not_terms = self.column_like(column, terms_split(not_terms))

        sql = []
        if len(all_terms):
            sql.append('({})'.format(' AND '.join(all_terms)))

        if len(any_terms):
            sql.append('({})'.format(' OR '.join(any_terms)))

        if len(not_terms):
            sql.append('NOT ({})'.format(' OR '.join(not_terms)))

        sql = ' AND '.join(sql)
        sql = 'SELECT * FROM {} WHERE {}'.format(table, sql)

        return self._exec_search_iter(table, sql, nocase, rdo)


class Migration(object):
    version = None
    def __init__(self):
        """Simple migration class to hold version and database function calls
        to upgrade/downgrade each version.  Each migration version should
        subclass this and each schema should have a list of these objects."""
        if self.version is None:
            msg = 'Migration {} does not have a version'.format(
                    type(self).__name__)
            raise MigrationError(msg)

    def up(self, db): pass
    def down(self, db): pass


class RowDO(object):
    # can't use positional args as it would prevent them from named args
    # (i.e. column names).
    # args: name, cols, defaults, protected
    def __init__(self, *args, **kwargs):
        """Initializer for row ORM objects.

        Args:
            *args: Either 1 or 4 positional arguments.  1 argument must be
                RowDO to make a copy of.  4 arguments are in the order:
                * name: RowDO name string (typically same as table name).
                * cols: tuple of strings of column names.
                * defaults: tuple of default values for each column.
                * protected: tuple of string of protected columns.  These
                    column can not be set after initialization.
            **kwargs: keyword arguments of columns to initialize.
        """
        if len(args) == 1:
            rdo = args[0]
            if not isinstance(rdo, self.__class__):
                raise TypeError('expected type: \'{}\''.format(
                        type(self).__name__))
            self._init_from_rowdo(rdo)
            return
        elif len(args) == 4:
            name, cols, defaults, protected = args
        else:
            err = '__init__() takes 2 or 5 positional arguments ({} given)'
            err = err.format(len(args) + 1)
            raise TypeError(err)

        if defaults is None:
            defaults = (None,) * len(cols)

        if protected is None:
            protected = tuple()

        if len(cols) != len(defaults):
            raise RowDOError('cols/defaults size mismatch')

        self.name = name
        self.protected = protected
        self.cols = cols

        # Don't inherent as some of the functions don't make sense in
        # this context.
        self._data = collections.OrderedDict(zip(cols, defaults))

        self._locked = True

        for k,v in kwargs.iteritems():
            if k not in cols:
                raise KeyError('column {} not in table {}'.format(k,
                        self._tblname))
            self[k] = v

    def _init_from_rowdo(self, rdo):
        """Copy data from existing RowDO"""
        self.name = rdo.name
        self.protected = rdo.protected
        self.cols = rdo.cols
        self._data = collections.OrderedDict(rdo._data)
        self._locked = True

    def __setitem__(self, key, value):
        if key not in self.cols:
            raise KeyError('column {} not in table {}'.format(key, self.name))
        if key in self.protected and self._locked:
            raise AttributeError('{} is protected'.format(key))
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __repr__(self):
        items = ', '.join(['{}={}'.format(k,v) for k,v in zip(self.keys(),
                self.values())])
        return '{}({})'.format(self.name, items)

    def __str__(self):
        return str(self.values())

    def keys(self):
        """Tuple of RowDO keys (columns)"""
        return tuple(self._data.keys())

    def has_key(self, key):
        """True if RowDO has key (column)"""
        return self._data.has_key(key)

    def values(self, keys=None):
        """Tuple of values in order.

        Args:
            keys (optional): List of keys to return values for.  If not set
                will return all values in order as RowDO.keys.

        Returns:
            tuple of values.
        """
        if keys is None:
            return tuple(self._data.values())
        return tuple([self._data[x] for x in keys])

    def items(self):
        """List of RowDO (key, value) pairs."""
        return self._data.items()

    def set_items(self):
        """List of RowDO (key, value) pairs that have been set (are not UNSET
        sentinel)."""
        return tuple([(k,v) for k,v in self.items() if v != UNSET])

    def from_row(self, row):
        """Set values from sqlite3.Row.

        Args:
            row: sqlite3.Row with same len of columns as RowDO object.

        Returns:
            self.
        """
        if not isinstance(row, sqlite3.Row):
            raise TypeError('row must be type sqlite3.Row')

        if len(row) != len(self.cols):
            raise RowDOError('incorrect row size')

        # No need to unlock since we're altering _data directly.
        self._data = collections.OrderedDict(zip(self.cols, row))

        return self


class RowDOFactory(object):
    def __init__(self, rdo_ctors):
        """Initializer for RowDO factory.  It provides a select number of
        methods with the same declarations as SQLiteDriver for Migration
        objects to use.  This allows the RowDO constructors and schema
        to be generated from the same migration objects in lockstep.

        Args:
            rdo_ctors: dict to store the rdo_constructors.
        """
        self.rdo_ctors = rdo_ctors

    def col(self, name, sql_type, **kwargs):
        # Only pass the column data the row factory will care about back to
        # add_table.  If sql_type is None this is a not a real column.
        # Return all Nones and add_table will filter it out.
        if sql_type is None:
            return (None,) * 3

        return (name, kwargs.get('default', UNSET),
                kwargs.get('protected', False))

    def add_table(self, name, *cols):
        cols = [x for x in cols if x[0] is not None]
        col_names, defaults, _ = zip(*cols)
        protected = tuple([x[0] for x in cols if x[2]])
        partial_rdo = functools.partial(RowDO, name, col_names, defaults,
                protected)
        self.rdo_ctors[name] = partial_rdo

    def del_table(self, name):
        self.rdo_ctors.pop(name)


def get_schema_id_ver(db):
    """Get database user_version and split into (schema_id, schema_version).

    Args:
        db: DBDriver object.

    Returns:
        tuple of int schema_id and int version.
    """
    user_version = db.get_version()
    return user_version >> 16, user_version & 0xFFFF


def set_schema_id_ver(db, schema_id, version):
    """Join schema_id and schema_version and set in database user_version.

    Args:
        db: DBDriver object.
        schema_id: 15-bit unsigned int.
        version: 16-bit unsigned int.

    Returns:
        tuple of int schema_id and int version.
    """
    if version < 0 or version > ((1 << 16) - 1):
        raise ValueError('version {} out of range'.format(hex(version)))
    if schema_id < 0 or schema_id > ((1 << 15) - 1):
        raise ValueError('schema_id {} out of range'.format(hex(schema_id)))

    user_version = (schema_id << 16) | version
    db.set_version(user_version)
    return schema_id, version


def apply_schema(db, schema_id, schema, version=None):
    """Apply schema to database.  Required even if the schema exists
    to generate the RowDO constructors.

    Args:
        db: DBDriver object.
        schema_id: 15-bit unsigned int.
        schema: list of Migration objects.
        version (optional): version to migrate to.  If not set will migrate
            to the highest version.
    """
    if schema_id <= 0:
        raise ValueError('schema_id must be > 0')

    # Sanity on schema ordering and versions.
    schema_vers = list(map(operator.attrgetter('version'), schema))

    if schema_vers != sorted(schema_vers):
        raise MigrationError('Invalid schema ordering')

    if sum(schema_vers) != sum(range(1, len(schema_vers) + 1)):
        if schema_vers[0] != 1:
            raise MigrationError('Schema does not start at 1')
        raise MigrationError('Schema does not increment by 1')

    if version is None:
        version = len(schema)
    elif version < 0 or version > len(schema):
        raise MigrationError('Invalid version {}'.format(version))

    db_sid, db_ver = get_schema_id_ver(db)
    if db_sid != 0 and db_sid != schema_id:
        err = 'database schema_id: {} != schema_id: {}'.format(
                db_sid, schema_id)
        raise MigrationError(err)

    if db_ver != version:
        if db_ver < version:
            mig_func = 'up'
            migrations = schema[db_ver:version]
            offset = 0
        else:
            mig_func = 'down'
            migrations = schema[version:db_ver]
            migrations.reverse()
            offset = -1

        for mig in migrations:
            getattr(mig, mig_func)(db)
            #db_ver = db.set_version(mig.version + offset)
            _, db_ver = set_schema_id_ver(db, schema_id,
                    mig.version + offset)

    # Easiest to build the row objects after the schema up/downgrade is done.
    # Need to use the migration objects as they have extra data that is not
    # in the sql schema (i.e. protected).
    row_factory = RowDOFactory(db.rdo_ctors)
    for mig in schema[:version]:
        mig.up(row_factory)
