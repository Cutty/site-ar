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

import argparse
import atexit
import collections
import errno
import logging
import os
import sys
import textwrap


from . import dbdrv
from . import prefs
from . import ui_top
from . import util
from .dbdrv import SQLiteDriver as DBDriver
from .exceptions import DBError


log = logging.getLogger(__name__)


DEFAULT_DB_PATH = 'data.db'
DEFAULT_DL_PATH = 'dl'
DEFAULT_LOG_HISTORY = 100
DEFAULT_SITE_TYPE = 'auction'


# Use OrderedDict for printing help.
# Note: 'generic' type must be index 0 (see dbdrv.apply_schema).
SITE_TYPE_ID_GENERIC = 0
SITE_TYPES = collections.OrderedDict((
    ('generic',
        (
            '.ui_top.UIMain',
            None,
            'Generic DB viewer (can not be used during DB creation)'
        )
    ),
    ('auction',
        (
            '.auction.ui_auction.AuctionUI',
            '.auction.schema.get_schema',
            'Auction sites'
        )
    )
))

_EPILOG_PAD = 24
_EPILOG_MAX_LEN = 79


def init_logger(args):
    """Initialize UI, stream (stderr) and file logging handlers.

    Args:
        args: argparse.Namespace parsed args.

    Returns:
        UILoggingHandler that has already been attached to the application
        RootLogger.

    Note:
        The file logging handler is not returned.  If the caller wants to
        explicitly close it, it will have to be retrieved from
        RootLogger.handlers.
    """
    root_log = logging.getLogger()

    fmt = '%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s'
    formatter = logging.Formatter(fmt)

    if args.verbose is True:
        level = logging.DEBUG
    else:
        level = logging.INFO

    ui_lh = ui_top.UILoggingHandler(max_history=args.log_history)
    ui_lh.setFormatter(formatter)
    ui_lh.setLevel(level)
    root_log.addHandler(ui_lh)

    if args.log_file is not None:
        path = os.path.realpath(os.path.expanduser(args.log_file))
        file_lh = logging.FileHandler(path)
        file_lh.setFormatter(formatter)
        file_lh.setLevel(level)
        root_log.addHandler(file_lh)
        # Just going to let the OS close the file on exit.

    root_log.setLevel(level)

    return ui_lh


def dump_args(args):
    """Print args to log.debug.

    Args:
        args: argparse.Namespace parsed args.
    """
    log.debug('Starting main with args...')
    for key, value in args._get_kwargs():
        log.debug('arg: {}={}'.format(key, repr(value)))


def help_epilog():
    """Generate epilog for argparse help"""
    ret = ['Available site types:',]
    for name, (_, _, desc) in SITE_TYPES.iteritems():
        if desc is None:
            desc = ''
        desc = textwrap.wrap(desc, _EPILOG_MAX_LEN - _EPILOG_PAD)
        if len(desc) == 0:
            desc = ['',]

        ret.append('{:<{pad}s}{}'.format(name, desc.pop(0), pad=_EPILOG_PAD))
        while len(desc):
            ret.append('{:<{pad}s}{}'.format('', desc.pop(0), pad=_EPILOG_PAD))

    return '\n'.join(ret)


def parse_args(argv=None):
    """Parse command line arguments.

    Args:
        argv: optional (argv if defined must have the program name as argv[0].

    Returns:
        argparse.Namespace parsed args.
    """
    if argv is not None:
        prog = os.path.basename(argv[0])
    else:
        prog = 'site-ar'

    parser = argparse.ArgumentParser(prog=prog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description='site archival tool',
            epilog=help_epilog())

    arg_help = 'Site customization type (default: {})'.format(
            DEFAULT_SITE_TYPE)
    parser.add_argument('--site-type', type=str, default=None,
            metavar='SITE_TYPE', choices=SITE_TYPES.keys(),
            help=arg_help)

    arg_help = 'Download directory (default: {})'.format(DEFAULT_DL_PATH)
    parser.add_argument('--dl-dir', type=str, default=DEFAULT_DL_PATH,
            metavar='PATH', help=arg_help)

    parser.add_argument('--reset-prefs', action='store_true',
            help='Reset preferences')

    parser.add_argument('--dump-prefs', action='store_true',
            help='Dump preferences and exit')

    arg_help = ('Max lines retained in UI log window (default {}).'
            '  Use 0 for unlimited')
    arg_help = arg_help.format(DEFAULT_LOG_HISTORY)
    parser.add_argument('--log-history', type=int,
            default=DEFAULT_LOG_HISTORY, metavar='LINES',
            help=arg_help)

    parser.add_argument('--log-hist-dump', action='store_true',
            help='Dump log history on exit')

    parser.add_argument('--log-file', type=str, default=None,
            metavar='PATH', help='log to file')

    parser.add_argument('-v', '--verbose', action='store_true',
            help='Verbose logging')

    parser.add_argument('db', type=str, nargs='?', default=DEFAULT_DB_PATH,
            help='path to database (default {})'.format(DEFAULT_DB_PATH))

    args = parser.parse_args(argv)
    return args


def main_atexit(log_handler, db):
    """Disconnect UI from log_handler and close db.

    Used with atexit to ensure database connection is closed during abnormal
    program termination.

    Args:
        log_handler: .ui_top.UILogginHandler.
        db: .dbdrv.DBDriver.
    """
    # Does nothing on a normal exit but if an unhandled exception occurs
    # (like KeyboardInterrupt) this will let the log line appear in the
    # console.
    log_handler.disconnect_ui()
    log.info('closing database...')
    db.close()


def main(argv=None):
    """Run main application.

    Args:
        argv: optional (argv if defined must have the program name as argv[0].
    """
    args = parse_args(argv)

    log_handler = init_logger(args)
    if args.verbose is True:
        dump_args(args)

    # Create and test download directory.
    dl_dir = os.path.realpath(os.path.expanduser(args.dl_dir))
    util.makedirs(dl_dir)
    util.require_dir(dl_dir)
    if os.access(dl_dir, os.W_OK) is False:
        raise IOError(errno.EACCES, 'Permission denied', dl_dir)

    site_type = args.site_type
    is_new_db = not os.path.isfile(args.db)

    # New db can not use generic (need initial schema) or set default if None.
    #if not os.path.isfile(args.db):
    if is_new_db:
        if site_type is None:
            site_type = DEFAULT_SITE_TYPE
        elif site_type == 'generic':
            err = 'Can not use \'generic\' site type when creating database'
            raise ValueError(err)

    # Waiting until as many checks as possible before opening (and possibly
    # creating) the database.
    db = DBDriver(args.db)
    atexit.register(main_atexit, log_handler, db)

    if is_new_db:
        # This could go in the if block above.  Keeping here to be with the
        # other schema_id code.
        schema_id = SITE_TYPES.keys().index(site_type)
        # generic site type not allowed and will have failed above.
        use_generic = False
    else:
        # Peek at the database schema_id.
        schema_id, _ = dbdrv.get_schema_id_ver(db)

        if schema_id == 0:
            # This database either was made by this program or failed before
            # applying the schema.
            raise DBError('opened database with 0 schema id')

        try:
            db_site_type = SITE_TYPES.keys()[schema_id]
        except IndexError:
            raise DBError('database using unknown schema id: {:#04x}'.format(
                    db_sid))

        use_generic = False
        if site_type is None:
            site_type = db_site_type
        elif site_type == 'generic':
            use_generic = True
            site_type = db_site_type
        elif site_type != db_site_type:
            err = ('arg site-type: \'{}\' is not compatible with '
                    'db site_type: \'{}\'')
            err = err.format(site_type, db_site_type)
            raise ValueError(err)
        else:
            site_type = db_site_type

    ui_path, schema_path, _ = SITE_TYPES[site_type]
    if use_generic is True:
        ui_path, _, _ = SITE_TYPES['generic']

    _, get_schema = util.get_mod_obj(schema_path)
    schema = get_schema()
    dbdrv.apply_schema(db, schema_id, schema)

    _, ui_cls = util.get_mod_obj(ui_path)
    # Dynamic module loading at the top level should be done by now.  It is
    # up the module containing ui_cls to ensure all site specific preferences
    # have been added.

    # The database should have a preferences table here as well.  Load prefs,
    # reset and/or dump depending on args.
    prefs.set_db(db)
    if args.reset_prefs is False:
        prefs.load()
    prefs.save()

    if args.dump_prefs is True:
        prefs.dump()
        return

    ui = ui_cls(db, dl_dir, log_handler)
    ui.start()

    if args.log_hist_dump is True:
        for msg in log_handler.get_history_str(only_sh_emit=True):
            # StreamHandler in UILoggingHandler outputs to stderr by default.
            # Do the same here.
            sys.stderr.write(msg + '\n')
