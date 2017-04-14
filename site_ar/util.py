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
import importlib
import copy
import errno
import logging
import md5
import os
import re
import shlex


log = logging.getLogger(__name__)
_root_log = logging.getLogger()


PRICEFIND = re.compile(r'[+-]?[0-9]{1,3}(?:,?[0-9]{3})*\.[0-9]{2}')
PRICEFMT = '{:,.02f}'
CSV_PRICEFMT = '\'' + PRICEFMT

_NOINDEX = object()


def flush_log():
    """Calls flush if exists all handlers in RootLogger."""
    for handler in _root_log.handlers:
        if hasattr(handler, 'flush'):
            handler.flush()


def get_mod_obj(path, package=None):
    """Gets module and object from package using absolute or relative path.

    Args:
        path: string python style path of module and object to import.
        package (optional): string of package to anchor the import.  If
            omitted __package__ of this function will be used.

    Returns:
        tuple of (module, object).  module and/or object may be None if not
            found.
    """
    if path is None or path == '':
        return None, None

    if package is None:
        package = __package__

    path = path.rsplit('.', 1)
    mod = path[0]
    obj = getindex(path, 1, None)

    try:
        mod = importlib.import_module(mod, package=package)
    except (ImportError, ValueError):
        mod = None

    if mod is not None and obj is not None:
        obj = getattr(mod, obj, None)
    else:
        # mod is None but obj may not be.
        obj = None

    return mod, obj


def makedirs(path, mode=0777):
    """Recursive make directories.  Does not warn if path exists and is a
    directory.

    Args:
        path: string path to create.
        mode: mode used during create.

    Returns:
        None
    """
    try:
        os.makedirs(path, mode)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def require_dir(path):
    """Checks if path is a directory or raises exception.

    Args:
        path: string path to check

    Returns:
        True if directory.  If path exists but not a directory raises IOError
            with ENODEV else ENOENT as arguments.
    """
    if os.path.isdir(path):
        return True

    if os.path.exists(path):
        raise IOError(errno.ENODEV, 'Not a directory', path)
    else:
        raise IOError(errno.ENOENT, 'No such file or directory', path)


def unused_path(prefix, ext, max_tries=100):
    """Finds an unused path using a counter in the format
    <prefex>[-<DDDD>]<ext>.

    Args:
        prefex: path prefix string.
        ext: path extension string.
        max_tries (optional): int max number of paths to try before failing
            (default 100).

    Returns:
        unused string path or None if max_tries exceeded.
    """
    path = '{}{}{}'.format(prefix, os.path.extsep, ext)
    if not os.path.exists(path):
        return path

    for x in range(max_tries):
        path = '{}-{:04d}{}{}'.format(prefix, x, os.path.extsep, ext)
        if not os.path.exists(path):
            return path

    return None


def md5_path(data, directory, ext):
    """Creates a path based on md5 hash of data.  Uses unused_path to ensure a
    unique path is created.

    Args:
        data: string data for md5 hash.
        directory: string path of directory to find path.
        ext: path extension string.

    Returns:
        string path or None if could not be found.
    """
    if ext.find(os.path.sep) != -1:
        raise ValueError('extension must not contain {}'.format(os.path.sep))

    digest = md5.md5(data).hexdigest()
    prefix = os.path.join(directory, digest)

    path = unused_path(prefix, ext)
    if path is not None:
        path = os.path.basename(path)
    return path


def append_ext(path, ext):
    """Appends extension to path.

    Args:
        path: string path.
        ext: string extension.

    Returns:
        Joined path string.
    """
    if ext is None or ext == '':
        return path

    if os.path.splitext(path)[1] == '':
        if ext[0] != os.path.extsep:
            ext = os.path.extsep + ext
        path += ext
    return path


def tryopen(name, *args, **kwargs):
    """Tries to open file.  Suppresses IOError and OSError and logs a
    warning if file can not be opened.

    Args:
        *args/**kwargs: args to pass to open.

    Returns:
        file or None if could not open.
    """
    try:
        f = open(name, *args, **kwargs)
        return f
    except (IOError, OSError) as e:
        log.warn('could not open: \'{}\' from exception {}'.format(
                name, exception_string(e)))

    return None


def test_create(path):
    """Test if a path can be created.  Path will not be created.

    Args:
        path: string path to test.

    Returns:
        0 if OK. EISDIR, ENOENT, EEXIST or EACCES on error.
    """
    path = os.path.realpath(os.path.expanduser(path))
    direc = os.path.split(path)[0]

    if os.path.isdir(path):
        return errno.EISDIR
    elif not os.path.isdir(direc):
        return errno.ENOENT
    elif os.path.exists(path):
        if os.access(path, os.W_OK):
            return errno.EEXIST
        else:
            return errno.EACCES
    elif not os.access(direc, os.W_OK):
        # Here we know direc is actually a directory and the path does not
        # exist.  Check if we have write access to the directory to create a
        # file.
        return errno.EACCES
    else:
        return 0


def wsclean(s):
    """Replaces all blocks of whitespace and replaces with single space."""
    return re.sub(r'\s+', ' ', s.strip())


def getindex(obj, index, default=_NOINDEX):
    """Get index from object with default.

    Args:
        obj: object to index.
        index: int index.
        default (optional): default if index is out of range.  If omitted and
            index if out of range IndexError will be raised.

    Returns:
        indexed object or default.
    """
    try:
        return obj[index]
    except IndexError:
        if default != _NOINDEX:
            return default
        raise


def allindex(obj, value):
    """Return list of all indexes of value in obj."""
    ret = []
    index = 0
    while True:
        try:
            index = obj.index(value, index)
            ret.append(index)
            index += 1
        except ValueError:
            break

    return ret


def listreplace(lst, old, new, count=None):
    """Replace all values in list.

    Args:
        lst: list of operate on.
        old: value to replace.
        new: value to replace with.
        count: max number of values to replace.

    Returns:
        lst, does not make a copy.
    """
    indices = allindex(lst, old)
    if count is not None:
        indices = indices[:count]
    for index in indices:
        lst[index] = new
    return lst


def listremove(lst, value):
    """Remove value from lst without error."""
    try:
        lst.remove(value)
    except ValueError:
        pass


def listfindremove(lst, pattern):
    """Case insensitive search in list of strings, removing and returning
    first match.

    Args:
        lst: list of strings.
        pattern: case insensitive pattern to search for.

    Returns:
        If found match and lst is modified, None if not.
    """
    if any([not isinstance(x, basestring) for x in lst]):
        raise TypeError('lst must only contain strings')

    pattern = pattern.lower()
    match = [x for x in lst if x.lower().find(pattern) != -1]
    match = getindex(match, 0, None)
    if match is not None:
        listremove(lst, match)
    return match


def mapping_price_fmt(mapping, key='price', copy_mapping=True, fmt=PRICEFMT):
    """Format price in mapping.

    Args:
        mapping: mapping to operate on.
        key: string key containing price value.
        copy_mapping (optional): True to copy mapping before format.
        fmt (optional): price format to use.

    Returns:
        mapping or copy of mapping.
    """
    if mapping.has_key(key) and isinstance(mapping[key], (int, float)):
        if copy_mapping is True:
            # Keep original mapping price as a number.
            mapping = copy.deepcopy(mapping)
        mapping[key] = fmt.format(mapping[key])
    return mapping


def boolstr(value):
    """Value to bool handling True/False strings."""
    if isinstance(value, basestring):
        if value.lower() == 'false':
            return False

        try:
            value = float(value)
        except ValueError:
            pass

    return bool(value)


def isnonestr(value):
    """Returns True if value is None or basestring."""
    return value is None or isinstance(value, basestring)


def terms_split(terms):
    """Split quoted terms into list and strip quotes.  Unmatched quotes will
    raise a ValueError.

    Example the string:
    The quick 'brown fox' "jumps over" the "lazy dog"

    will return:
    ['The', 'quick', 'brown fox', 'jumps over', 'the', 'lazy dog']

    Args:
        terms: string of quoted terms.
    """
    if terms in ('', u'', None):
        return list()
    elif isinstance(terms, basestring):
        terms = shlex.split(terms)
    elif isinstance(terms, collections.Iterable):
        terms = list(terms)
    else:
        err = '\'{}\' object is not str/unicode/iterable'.format(
                type(terms).__name__)
        raise TypeError(err)

    terms = [str(x).strip('"\'') for x in terms]

    return terms


def exception_string(e):
    """Return an interpreter like error string from an exception."""
    s = type(e).__name__

    # If e is not a built-in exception add module to exception name.
    if hasattr(e, '__module__'):
        s = '{}.{}'.format(e.__module__, s)

    # If e has a message add ':' and message.
    if str(e) != '':
        s = '{}: {}'.format(s, str(e))

    return s
