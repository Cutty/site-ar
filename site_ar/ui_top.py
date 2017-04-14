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

import datetime
import logging
import operator
import os
import sqlite3
import textwrap
import traceback
import unicodedata
import urwid


from . import dbdrv
from . import export
from . import prefs
from . import ui_base
from . import ui_dialog
from . import util
from .exceptions import UIError, DBDriverError, ExportError


log = logging.getLogger(__name__)


_L_ARROW = unicodedata.lookup('LEFTWARDS ARROW')
_D_ARROW = unicodedata.lookup('DOWNWARDS ARROW')
_U_ARROW = unicodedata.lookup('UPWARDS ARROW')
_R_ARROW = unicodedata.lookup('RIGHTWARDS ARROW')


# changes on restart.
prefs.add('ui.log.view.lines', int, True, default=20,
        help='Number of log lines to show in main UI')


class UITreeWidget(urwid.TreeWidget):
    """UI style TreeWidget.  Ensures on_expand/on_collapse events are called
    on corresponding nodes.  Designed to work on nodes backed by RowDO
    objects."""

    def __init__(self, node):
        """Initializer.

        Args:
            node: corresponding urwid.TreeNode.
        """
        self._expanded = False

        super(UITreeWidget, self).__init__(node)
        self._w = urwid.AttrMap(self._w, {None: 'body'}, {None: 'focus'})

        self.expanded = False

    @property
    def expanded(self):
        return self._expanded

    @expanded.setter
    def expanded(self, value):
        # Note: urwid.TreeWidget will set self.expanded to True and then later
        # UITreeWidget will set it back to False.  The tree widget nodes
        # should be able to handle on_expand/on_collapse quickly (at
        # least during init).
        node = self.get_node()
        if hasattr(node, 'on_expand') and value is True \
                and self._expanded is False:
            node.on_expand()
        elif hasattr(node, 'on_collapse') and value is False \
                and self._expanded is True:
            node.on_collapse()

        self._expanded = value

    def get_ui(self):
        """Get UIMain object."""
        node = self.get_node()
        if hasattr(node, 'get_ui'):
            return node.get_ui()
        elif hasattr(node, 'ui'):
            return node.ui
        else:
            return None

    def get_display_text(self):
        """Get display text to be used as line in tree view.  Defers to
        node."""
        return self.get_node().get_display_text()

    def get_node_type(self):
        """Get node type string, used to generate title for detailed mapping
        dialog.  Defers to node."""
        return self.get_node().get_type()

    def get_node_detail_mapping(self):
        """Get detail mapping from node."""
        node = self.get_node()
        if hasattr(node, 'get_detail_mapping'):
            return self.get_node().get_detail_mapping()
        return None

    def show_node_detail_mapping(self, key):
        """Display node detail mapping as UIViewMappingDialog.  Mapped by
        default to space key."""
        node_mapping = self.get_node_detail_mapping()
        if node_mapping is None:
            return key

        node_type = self.get_node_type()
        ui = self.get_node().get_ui()
        view_mapping = UIViewMappingDialog(ui, node_type, node_mapping,
                ui.loop.widget)
        view_mapping.start()

    def selectable(self):
        return True

    def keypress(self, size, key):
        """Catch space key to show node detailed mapping."""
        key = super(UITreeWidget, self).keypress(size, key)
        if key == ' ':
            return self.show_node_detail_mapping(key)
        else:
            return key


class UIViewMappingDialog(object):
    """View mapping dialog.  Each entry in the mapping is displayed as its own
    line of selectable text using the format '{:<{width}} | {}' where width
    is calculated as the maximum of all keys in the mapping."""

    def __init__(self, ui, mapping_name, mapping, bottom_w,
            width=(urwid.RELATIVE, 80), max_height=(urwid.RELATIVE, 80)):
        """Initializer.

        Args:
            ui: UIMain.
            mapping_name: string to used to generate title.
            mapping: key value data to display, must support item iteration.
            bottom_w: widget to display dialog over.  Typically the current
                view but may be another dialog if nested.
            width (optional): urwid dimension tuple.
            max_height (optional): urwid dimension tuple, mapping data is
                scrollable if it can not be displayed at once.
        """
        # dict or list of items.
        if hasattr(mapping, 'keys'):
            keys = mapping.keys()
        else:
            keys = [x for x in zip(*mapping)[0]]

        max_key_len = max([len(str(x)) for x in keys])

        if hasattr(mapping, 'iteritems'):
            mapping = mapping.iteritems()
        elif hasattr(mapping, 'items'):
            mapping = mapping.items()

        fmt = '{:<{width}} | {}'
        text = [ui_base.SelectableText(fmt.format(k, v, width=max_key_len),
                wrap=urwid.CLIP) for k,v in mapping]
        text = [urwid.AttrMap(x, {None: 'body'}, {None: 'focus'})
                for x in text]
        body = ui_base.ListBoxBase(urwid.SimpleListWalker(text))

        dfw = ui_dialog.DialogFrameWidget(ui, body,
                title='{} detailed view'.format(mapping_name))
        dfw.exit_on_esc = True
        dfw.exit_on_enter = True
        dfw.exit_on_space = True

        # This will change if the layout of DialogBase changes or
        # UIViewMappingDialog changes the header or footer.
        required_rows = len(keys) + ui_dialog.DIALOG_BASE_ROWS_COLS[0]

        # See if we can fit the rows to the exact number required to show
        # everything in the mapping.
        height = ui_base.min_height(required_rows, max_height,
                ui.screen_rows)

        self.ui = ui
        self.dialog = ui_dialog.DialogBase(ui, dfw, bottom_w, width=width,
                height=height)

    def start(self):
        """Start dialog, exiting with esc, space or enter keys."""
        if self.ui.enter_dialog():
            self.dialog.start()
            self.ui.exit_dialog()


class UITreeListBox(ui_base.TreeListBoxBase):
    """Data browser tree view.  Provides export and update functionality on
    currently focused node."""

    def _get_callable_attr_node(self, attr):
        """Find first callable attribute on the currently focused node.

        Args:
            attr: string attribute to search for.

        Returns:
            urwid.TreeNode.
        """
        node = ui_base.tree_attr_find(self.focus_position, attr,
                find_first=True)
        if node is None:
            err = 'could not find node callable attribute \'{}\''
            raise AttributeError(err.format(attr))

        return node

    def get_export_node(self):
        """Find first node with export method."""
        return self._get_callable_attr_node('export')

    def get_update_node(self):
        """Find first node with update method."""
        return self._get_callable_attr_node('update')

    @property
    def export_title(self):
        """Create a export title based on the export_title attribute.  If not
        available a generic one is created from the node's class name and
        id."""
        node = self.get_export_node()
        export_title = getattr(node, 'export_title', None)
        if export_title is None:
            export_title = 'Export node: {} ({})'.format(
                    type(node).__name__, hex(id(node)))
        return export_title

    def export(self, exporter):
        """Call export on currently focused node.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
        """
        log.debug('export called on: {}'.format(self))
        node = self.get_export_node()

        log.debug('sending export to: {}'.format(node))
        node.export(exporter)

    def _update_on_node(self, node, try_all=False):
        """Call update/update_all on currently focused node.  If try_all is
        True update_all will be called if available but update will be used as
        a fallback.

        Args:
            node: urwid.TreeNode to call function on.
            try_all (optional): bool to try calling update_all before update.
        """
        if try_all is True and hasattr(node, 'update_all'):
            node.update_all()
        else:
            node.update()

    def update(self):
        """Call update on currently focused node."""
        log.debug('update called on: {}'.format(self))
        self._update_on_node(self.get_update_node())

    def update_all(self):
        """Call update_all/update on currently focused node."""
        log.debug('update all called on: {}'.format(self))
        self._update_on_node(self.get_update_node(), try_all=True)


class UISearchListBox(ui_base.ListBoxBase):
    """Generic search result data view.  Provides displaying detailed view
    dialog on results if support is provided by child class."""

    def __init__(self, ui, iterable, text_attr='body',
            text_focus_attr='focus'):
        """Initializer.

        Args:
            ui: UIMain.
            iterable: search results iterable, values should be string to
                display in the listbox.
            attr (optional): default attr key.
            focus_attr (optional): focus attr key.
        """
        self.ui = ui

        if isinstance(text_attr, basestring):
            text_attr = {None: text_attr}
        if isinstance(text_focus_attr, basestring):
            text_focus_attr = {None: text_focus_attr}

        data = self.init_result_data(iterable, text_attr, text_focus_attr)

        super(UISearchListBox, self).__init__(data)

    def init_result_data(self, iterable, text_attr='body',
            text_focus_attr='focus'):
        """Generator to convert iterable of strings into SelectableText
        widgets.

        Args:
            iterable: search results iterable, values should be string to
                display in the listbox.
            attr (optional): default attr key.
            focus_attr (optional): focus attr key.
        """
        for value in iterable:
            if isinstance(value, basestring):
                value = ui_base.SelectableText(value)
                value = urwid.AttrMap(value, text_attr, text_focus_attr)
                yield value
            elif isinstance(value, urwid.Widget):
                yield value
            else:
                err = ('\'{}\' object is not str, unicode or instance of '
                        'urwid.Widget').format(type(value).__name__)
                raise TypeError(err)

    def show_result_detail_mapping(self, key):
        """Show detail mapping for currently focused node if get_detail_mapping
        is provided by class.

        Args:
            key: key used to activate detail mapping.

        Returns:
            None if detailed mapping displayed, key if not.
        """
        # If subclassing define get_detail_mapping and get_type to display a
        # UIViewMappingDialog for the focused search result.
        if not hasattr(self, 'get_detail_mapping') \
                or not hasattr(self, 'get_type'):
            return key

        result_mapping = self.get_detail_mapping()

        result_type = '{} search result'.format(self.get_type())

        view_mapping = UIViewMappingDialog(self.ui, result_type,
                result_mapping, self.ui.loop.widget)
        view_mapping.start()

    def keypress(self, size, key):
        """Catch space key to show detailed mapping of currently focused
        search result."""
        key = super(UISearchListBox, self).keypress(size, key)
        if key == ' ':
            return self.show_result_detail_mapping(key)
        else:
            return key


class UIRowDOSearchListBox(UISearchListBox):
    """RowDO search result data view."""

    rdo_name = None
    export_keys = None

    def __init__(self, ui, iterable, text_attr='body',
            text_focus_attr='focus'):
        """Initializer.

        Args:
            ui: UIMain.
            iterable: iterable of RowDO objects.
            attr (optional): default attr key.
            focus_attr (optional): focus attr key.
        """
        super(UIRowDOSearchListBox, self).__init__(ui, iterable, text_attr,
                text_focus_attr)

    def format_rdo(self, rdo):
        """Generic rdo display text.  Overload this to customize how RowDO
        objects are displayed in search results."""
        return repr(rdo)

    def init_result_data(self, iterable, text_attr='body',
            text_focus_attr='focus'):
        """Generator to convert iterable of RowDO (typically created by
        db.search_terms_iter) into SelectableText widgets.  The RowDO object
        is attached to the widget to be used for displaying detailed mappings.

        Args:
            iterable: iterable of RowDO objects.
            attr (optional): default attr key.
            focus_attr (optional): focus attr key.
        """
        try:
            for rdo in iterable:
                if not isinstance(rdo, dbdrv.RowDO):
                    err = 'iterable must contain only dbdrv.RowDO'
                    raise TypeError(err)
                if self.rdo_name is not None \
                        and self.rdo_name != rdo.name:
                    err = ('iterable must contain only \'{}\' '
                            'dbdrv.RowDO').format(self.rdo_name)
                    raise TypeError(err)

                text = self.format_rdo(rdo)
                value = ui_base.SelectableText(text)

                # Attach table row to text node (used for
                # get_detail_mapping).
                value.rdo = rdo

                value = urwid.AttrMap(value, text_attr, text_focus_attr)
                yield value
        except sqlite3.Error as e:
            log.warn('search error: {}'.format(util.exception_string(e)))
            raise StopIteration

    def get_rdo(self, widget):
        """Get original RowDO object from widget."""
        if isinstance(widget, (urwid.AttrMap, urwid.AttrWrap)):
            widget = widget.original_widget
        if not isinstance(widget, urwid.Widget):
            raise TypeError('widget must be type urwid.Widget')
        return widget.rdo

    def get_focus_rdo(self):
        """Get RowDO object from currently focused widget."""
        widget = self.get_focus()[0]
        if widget is None:
            raise ValueError('no widget in focus')
        return self.get_rdo(widget)

    def get_type(self):
        """Get currently focused RowDO name."""
        rdo = self.get_focus_rdo()
        return '{} row'.format(rdo.name)

    def get_detail_mapping(self):
        """Get currently focused RowDO detailed mapping."""
        return self.get_focus_rdo()

    def get_export_keys(self, contents):
        """Get intersection of RowDO keys in contents and self.export_keys.
        This assumes all RowDO objects in contents are of the same type."""
        keys = self.get_rdo(contents[0]).keys()
        return export.key_intersection(self.export_keys, keys,
                self.get_type())

    @property
    def export_title(self):
        return 'Export search results'

    def export(self, exporter):
        """Export search results.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
        """
        log.debug('export called on: {}'.format(self))
        contents = self.contents()

        keys = self.get_export_keys(contents)

        log.debug('exporting keys: {}({})'.format(type(keys).__name__, keys))

        exporter.write_hdr(keys)
        exporter.write_blank()

        for widget in ui_base.listbox_contents_iter(contents):
            # Not modifying rdo with the generic implementation, no need to
            # make a copy.
            rdo = self.get_rdo(widget)
            values = rdo.values(keys)
            exporter.write_row(values)


class TableNode(ui_base.WeakRefTreeRootNodeList,
        ui_base.RowDOChildrenExportMixin):
    """Top level node representing each table in database."""

    def __init__(self, db, ui, value_list, parent=None, key=None,
            depth=None):
        """Initializer.

        Args:
            db DBDriver object.
            ui: UIMain.
            value_list: either list of tables names or SiblingList.
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
        """
        self.db = db
        self.ui = ui
        super(TableNode, self).__init__(self.get_ui().loop, value_list,
                parent=parent, key=key, depth=depth)

    def load_widget(self):
        """Create and return tree widget for self."""
        return UITreeWidget(self)

    def load_child_keys(self):
        """Return ROWIDs for children of this table."""
        return self.db.get_single_column('ROWID', self.get_sibling_data())

    def get_sibling_node(self, key=None):
        """Get sibling table node by key.

        Args:
            key (optional): sibling key, if omitted gets self as sibling.

        Returns:
            Sibling TableNode.
        """
        sibling = self.get_sibling(key)
        if sibling['node'] is None:
            sibling['node'] = TableNode(self.db, self.ui,
                    self.get_value_list(), key=key)
        return sibling['node']

    def get_ui(self):
        """Get UIMain object."""
        return self.ui

    def get_display_text(self):
        """Return table name as display text."""
        return self.get_sibling_data()

    def _load_rdo(self, key):
        """Get RowDO object by key (ROWID)."""
        return self.db.search_iter(self.get_sibling_data(),
                'ROWID = {}'.format(key)).next()

    def load_child_node(self, key):
        """Create a RowDONode for child by key (ROWID)."""
        rdo = self._load_rdo(key)
        return RowDONode(self.ui, rdo, parent=self, key=key,
                depth=self.get_depth() + 1)

    def get_detail_mapping(self):
        # Effectively disable detail view.
        return None

    @property
    def export_title(self):
        return 'Export table: \'{}\''.format(self.get_display_text())

    def export(self, exporter):
        """Generic export of all RowDO objects of this table.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
        """
        log.debug('export called on: {}'.format(self))

        table_name = self.get_display_text()
        exporter.write_hdr('Table {}'.format(table_name))
        self.export_children(exporter, table_name)

    def update(self):
        """Update is disabled for TableNodes.  Show error dialog explaining
        this."""
        markup = 'Update not available for TableNode'
        widget = ui_base.markup_to_text(markup, align=urwid.LEFT,
                wrap=urwid.ANY)
        width, _ = self.get_ui().get_screen_relative((80, None))
        width, height = widget.original_widget.pack((width,))
        err_dialog = ui_dialog.ErrorDialog(self.get_ui(), widget=widget,
                width=width + ui_dialog.ERROR_DIALOG_ROWS_COLS[1],
                height=height + ui_dialog.ERROR_DIALOG_ROWS_COLS[0])
        err_dialog.start()


class RowDONode(urwid.TreeNode):
    """leaf node representing each single RowDO object."""

    def __init__(self, ui, value, parent=None, key=None, depth=None):
        """Initializer.

        Args:
            ui: UIMain.
            value: RowDO object.
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
        """
        self.ui = ui
        super(RowDONode, self).__init__(value, parent=parent, key=key,
                depth=depth)

    def load_widget(self):
        """Create and return tree widget for self."""
        return UITreeWidget(self)

    def get_ui(self):
        """Get UIMain object."""
        return self.ui

    def get_display_text(self):
        """Return generic string representation of node's RowDO object."""
        return repr(self.get_value())

    def get_type(self):
        """Return RowDO name as node type."""
        return '{} row'.format(self.get_value().name)

    def get_detail_mapping(self):
        """Return RowDO object as detailed mapping."""
        return self.get_value()


class UILoggingHandler(logging.Handler):
    """UI integrated logging handler for standard Python logging library.
    The handler can be 'connected' and 'disconnected' to the UI and
    initialized before hand.  While in the disconnected state the handler can
    also output logging lines to stderr using the building StreamHandler."""

    log_level_attr = {
        'CRITICAL': 'log critical',
        'ERROR': 'log error',
        'WARN': 'log warning',
        'WARNING': 'log warning',
        'INFO': 'log info',
        'DEBUG': 'log debug',
        'NOTSET': 'log notset',
    }

    def __init__(self, max_history=100, disable_stderr=False):
        """Initializer.

        Args:
            max_history (optional): int max logging lines stored in internal
                SimpleListWalker.
            disable_stderr (optional): bool if stderr is always disabled.
        """
        super(UILoggingHandler, self).__init__()
        self.flush_ui = None
        self.max_history = max_history
        self.log_history = urwid.SimpleListWalker(list())
        if disable_stderr is True:
            self._stream = None
        else:
            self._stream = logging.StreamHandler()
        self.stream = self._stream

    def flush(self):
        """Flush UI if connected.  Used to update the UI log while busy inside
        the main loop."""
        if self.flush_ui is not None:
            self.flush_ui(frame_offset=1)

    def setLevel(self, level):
        """Set current logging level for UI and stderr."""
        super(UILoggingHandler, self).setLevel(level)
        if self._stream is not None:
            self._stream.setLevel(level)

    def format(self, record):
        """Format a record with the defined UI decorations."""
        # Apply logging formatter.
        msg = super(UILoggingHandler, self).format(record)

        # Convert and decorate for the ui.
        attr = self.log_level_attr.get(record.levelname, 'log notset')
        focus_attr = 'focus {}'.format(attr)
        msg = ui_base.SelectableText(msg)
        msg = urwid.AttrMap(msg, {None: attr}, {None: focus_attr})

        return msg

    def emit(self, record):
        """Emit a record to either UI or stderr based on connected state.
        Emit does not automatically flush the UI since it may cause Python
        maximum recursion error depending where in the render chain the log
        line is created."""
        if self.stream is not None:
            self.stream.emit(record)

        try:
            msg = self.format(record)
            # Set if the msg was already emitted on the stream handler.
            msg._sh_emit = self.stream is not None

            self.log_history.append(msg)

            log_size = len(self.log_history)
            if self.max_history > 0 and log_size > self.max_history:
                # Should only ever increment by one.
                self.log_history.pop(0)
                log_size -= 1

            self.log_history.focus = log_size - 1
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def setFormatter(self, fmt):
        """Set current logging formatter for UI and stderr."""
        super(UILoggingHandler, self).setFormatter(fmt)
        if self._stream is not None:
            self._stream.setFormatter(fmt)

    def connect_ui(self, flush_ui):
        """Connect UI with the flush_ui function.  This will disable stderr."""
        self.flush_ui = flush_ui
        self.stream = None

    def disconnect_ui(self):
        """Disconnect UI and enable stderr if not permanently disabled."""
        self.flush_ui = None
        self.stream = self._stream

    def get_history(self):
        """Return internal SimpleListWalker containing log history."""
        return self.log_history

    def get_history_str(self, only_sh_emit=False):
        """Generator of strings of log history.

        Args:
            only_sh_emit (optional): bool to only return records that were not
                already emitted to stderr.
        """
        for msg in self.log_history:
            if msg._sh_emit is False or only_sh_emit is False:
                yield msg.original_widget.text


class UIMain(object):
    """Top level generic UI class."""

    log_palette = [
        ('log critical',            'dark red,bold',    'light gray'),
        ('log debug',               'dark green',       'light gray'),
        ('log error',               'dark red',         'light gray'),
        ('log info',                'black',            'light gray'),
        ('log notset',              'dark magenta',     'light gray'),
        ('log warning',             'yellow',           'light gray'),
        ('focus log critical',      'dark red,bold',    'dark blue'),
        ('focus log debug',         'dark green',       'dark blue'),
        ('focus log error',         'dark red',         'dark blue'),
        ('focus log info',          'black',            'dark blue'),
        ('focus log notset',        'dark magenta',     'dark blue'),
        ('focus log warning',       'yellow',           'dark blue'),
    ]

    palette = [
        ('app footer',      'light gray',       'black'),
        ('app header',      'yellow,bold',      'black',        'standout'),
        ('body bold',       'black,bold',       'light gray',   'underline'),
        ('body underline',  'black,underline',  'light gray',   'underline'),
        ('body',            'black',            'light gray'),
        ('border',          'black',            'dark gray'),
        ('button focus',    'white',            'dark green'),
        ('button',          'light gray',       'dark blue',    'standout'),
        ('error',           'dark red,bold',    'light gray'),
        ('focus',           'light gray',       'dark blue',    'standout'),
        ('help header',     'yellow,bold',      'black',        'standout'),
        ('help hl',         'dark blue,bold',   'light gray'),
        ('help underline',  'dark blue,underline',  'light gray'),
        ('help',            'black',            'light gray'),
        ('key',             'light cyan',       'black',        'underline'),
        ('log header',      'yellow,bold',      'black',        'standout'),
        ('search header',   'light cyan,bold',  'black',        'standout'),
        ('shadow',          'white',            'black'),
        ('title',           'white,bold',       'black',        'bold'),
    ]

    title = [
        'Site archiver'
    ]

    #('key', unicodedata.lookup('LEFTWARDS ARROW')),  ',',
    #('key', unicodedata.lookup('DOWNWARDS ARROW')),  ',',
    #('key', unicodedata.lookup('UPWARDS ARROW')),    ',',
    #('key', unicodedata.lookup('RIGHTWARDS ARROW')), '  ',
    footer_markup = [
        ('title', 'Keys:  '),
        ('key', 'E'), ('title', 'xport'), '  ',
        ('key', 'Q'), ('title', 'uit'),   '  ',
        ('key', 'S'), ('title', 'earch'), '  ',
        ('key', 'U'), ('title', 'pdate'), '  ',
        ('title', 'Movement'), ' ',
        ('key', _L_ARROW),  ',',
        ('key', _D_ARROW),  ',',
        ('key', _U_ARROW),  ',',
        ('key', _R_ARROW),  '  ',
        ('key', 'H'), ',',
        ('key', 'J'), ',',
        ('key', 'K'), ',',
        ('key', 'L'), '  ',
        ('title', 'Preferences'), ' ',
        ('key', 'ctrl-p'),        '  ',
        ('title', 'Help'),        ' ',
        ('key', '?'),             '  ',
    ]

    help_markup_list = [
        ('help underline', 'Keys:'),
        '',
        [('help hl', 'esc:      '), ('help', 'Exit dialog/search results')],
        [('help hl', 'tab:      '), ('help', 'Switch to/from log/buttons')],
        [('help hl', '?:        '), ('help', 'Open help')],
        [('help hl', 'e:        '),
            ('help', 'Export current tree/search results')],
        [('help hl', 'q:        '), ('help', 'Quit')],
        [('help hl', 's         '), ('help', 'Open search')],
        [('help hl', 'u         '), ('help', 'Update current tree')],
        [('help hl', 'U         '), ('help', 'Update all trees')],
        [('help hl', _L_ARROW + ' /h/-:   '), ('help', 'Left/collapse tree')],
        [('help hl', _R_ARROW + ' /l/+:   '), ('help', 'Right/expand tree')],
        [('help hl', _D_ARROW + ' /j:     '), ('help', 'Down')],
        [('help hl', _U_ARROW + ' /k:     '), ('help', 'Up')],
        [('help hl', 'ctrl-d:   '), ('help', 'Page down')],
        [('help hl', 'ctrl-u:   '), ('help', 'Page up')],
        [('help hl', 'ctrl-p:   '), ('help', 'Open preferences')],
    ]

    search_markup = [
        'Search results'
    ]

    def __init__(self, db, dl_dir, log_handler=None):
        """Initializer.

        Args:
            db: DBDriver object.
            dl_dir: path to download directory.
            log_handler (optional): UILoggingHandler object.
        """
        self._running = False
        self._in_dialog = False
        self.init_dialog_key_map()
        self._export_timestamp = True

        self.db = db
        self.dl_dir = dl_dir

        self.log_handler = log_handler
        if log_handler is not None:
            # If a log_handler is passed in init the logging palette.
            self.init_log_palette()

        # Create an empty main loop for widgets that need alarms.  Disable
        # mouse events in the main loop.
        self.loop = urwid.MainLoop(None, self.palette, handle_mouse=False,
            unhandled_input=self.unhandled_input,
            event_loop=ui_base.NestableSelectEventLoop())

        # Init data_view
        self.data_view = self.init_data_view()

        # Create empty search view to not crash if we switch before
        # data is available.
        self.set_search_view(self.empty_search_view())

        # Set current view to data (this is used to switch between
        # data and search view).
        self.current_view = self.data_view

        if log_handler is not None:
            # If a log_handler is passed in create a log view as a listbox.
            log_history = log_handler.get_history()
            self.log_data = ui_base.ListBoxBase(log_history)
            self.log_data = urwid.AttrMap(self.log_data, {None: 'body'})

            self.log_header = urwid.Text('Log')
            self.log_header = urwid.AttrMap(self.log_header,
                    {None: 'log header'})

            self.log_view = urwid.Frame(self.log_data, header=self.log_header)
            self.log_view = urwid.BoxAdapter(self.log_view,
                    prefs['ui.log.view.lines'])

            # Create a frame and place current view as the body and log view
            # as the footer.  Set this frame as the main view.  Leave
            # current view intact so it can be used to switch between the
            # data and search views.
            self.main_view = urwid.Frame(self.current_view,
                    footer=self.log_view)
        else:
            # Set log view as None, used to determine how to switch the
            # current view (see set_current_view).
            self.log_view = None
            # Main view is only the current view.
            self.main_view = self.current_view

        # Create full app view header/foot and combine with the main view.
        self.app_header = urwid.Text(self.title, align=urwid.CENTER)
        self.app_header = urwid.AttrMap(self.app_header, {None: 'app header'})

        self.app_footer = urwid.Text(self.footer_markup)
        self.app_footer = urwid.AttrMap(self.app_footer, {None: 'app footer'})

        self.app_view = urwid.Frame(self.main_view, header=self.app_header,
                footer=self.app_footer)

        # Set app view.
        self.loop.widget = self.app_view

    def init_dialog_key_map(self):
        """Initialize top level key map to be mapped with handlers.  Values in
        key map are tuples in the format (<handler>, <bool if dialog
        nestable>)."""
        self._dialog_key_map = {
            '/':        (self.handle_help,      False),
            '?':        (self.handle_help,      False),
            'e':        (self.handle_export,    False),
            'E':        (self.handle_export,    False),
            'q':        (self.handle_quit,      True),
            'Q':        (self.handle_quit,      True),
            's':        (self.handle_search,    False),
            'S':        (self.handle_search,    False),
            'u':        (self.handle_update,    False),
            'U':        (self.handle_update,    False),
            'ctrl p':   (self.handle_prefs,     False)
        }

    def init_log_palette(self):
        """Init log palette."""
        palette_keys = zip(*self.palette)[0]
        for lp in self.log_palette:
            key = lp[0]
            if key not in palette_keys:
                self.palette += (lp,)

    def init_data_view(self):
        """Initialize data view using TableNodes for each table in the
        database as the top level."""
        self.table_list = self.db.tables()
        self.table_root_node = TableNode(self.db, self, self.table_list)
        self.table_data_view = UITreeListBox(urwid.TreeWalker(
                self.table_root_node))
        blah = self.table_data_view
        self.table_data_view.offset_rows = 1

        return urwid.AttrMap(self.table_data_view, {None: 'body'})

    @property
    def screen_cols_rows(self):
        """Return current screen dimension (columns, rows) from main loop."""
        return self.loop.screen.get_cols_rows()

    @property
    def screen_cols(self):
        """Return current horizontal dimension (columns) from main loop."""
        return self.screen_cols_rows[0]

    @property
    def screen_rows(self):
        """Return current vertical dimension (rows) from main loop."""
        return self.screen_cols_rows[1]

    def get_screen_relative(self, relative):
        """Return relative screen dimensions

        Args:
            relative: tuple (horizontal, vertical) percentages of screen size
                to calculate.
        """
        cols, rows = self.screen_cols_rows
        if relative[0] is not None:
            cols = ui_base.given_width((urwid.RELATIVE, relative[0]), cols)
        if relative[1] is not None:
            rows = ui_base.given_height((urwid.RELATIVE, relative[1]), rows)
        return (cols, rows)

    def start(self):
        """Run main loop until returned by exit handler."""
        if self._running:
            return

        if self.log_handler is not None:
            self.log_handler.connect_ui(self.flush)

        self._running = True

        self.loop.run()

    def shutdown(self):
        """Shutdown down main loop and disconnect log."""
        if not self._running:
            return

        if self.log_handler is not None:
            self.log_handler.disconnect_ui()

        self._running = False
        raise urwid.ExitMainLoop()

    def flush(self, force_flush=False, frame_offset=0):
        """Update screen while busy in the main loop.  Checks if stack is
        currently rendering the screen and aborts with log error.

        Args:
            force_flush (optional): bool to disable render check.
            frame_offset (optional): fames to skip when creating log error.
                Useful for tracking buggy calls.
        """
        if not self._running:
            return

        if not force_flush:
            # Calling draw_screen while rendering can cause a maximum recursion
            # error in Python.
            fn_skip = ['render', 'cached_render']
            if frame_offset > 0:
                frame_offset *= -1

            tb = traceback.extract_stack()
            fn_list = map(operator.itemgetter(2), tb)
            if any([x in fn_list for x in fn_skip]):
                fmt = ('flush called in render chain, deferring call '
                        'from {} {}:{}')
                # self.flush frame is tb[-1], caller frame is tb[-2].
                frame = tb[-2 + frame_offset]
                # frame format (file, line, caller function, call source)
                log.error(fmt.format(frame[2], os.path.split(frame[0])[1],
                        frame[1]))
                return

        self.loop.draw_screen()

    def has_log_view(self):
        """Return if log view is enabled."""
        return hasattr(self.main_view, 'footer')

    def switch_main_focus(self):
        """Switch main focus between data/search and log frames."""
        if not self.has_log_view():
            return False

        if self.main_view.focus_position == 'body':
            self.main_view.focus_position = 'footer'
        else:
            self.main_view.focus_position = 'body'
        return True

    def enter_dialog(self):
        """Enter dialog guard function.  Return True if dialog lock taken."""
        # returns True if not already in a dialog.
        if not self._in_dialog:
            self._in_dialog = True
            return True
        return False

    def exit_dialog(self):
        """Exit dialog guard function.  Releases lock and warns if lock was
        not set."""
        if not self._in_dialog:
            log.warn('exit_dialog called but not set')
            return
        self._in_dialog = False

    def in_dialog(self):
        """Return True if dialog lock is set."""
        return self._in_dialog

    def do_dialog(self, func, key, nested_dialog=False):
        """General display dialog and return status.  Handler acquiring and
        releasing dialog lock.  Typically used with handler functions.

        Args:
            func: handler or dialog function.
            key: key that generated this event/call.
            nested_dialog (optional): bool to only call handler/dialog if lock
                was acquired.
        """
        was_in_dialog = self.in_dialog()
        # Note: enter_dialog must be called before checking nested_dialog to
        # set self._in_dialog if nested_dialog is True.
        if self.enter_dialog() is False and nested_dialog is False:
            return

        log.debug('entering dialog: {}'.format(func))
        ret = func(key)

        if was_in_dialog is False:
            self.exit_dialog()

        return ret

    def set_search_view(self, view):
        """Set current search view."""
        self.search_view = view

    def create_search_listbox(self, iterable):
        """Create and return search list box using UIRowDOSearchListBox.

        Args:
            iterable: iterable of RowDO objects.

        Returns:
            Decorated UIRowDOSearchListBox.
        """
        # Note: Overload this.
        ret = UIRowDOSearchListBox(self, iterable, 'body', 'focus')
        return urwid.AttrMap(ret, {None: 'body'})

    def create_search_view(self, iterable):
        """Create and return search list view with body from
        create_search_listbox.

        Args:
            iterable: iterable of RowDO objects.

        Returns:
            urwid.Frame with search view as body.
        """
        header = urwid.Text(self.search_markup, align=urwid.CENTER)
        header = urwid.AttrMap(header, {None: 'search header'})
        body = self.create_search_listbox(iterable)
        return urwid.Frame(body, header=header)

    def empty_search_view(self):
        """Create empty search view."""
        return self.create_search_view(list())

    def get_current_view(self):
        """Return 'data' or 'search' depending on current data view."""
        if self.current_view == self.data_view:
            return 'data'
        elif self.current_view == self.search_view:
            return 'search'
        else:
            raise UIError('unknown current view for object: {}'.format(
                    str(self.current_view)))

    def set_current_view(self, view):
        """Set current data view to 'data' or 'search'.  Actual widgets
        containing view should already be stored internally."""
        if view == 'data':
            self.current_view = self.data_view
        elif view == 'search':
            self.current_view = self.search_view
        else:
            raise ValueError('view must be \'data\' or \'search\'')

        if self.log_view is None:
            # No log view, current view is the body of the app view frame.
            self.app_view.set_body(self.current_view)
        else:
            # Has log view, current view is the body of the
            # current view/log view frame which is the body of the app view
            # frame.
            self.app_view.get_body().set_body(self.current_view)

    def switch_current_view(self):
        """Switch current view between 'data' and 'search'."""
        if self.get_current_view == 'data':
            self.set_current_view('search')
        else:
            self.set_current_view('data')

    def get_data_widget(self):
        """Return current data view widget."""
        return self.data_view.original_widget

    def get_search_widget(self):
        """Return current search view widget."""
        return self.search_view.body.original_widget

    def get_current_widget(self):
        """Return widget for currently displayed view."""
        if self.get_current_view() == 'data':
            return self.get_data_widget()
        else:
            return self.get_search_widget()

    def handle_help(self, key):
        """Display help dialog using markup in self.help_markup_list.
        Preferences with their default and help are dynamically generated and
        shown too."""

        width = (urwid.RELATIVE, 80)

        # Used to indent the preference help strings.
        tw_indent = ' ' * 4
        tw_width = ui_base.given_width(width, self.screen_cols) \
                - len(tw_indent) - ui_dialog.DIALOG_BASE_ROWS_COLS[1]

        pref_markup_list = [
            '',
            ('help underline', 'Preferences:'),
        ]
        for pref_key in sorted(prefs.keys()):
            p = prefs.get_pref(pref_key)
            type_str = getattr(p.value_type, '__name__', repr(p.value_type))

            pref_markup_list.append(('help underline', '{}:'.format(p.key)))
            markup = [
                ('help hl', '    {}('.format(type_str)),
                '{}'.format(p.value),
                ('help hl', ')'),
                '  default: {}'.format(p.default)
            ]
            pref_markup_list.append(markup)

            hlp = p.help
            if isinstance(hlp, basestring) and hlp != '':
                hlp = textwrap.wrap('Help: ' + hlp, tw_width)
                for line in hlp:
                    pref_markup_list.append('{}{}'.format(tw_indent, line))

            pref_markup_list.append('')

        widget = ui_base.markup_list_to_text(
                self.help_markup_list + pref_markup_list, attr='help')
        ui_dialog.SimpleDialog(self, widget=widget,
                width=(urwid.RELATIVE, 80), height=(urwid.RELATIVE, 80),
                title='Help', title_attr='help header').start()

    def export_timestamp(self, exporter):
        """Write formatted timestamp to exporter."""
        exporter.write_hdr('Written on: {}'.format(
                str(datetime.datetime.utcnow())))

    def do_export(self, current_widget, export_header=None):
        """Get path from save dialog and call export on current_widget.

        Args:
            current_widget: widget to call export on>
            export_header (optional): header string to write before calling
                current_widget.export.
        """
        path = export.get_default_export_path()
        export_title = getattr(current_widget, 'export_title', 'Export data')
        dialog = ui_dialog.SaveDialog(self, markup=export_title,
                default=path)
        path = dialog.start()

        if path is None:
            return

        log.info('exporting to: \'{}\''.format(path))
        exporter = export.Exporter(path)

        if callable(export_header):
            export_header(exporter)
        elif isinstance(export_header, basestring):
            exporter.write_hdr(export_header)

        current_widget.export(exporter)
        exporter.close()

    def handle_export(self, key):
        """Handle export of current view.  If corresponding widget does not
        have an export method display error dialog."""
        current_widget = self.get_current_widget()

        if not hasattr(current_widget, 'export') \
                or not callable(current_widget.export):
            current_view = self.get_current_view()
            markup = 'No export for {} view available'.format(current_view)
            widget = ui_base.markup_to_text(markup, align=urwid.LEFT,
                    wrap=urwid.ANY)
            width, _ = self.get_screen_relative((80, None))
            width, height = widget.original_widget.pack((width,))
            err_dialog = ui_dialog.ErrorDialog(self, widget=widget,
                    width=width + ui_dialog.ERROR_DIALOG_ROWS_COLS[1],
                    height=height + ui_dialog.ERROR_DIALOG_ROWS_COLS[0])
            err_dialog.start()
            return

        if self._export_timestamp is True:
            export_header = self.export_timestamp
        else:
            export_header = None

        self.do_export(current_widget, export_header=export_header)

    def handle_quit(self, key):
        """Show quit dialog and exit if OK is selected.  Quit dialog will
        always be displayed even if there is an active dialog.  It will set the
        dialog set to prevent any other dialogs before returning."""
        quit_dialog = ui_dialog.ConfirmDialog(self, markup='Exit program?',
                width=40, height=10, ignore_keys=('q', 'Q'))
        ret = quit_dialog.start()
        if ret == 1:
            self.shutdown()

    def search_dialog(self):
        """Return parameters from search dialog with table and column
        fields."""
        dialog = ui_dialog.SearchDialog(self, search_type='database',
                prompt_table=True, prompt_column=True)
        return dialog.start()

    def _get_search_data(self, params):
        """Create and return search iterator from search dialog parameters."""
        try:
            data = self.db.search_terms_iter(table=params['table'],
                    column=params['column'], all_terms=params['all_terms'],
                    any_terms=params['any_terms'],
                    not_terms=params['not_terms'])
        except (DBDriverError, sqlite3.Error) as e:
            log.warn('search error: {}'.format(util.exception_string(e)))
            data = None

        return data

    def handle_search(self, key):
        """Show search dialog and display results.  If search does not return
        any results a error dialog is displayed."""
        params = self.search_dialog()

        if params is None:
            log.debug('aborting search')
            return

        data = self._get_search_data(params)
        if data is None:
            return

        view = self.create_search_view(data)

        self.set_search_view(view)

        if self.get_search_widget().get_focus() == (None, None):
            markup = 'No results found'
            log.info(markup)

            err_dialog = ui_dialog.ErrorDialog(self, markup=markup,
                    width=len(markup) + ui_dialog.ERROR_DIALOG_ROWS_COLS[1],
                    height=1 + ui_dialog.ERROR_DIALOG_ROWS_COLS[0])
            err_dialog.start()
            return

        self.set_current_view('search')

    def handle_update(self, key):
        """If in data view call update on data widget.  If widget does not
        have update method an AttributeError will be raised.  Does nothing
        while in search view."""
        if self.get_current_view() == 'search':
            return

        # Just look for update attr, try update_all below but fall back to
        # update.
        current_widget = self.get_current_widget()
        if not hasattr(current_widget, 'update') \
                or not callable(current_widget.update):
            err = '\'{}\' does not have callable attribute \'update\''
            raise AttributeError(err.format(type(current_widget).__name__))

        if key == 'U' and hasattr(current_widget, 'update_all'):
            current_widget.update_all()
        else:
            current_widget.update()

    def handle_prefs(self, key):
        """Show edit preferences dialog."""
        ui_dialog.EditPreferencesDialog(self).start()

    def unhandled_input(self, key):
        """Catch esc and tab keys to navigate between log/data/search views.
        Handles all keys in self._dialog_key_map."""
        if self._dialog_key_map.has_key(key):
            func, nested_dialog = self._dialog_key_map[key]
            self.do_dialog(func, key, nested_dialog)
        elif key == 'esc':
            if self.get_current_view() == 'search':
                self.set_current_view('data')
        elif key == 'tab':
            if not self.in_dialog():
                self.switch_main_focus()
