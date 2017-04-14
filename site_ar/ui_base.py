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
import logging
import select
import unicodedata
import urwid
import weakref


from . import dbdrv
from . import export
from . import prefs
from . import util
from .exceptions import UIError, PreferencesTypeError, ValidatedEditError


log = logging.getLogger(__name__)


FIXED_BOTTOM = ' '.join([urwid.FIXED, urwid.BOTTOM])
FIXED_LEFT = ' '.join([urwid.FIXED, urwid.LEFT])
FIXED_RIGHT = ' '.join([urwid.FIXED, urwid.RIGHT])
FIXED_TOP = ' '.join([urwid.FIXED, urwid.TOP])


prefs.add('ui.weakchildren_lifespan', int, True, default=10,
        help='Time in seconds for children of WeakRefParentNode to '
        'maintain strong references after collapse')


def _given_val(val_type, val, screen_val):
    """Return a given/absolute value given a urwid dimension tuple.

    Args:
        val_type: string 'height' or 'width' of val.
        val: urwid dimension tuple.
        screen_val: absolute screen dimension.

    Returns:
        int dimension.
    """
    if val_type == 'height':
        norm_func = urwid.decoration.normalize_height
    elif val_type == 'width':
        norm_func = urwid.decoration.normalize_width
    else:
        raise ValueError('val_type must be \'height\' or \'width\'')

    norm_type, norm_amount = norm_func(val, UIError)
    if norm_type == urwid.RELATIVE:
        norm_amount = urwid.int_scale(norm_amount, 101, screen_val)
    return norm_amount


def _min_val(val_type, val_a, val_b, screen_val):
    """Minimum value of two urwid dimension tuples.

    Args:
        val_type: string 'height' or 'width' of val_*.
        val_a: urwid dimension tuple.
        val_b: urwid dimension tuple.
        screen_val: absolute screen dimension.

    Returns:
        val_a or val_b.
    """
    given_a = _given_val(val_type, val_a, screen_val)
    given_b = _given_val(val_type, val_b, screen_val)

    if given_a <= given_b:
        return val_a
    else:
        return val_b


def given_height(height, screen_rows):
    """Return a given/absolute rows given a urwid dimension tuple.

    Args:
        height: urwid dimension tuple.
        screen_rows: int screen rows.

    Returns:
        int rows.
    """
    return _given_val('height', height, screen_rows)


def given_width(width, screen_cols):
    """Return a given/absolute cols given a urwid dimension tuple.

    Args:
        width: urwid dimension tuple.
        screen_cols: int screen cols.

    Returns:
        int cols.
    """
    return _given_val('width', width, screen_cols)


def min_height(height_a, height_b, screen_rows):
    """Minimum height or urwid dimension tuples.

    Args:
        height_a: urwid dimension tuple.
        height_b: urwid dimension tuple.
        screen_rows: int screen rows.

    Returns:
        height_a or height_b.
    """
    return _min_val('height', height_a, height_b, screen_rows)


def min_width(width_a, width_b, screen_cols):
    """Minimum width or urwid dimension tuples.

    Args:
        width_a: urwid dimension tuple.
        width_b: urwid dimension tuple.
        screen_rows: int screen rows.

    Returns:
        width_a or width_b.
    """
    return _min_val('width', width_a, width_b, screen_cols)


def markup_to_text(markup, align=urwid.LEFT, wrap=urwid.SPACE, layout=None,
        attr='body', focus_attr=None):
    """Convert markup to urwid.Text.

    Args:
        markup: urwid markup.
        align (optional): urwid text alignment.
        wrap (optional): urwid text wrap.
        layout (optional): urwid text layout instance.
        attr (optional): default attr key.
        focus_attr (optional): focus attr key.

    Returns:
        urwid.Text.
    """
    if isinstance(attr, basestring):
        attr = {None: attr}
    if isinstance(focus_attr, basestring):
        focus_attr = {None: focus_attr}

    text = urwid.Text(markup, align=align, wrap=wrap, layout=layout)
    text = urwid.AttrMap(text, attr, focus_attr)
    return text


def markup_list_to_text(markup_list, align=urwid.LEFT, wrap=urwid.SPACE,
        layout=None, attr='body', focus_attr=None):
    """Convert list of markups to list of urwid.Text objects.

    Args:
        markup_list: list of urwid markup.
        align (optional): urwid text alignment.
        wrap (optional): urwid text wrap.
        layout (optional): urwid text layout instance.
        attr (optional): default attr key.
        focus_attr (optional): focus attr key.

    Returns:
        list of urwid.Text.
    """
    if isinstance(attr, basestring):
        attr = {None: attr}
    if isinstance(focus_attr, basestring):
        focus_attr = {None: focus_attr}

    widgets = []
    for markup in markup_list:
        text = urwid.Text(markup, align=align, wrap=wrap, layout=layout)
        text = urwid.AttrMap(text, attr, focus_attr)
        widgets.append(text)

    return widgets


def listbox_contents_iter(contents):
    """Returns and iterator to a ListBoxContents object."""
    # ListBoxContents is defined inside urwid.ListBox use string
    # compare for simple sanity.
    if type(contents).__name__ != 'ListBoxContents':
        raise TypeError('contents must be urwid.ListBox.ListBoxContents')

    index = 0
    while True:
        item = contents[index]
        # ListBoxContents will return None if index is out of range.
        if item is None:
            raise StopIteration
        yield item
        index += 1


def tree_attr_find(node, attr, attr_callable=False, find_first=True):
    """Walk urwid.TreeNode objects to parent searching for an attribute,
    including node.

    Args:
        node: starting urwid.TreeNode.
        attr: string attribute to search for.
        attr_callable (optional): True to only match callable attributes.
        find_fist: True to find first node, False for last found.

    Returns:
        matching node or None.
    """
    found = None
    while node != None:
        nodeattr = getattr(node, attr, None)
        if nodeattr is not None and (attr_callable is False
                or callable(nodeattr)):
            if find_first is True:
                return node
            found = node

        if not hasattr(node, 'get_parent'):
            raise ValueError('node does not have get_parent')

        node = node.get_parent()

    return found


class WeakRefParentNode(urwid.ParentNode):
    """Child class of urwid.ParentNode where when in the collapsed state
    children weakly referenced.  This allows them to be cached but still have
    a finite lifespan and be collected if unused.  When the node is in the
    expanded state all children are strongly referenced to be used by urwid.
    Class requires extra support to operate."""

    def __init__(self, loop, value, parent=None, key=None, depth=None,
            lifespan=None):
        """Initializer.

        Args:
            loop: urwid.MainLoop.
            value: node value.
            parent (optional): urwid.TreeNode of parent.
            key (optional): key string.
            depth (optional): int this nodes depth.
            lifespan (optional): int if < 0 children are changed to weak
                referenced on collapse.  If 0 children will always be strongly
                referenced.  If > 0 time in seconds after collapse children
                change to weak referenced.
        """
        if lifespan is None:
            lifespan = prefs['ui.weakchildren_lifespan']

        self.loop = loop
        self.lifespan = lifespan
        self.alarm = None

        super(WeakRefParentNode, self).__init__(value, parent=parent,
                key=key, depth=depth)

        log.debug('_children type: {}'.format(type(self._children).__name__))
        if len(self._children):
            raise ValueError('unexpected data in self._children')

        self._children = weakref.WeakValueDictionary()
        self._expanded_count = 0

    def _set_alarm(self, sec):
        """Clears any current alarm and sets new alarm in sec."""
        if self.alarm is not None:
            self._clear_alarm()

        log.debug('setting alarm in {} seconds'.format(sec))
        self.alarm = self.loop.set_alarm_in(sec, self.on_alarm)

    def _clear_alarm(self):
        """Clear alarm if set."""
        if self.alarm is None:
            return

        log.debug('clearing alarm {}'.format(self.alarm))
        ret = self.loop.remove_alarm(self.alarm)
        if ret is False:
            log.warn('alarm {} not found'.format(self.alarm))
        self.alarm = None

    def _set_strong_children(self):
        """Set children to strongly referenced."""
        if not isinstance(self._children, dict):
            self._children = dict(self._children)
            log.debug('recovered {} weak children'.format(len(self._children)))

    def _set_weak_children(self):
        """Set children to weak referenced."""
        if not isinstance(self._children, weakref.WeakValueDictionary):
            log.debug('save {} weak children'.format(len(self._children)))
            self._children = weakref.WeakValueDictionary(self._children)
            log.debug('{} children now weak'.format(len(self._children)))

    def _assert_strong_children(self):
        """Raise TypeError if children are not strongly referenced."""
        if not isinstance(self._children, dict):
            raise TypeError('self._children must be type dict')

    def on_alarm(self, loop, user_data):
        """Alarm to change children to weak referenced."""
        log.debug('alarm fired on {}'.format(self))
        self.alarm = None
        self._set_weak_children()

    def on_expand(self):
        """on_expand event to change children to strongly referenced.
        on_expand will increase an internal counter so multiple users may
        expand the node to use the children."""
        log.info('on_expand on parent {} with {} children in {} '
                'count {}'.format(hex(id(self)), len(self._children),
                type(self._children).__name__, self._expanded_count))

        self._expanded_count += 1
        self._clear_alarm()
        self._set_strong_children()

    def on_collapse(self):
        """on_expand event to decrease the internal counter.  If counter
        reaches 0 children will be changed to weak referenced or alarm set
        based on __init__ lifespan argument."""
        log.info('on_collapse on parent {} with {} children in {} '
                'count {}'.format(hex(id(self)), len(self._children),
                type(self._children).__name__, self._expanded_count))

        if self._expanded_count == 0:
            log.warn('on_collapse called without matching expand')
        else:
            self._expanded_count -= 1

        if self._expanded_count != 0:
            return

        if self.lifespan > 0:
            # Set to weak immediately if there are no children (covers empty
            #parent or new parent where children have not been loaded yet).
            #Need to make sure _children is weak when collapsed if sources
            #other than TreeWalker are going to load children
            if not len(self._children):
                self._set_weak_children()
            else:
                self._set_alarm(self.lifespan)
        elif self.lifespan == 0:
            self._children = weakref.WeakValueDictionary()

    def get_child_node(self, key, reload=False):
        """get_child_node ensuring children are strongly referenced."""
        self._assert_strong_children()
        return super(WeakRefParentNode, self).get_child_node(key, reload)

    def set_child_node(self, key, node):
        """set_child_node ensuring children are strongly referenced."""
        self._assert_strong_children()
        return super(WeakRefParentNode, self).set_child_node(key, node)

    def change_child_key(self, oldkey, newkey):
        """change_child_key ensuring children are strongly referenced."""
        self._assert_strong_children()
        return super(WeakRefParentNode, self).change_child_key(oldkey, newkey)


class SiblingList(list):
    """Unique class to store sibling data for lists of top level nodes with no
    parent.  Each entry SiblingLists are {'data': value, 'node': node}."""
    pass


class TreeRootNodeListMixin(object):
    def _init_prepare(self, value_list, key):
        """Prepare a list of values or SiblingList for this node.

        Args:
            value_list: list of values or SiblingList
            key: int node key (list index).

        Returns:
            SiblingList, key
        """
        if not isinstance(value_list, SiblingList):
            value_list = SiblingList([{'data': x, 'node': None} for x
                    in value_list])

        # Bootstrap key and node if this is the first node in value_list.
        if key is None:
            key = 0
            value_list[0]['node'] = self

        return value_list, key

    def get_value_list(self):
        """Return SiblingList."""
        return self.get_value()

    def get_sibling_keys(self):
        """Get SiblingList keys."""
        return range(len(self.get_value_list()))

    def get_sibling(self, key=None):
        """Get sibling by key.

        Args:
            key (optional): sibling key, if omitted gets self as sibling.

        Returns:
            sibling as {'data': value, 'node': node}.
        """
        if key is None:
            key = self.get_key()
        return self.get_value()[key]

    def get_sibling_data(self, key=None):
        """Get sibling data by key.  If key is omitted returns self data."""
        return self.get_sibling(key)['data']

    def get_sibling_node(self, key=None):
        """Get sibling node by key.  If key is omitted returns self node."""
        # Only children nodes get cached by the parent.  TreeRootNodeList have
        # no parent so we need to create the cache of siblings or they will
        # be regenerated and settings lost (i.e. exanded/collapsed).
        sibling = self.get_sibling(key)
        if sibling['node'] is None:
            sibling['node'] = TreeRootNodeList(self.get_value_list(), key=key)
        return sibling['node']

    def next_sibling(self):
        """Return next sibling in order or None if at end of list."""
        siblings = self.get_value()
        next_key = self.get_key() + 1
        if next_key >= len(siblings):
            return None
        return self.get_sibling_node(next_key)

    def prev_sibling(self):
        """Return previous sibling in order or None if at beginning of list."""
        siblings = self.get_value()
        prev_key = self.get_key() - 1
        if prev_key < 0:
            return None
        return self.get_sibling_node(prev_key)


class TreeRootNodeList(TreeRootNodeListMixin, urwid.ParentNode):
    """Top level node list that may not have parents."""

    def __init__(self, value_list, parent=None, key=None, depth=None):
        """Initializer.

        Args:
            value_list: list of values or SiblingList
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
        """
        value_list, key = self._init_prepare(value_list, key)
        super(TreeRootNodeList, self).__init__(value_list, parent=parent,
                key=key, depth=depth)


class WeakRefTreeRootNodeList(TreeRootNodeListMixin, WeakRefParentNode):
    """Top level node list that may not have parents with weak referenced
    children."""

    def __init__(self, loop, value_list, parent=None, key=None, depth=None,
            lifespan=None):
        """Initializer.

        Args:
            loop: urwid.MainLoop.
            value_list: list of values or SiblingList
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
            lifespan (optional): WeakRefParentNode children lifespan.
        """
        value_list, key = self._init_prepare(value_list, key)
        super(WeakRefTreeRootNodeList, self).__init__(loop, value_list,
                parent=parent, key=key, depth=depth, lifespan=lifespan)


class RowDOChildrenExportMixin(object):
    """Mixin class for parent node to generically export RowDO based children
    nodes."""

    export_keys = None
    pre_cache_func = 'on_expand'
    post_cache_func = 'on_collapse'

    def _call_cache_func(self, func):
        """Call cache function.

        Args:
            func: function or string of attribute on self.
        """
        if isinstance(func, basestring):
            func = getattr(self, func, None)
        if func is None:
            return

        if not callable(func):
            raise ValueError('invalid cache function: {}'.format(func))

        func()

    def _pre_cache(self):
        """Call cache function to allow node to prepare to use cache."""
        self._call_cache_func(self.pre_cache_func)

    def _post_cache(self):
        """Call cache function to allow node to clean up after cache."""
        self._call_cache_func(self.post_cache_func)

    def get_export_keys(self, table_name):
        """Get export keys for a given table name.  Keys are intersected
        with self.export_keys."""
        # Create empty row for this table and get keys.
        keys = self.db.rdo_ctors[table_name]().keys()
        return export.key_intersection(self.export_keys, keys,
                '{} table'.format(table_name))

    def export_children(self, exporter, table_name,
            get_child_mapping='get_detail_mapping',
            get_keyed_mapping='_load_rdo',
            rdo_callback=None):
        """Export children.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
            table_name: table name string of children RowDO objects.
            get_child_mapping (optional): string of function to call on
                children to get mapping (used only if preference
                export.tree.use_cache is True).
            get_keyed_mapping (optional): string of functo to call on self
                to load RowDO object by key (used only if preference
                export.tree.use_cache is False).
            rdo_callback (optional): callback to call on each RowDO/mapping to
                prepare data for export.

        Returns:
            None.
        """
        log.debug('export_children called on: {}'.format(self))

        if rdo_callback is not None and not callable(rdo_callback):
            raise ValueError('rdo_callback must be None or callable')

        keys = self.get_export_keys(table_name)

        exporter.write_hdr(keys)
        exporter.write_blank()

        log.debug('exporting keys: {}({})'.format(type(keys).__name__, keys))

        use_cache = prefs['export.tree.use_cache']
        if use_cache is True:
            self._pre_cache()

        child_keys = self.get_child_keys()

        for child_key in child_keys:
            if use_cache is True:
                rdo = getattr(self.get_child_node(child_key),
                        get_child_mapping)()
            else:
                rdo = getattr(self, get_keyed_mapping)(child_key)

            if not isinstance(rdo, dbdrv.RowDO):
                err = 'could not load rdo for child key: {}'.format(
                        child_key)
                log.warn(err)
            else:
                if rdo_callback is not None:
                    # Make a copy to leave the search results unchanged by
                    # the callback.
                    rdo = rdo_callback(dbdrv.RowDO(rdo), rdo)
                values = rdo.values(keys)
                exporter.write_row(values)

        if use_cache is True:
            self._post_cache()


class HeavyLineBox(urwid.LineBox):
    """urwid.LineBox using heavy line characters."""

    def __init__(
            self,
            original_widget,
            title='',
            tlcorner=unicodedata.lookup('BOX DRAWINGS HEAVY DOWN AND RIGHT'),
            tline=unicodedata.lookup('BOX DRAWINGS HEAVY HORIZONTAL'),
            lline=unicodedata.lookup('BOX DRAWINGS HEAVY VERTICAL'),
            trcorner=unicodedata.lookup('BOX DRAWINGS HEAVY DOWN AND LEFT'),
            blcorner=unicodedata.lookup('BOX DRAWINGS HEAVY UP AND RIGHT'),
            rline=unicodedata.lookup('BOX DRAWINGS HEAVY VERTICAL'),
            bline=unicodedata.lookup('BOX DRAWINGS HEAVY HORIZONTAL'),
            brcorner=unicodedata.lookup('BOX DRAWINGS HEAVY UP AND LEFT')):
        super(HeavyLineBox, self).__init__(original_widget, title, tlcorner,
                tline, lline, trcorner, blcorner, rline, bline, brcorner)


class SelectableText(urwid.Text):
    """urwid.Text that sets selectable to True by default."""

    def __init__(self, markup, align=urwid.LEFT, wrap=urwid.SPACE,
            layout=None):
        super(SelectableText, self).__init__(markup, align, wrap, layout)
        self._selectable = True

    def keypress(self, size, key):
        return key


class IteratorWalker(urwid.ListWalker):
    """urwid.ListWalker that can operate on an iterator.
    urwid.SimpleListWalker requires contents to have __getitem__ though most
    data is retrieved using get_next/get_prev which can benifit from an
    iterator for large sets of data.  Items that have been retrieved from
    the iterator is stored in an internal list."""

    def __init__(self, iterator):
        """Initializer.

        Args:
            iterator: iterator.
        """
        self.iterator = iterator
        self.contents = []
        self.position = 0

    def _get(self, position):
        """Gets a value by positiion from iterator or contents if already
        retrieved.

        Args:
            position: index to get.

        Returns:
            value, position or None, None if position is out of range.
        """
        # urwid.ListWalker does not support negative indexing.
        if position < 0:
            return None, None

        count = len(self.contents)

        while count <= position:
            try:
                self.contents.append(self.iterator.next())
            except StopIteration:
                break
            count += 1

        try:
            return self.contents[position], position
        except IndexError:
            return None, None

    def get_focus(self):
        """Returns value of current position."""
        return self._get(self.position)

    def set_focus(self, position):
        """Sets focus to position and raises IndexError if out of range.

        Args:
            position: index to get.
        """
        if self._get(position) is (None, None):
            raise IndexError('IteratorWalker index out of range')
        self.position = position
        self._modified()

    def get_next(self, position):
        """Gets next value by position.

        Args:
            position: index to get next position of.

        Returns:
            value, position or None, None if next position is out of range.
        """
        return self._get(position + 1)

    def get_prev(self, position):
        """Gets previous value by position.

        Args:
            position: index to get previous position of.

        Returns:
            value, position or None, None if previous position is out of range.
        """
        return self._get(position - 1)


_listboxbase_cmd_map = urwid.command_map.copy()
_listboxbase_cmd_map._command.update({
    'k':        urwid.CURSOR_UP,
    'K':        urwid.CURSOR_UP,
    'j':        urwid.CURSOR_DOWN,
    'J':        urwid.CURSOR_DOWN,
    'ctrl d':   urwid.CURSOR_PAGE_DOWN,
    'ctrl u':   urwid.CURSOR_PAGE_UP
})


_treelistboxbase_cmd_map = _listboxbase_cmd_map.copy()
_treelistboxbase_cmd_map._command.update({
    'h':        urwid.CURSOR_LEFT,
    'H':        urwid.CURSOR_LEFT,
    '-':        urwid.CURSOR_LEFT,
    'l':        urwid.CURSOR_RIGHT,
    'L':        urwid.CURSOR_RIGHT,
    '=':        urwid.CURSOR_RIGHT,
    '+':        urwid.CURSOR_RIGHT
})


class ListBoxBase(urwid.ListBox):
    """Simple child class of urwid.ListBox that adds 'j', 'k', 'ctrl-d'
    and 'ctrl-u' movement key functionality.  Can also support a body
    generated by an iterator by default."""

    _command_map = _listboxbase_cmd_map

    def __init__(self, body):
        # ListBox expects body to have the attribute get_focus.  If not it
        # will use a default ListWalker which then expects body to have
        # __getitem__.  In the case of an iterator use the ItertorWalker.
        if not getattr(body, 'get_focus', None) \
                and isinstance(body, collections.Iterator):
            body = IteratorWalker(body)

        super(ListBoxBase, self).__init__(body)


class TreeListBoxBase(urwid.TreeListBox):
    """Simple child class of urwid.TreeListBox that adds 'h', 'j', 'k', 'l',
    'ctrl-d' and 'ctrl-u' movement key functionality."""

    _command_map = _treelistboxbase_cmd_map

    def _keypress_left(self, size):
        tree_widget, _ = self.get_focus()
        node = tree_widget.get_node()
        if isinstance(node, urwid.ParentNode) \
                and tree_widget.expanded is True:
            tree_widget.expanded = False
            tree_widget.update_expanded_icon()
        elif node.get_parent() is not None:
            self.move_focus_to_parent(size)

    def _keypress_right(self, size):
        tree_widget, _ = self.get_focus()
        if isinstance(tree_widget.get_node(), urwid.ParentNode):
            tree_widget.expanded = True
            tree_widget.update_expanded_icon()

    def keypress(self, size, key):
        if self._command_map[key] == urwid.CURSOR_LEFT:
            self._keypress_left(size)
        elif self._command_map[key] == urwid.CURSOR_RIGHT:
            self._keypress_right(size)
        else:
            return super(TreeListBoxBase, self).keypress(size, key)


class GridFlowBase(urwid.GridFlow):
    """Simple child class of urwid.GridFlow that adds 'h', and 'l' movement
    key functionality.  This is typically used for grids of buttons."""

    # No easy way to use command map on GridFlow since cursor keys are
    # used by Columns/Pile objects dynamically allocated by GridFlow.
    def keypress(self, size, key):
        if key in ('h', 'H'):
            key = 'left'
        elif key in ('l', 'L'):
            key = 'right'

        return super(GridFlowBase, self).keypress(size, key)


class ValidatedEdit(urwid.Edit):
    """Edit box that maintains a validated string in edit_text.  Class
    requires extra support to operate."""

    def __init__(self, caption=u'', edit_text=u'', multiline=False,
            align=urwid.LEFT, wrap=urwid.SPACE, allow_tab=False,
            edit_pos=None, layout=None, mask=None, validator=None):
        """Initializer.

        Args:
            caption (optional): caption string.
            edit_text (optional): initial edit_text value.
            multiline (optional): bool if multiline edit text is allowable.
            align (optional): urwid text alignment.
            wrap (optional): urwid text wrap.
            allow_tab (optional): bool if tab in edit text is allowable.
            edit_pos (optional): initial edit text cursor position.
            layout (optional): urwid text layout instance.
            mask (optional): edit text character mask.
            validator (optional): validator function, if omitted validation is
                disabled.  The validator is also used for value conversion of
                the edit text string.
        """
        self._last_validated = None
        self._validator = validator

        # Ensure the original text is actually valid.  Do not catch
        # exceptions here.
        if self._validator is not None:
            self._validator(edit_text)
            self._last_validated = edit_text

        super(ValidatedEdit, self).__init__(caption=caption,
                edit_text=edit_text, multiline=multiline, align=align,
                wrap=wrap, allow_tab=allow_tab, edit_pos=edit_pos,
                layout=layout, mask=mask)

    def validate(self):
        """Validate edit text, if invalid reset edit text to last good value,
        log info and raise ValidatedEditError."""
        if self._validator is None:
            return

        try:
            self._validator(self.edit_text)
            self._last_validated = self.edit_text
        except (PreferencesTypeError, TypeError, ValueError) as e:
            log.info(util.exception_string(e))
            invalid_text = self.edit_text
            self.edit_text = self._last_validated
            raise ValidatedEditError(invalid_text, e)

    def value(self):
        """Perform conversion of edit text using validator.  Returns edit text
        if validator is disabled."""
        if self._validator is not None:
            value = self._validator(self.edit_text)
        else:
            value = self.edit_text

        return value

    def on_focus_out(self):
        """Call backed used when focus leaves widget to call validator."""
        self.validate()


class NestableSelectEventLoop(urwid.main_loop.SelectEventLoop):
    """Nestable run event loop that does not catch ExitMainLoop to allow
    it to propagate to the top level."""
    # See urwid.main_loop.SelectEventLoop.run for the original function.
    def nested_run(self):
        self._did_something = True
        while True:
            try:
                self._loop()
            except select.error as e:
                if e.args[0] != 4:
                    # not just something we need to retry
                    raise
