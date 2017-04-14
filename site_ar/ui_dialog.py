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
import errno
import functools
import logging
import operator
import shlex
import types
import unicodedata
import urwid


from . import prefs
from . import ui_base
from . import util
from .exceptions import UIError, PreferencesTypeError, ValidatedEditError


log = logging.getLogger(__name__)


DIALOG_BASE_ROWS_COLS = (7, 8)
DIALOG_TITLE_ROWS = 2
ERROR_DIALOG_ROWS_COLS = (9, 8)


class DialogExit(Exception):
    """Exception used for exiting dialogs and returning a status code."""

    def __init__(self, status=None):
        self.status = status


class DialogWidgetMixin(object):
    exit_on_esc = None
    exit_on_space = None
    # Note: Catching enter will prevent buttons from working.
    exit_on_enter = None

    def exit(self, status=None):
        """Raise DialogExit to exit dialog and return status code."""
        raise DialogExit(status)

    def btnexit(self, button, status=None):
        """Generic button exit callback."""
        self.exit(status)

    def keypress(self, size, key):
        """Catch common dialog keys based on instance variables."""
        if self.exit_on_esc is not None and key == 'esc':
            self.exit(self.exit_on_esc)
        if self.exit_on_enter is not None and key == 'enter':
            self.exit(self.exit_on_enter)
        if self.exit_on_space is not None and key == ' ':
            self.exit(self.exit_on_space)

        return super(DialogWidgetMixin, self).keypress(size, key)

    def create_button(self, label, callback, user_data=None, attr=None,
            focus_attr=None):
        """Create a button for this dialog.

        Args:
            label: button string.
            callback: button on press callback.  This function may be an
                unbound method only if the function is part of the class
                containing this mixin.  This is useful for creating dialog
                templates without an instance available.
            user_data (optional): callback data.
            attr (optional): button default attr key.
            focus_attr (optional): button focus attr key.

        Returns:
            urwid.Button.
        """
        # Bind unbound methods to this instance only if the method belongs
        # to this class or parent.
        if isinstance(callback, types.MethodType) and callback.im_self is None:
            if issubclass(self.__class__, callback.im_class):
                callback = callback.__get__(self, self.__class__)
            else:
                raise UIError('can not bind callback: {} to {}'.format(
                        callback, self))

        button = urwid.Button(label, callback, user_data)
        button._w = urwid.AttrMap(button._w, None)

        if attr is not None:
            button._w.set_attr_map({None: attr})
        if focus_attr is not None:
            button._w.set_focus_map({None: focus_attr})

        return button


# contains body, title (header), footer (buttons), tabbing to footer
class DialogFrameWidget(DialogWidgetMixin, urwid.Frame):
    """Package common dialog elements into a urwid.Frame."""

    def __init__(self, ui, body, title=None, title_attr=None, buttons=None,
            button_focus=False, on_focus_changed=None, user_data=None):
        """Initializer.

        Args:
            ui: ui_top.UIMain.
            body: widget used for body.
            title (optional): string or widget for title (frame header).
            title_attr (optional): title default attr key.
            buttons (optional): list of button description tuples in the format
                (<label>, <callback>, [user_data], [bool default focus]).
            button_focus (optional): bool if buttons are in focus by default.
            on_focus_changed (optional): callback used when switching between
                buttons and body.
            user_data (optional): on_focus_changed callback data.
        """
        self.ui = ui

        self._dfw_header = None
        self._dfw_footer = None
        self._dfw_body = body
        self._dfw_buttons = None
        self._on_focus_changed = on_focus_changed
        self._user_data = user_data

        self.exit_on_esc = 0

        if isinstance(title, basestring):
            # Default style.
            divchr = unicodedata.lookup('BOX DRAWINGS HEAVY HORIZONTAL')
            title = urwid.Text(title, align=urwid.CENTER)
            if title_attr is not None:
                title = urwid.AttrMap(title, title_attr)
            self._dfw_header = urwid.Pile([title, urwid.Divider(divchr)])
        elif title is not None:
            # Directly apply title to frame header.
            self._dfw_header = title

        focus_part = 'body'

        if buttons is not None:
            button_widgets = []
            focus_position = None
            for index, button_desc in enumerate(buttons):
                button_widgets.append(self.create_button(button_desc[0],
                        button_desc[1], util.getindex(button_desc, 2, None),
                        'button', 'button focus'))

                # Set default focus to first found button with default set.
                if focus_position is None and util.getindex(button_desc, 3,
                        False):
                    focus_position = index

            # Gridflow containing buttons.
            self._dfw_buttons = ui_base.GridFlowBase(cells=button_widgets,
                    cell_width=10, h_sep=3, v_sep=1, align=urwid.CENTER)

            if focus_position is not None:
                self._dfw_buttons.focus_position = focus_position

            divchr = unicodedata.lookup('BOX DRAWINGS HEAVY HORIZONTAL')
            self._dfw_footer = urwid.Pile([urwid.Divider(divchr),
                    self._dfw_buttons], focus_item=1)

            if button_focus:
                focus_part = 'footer'

        super(DialogFrameWidget, self).__init__(self._dfw_body,
                header=self._dfw_header, footer=self._dfw_footer,
                focus_part=focus_part)

    def set_on_focus_changed(self, on_focus_changed, user_data):
        """Change on_focus_changed callback."""
        self._on_focus_changed = on_focus_changed
        self._user_data = user_data

    def get_ui(self):
        """Get ui_top.UIMain object."""
        return self.ui

    def switch_focus(self):
        """Switch focus between body and buttons."""
        if self._dfw_footer is not None:
            if self.focus_position == 'body':
                self.focus_position = 'footer'
            else:
                self.focus_position = 'body'

            if self._on_focus_changed is not None:
                self._on_focus_changed(self._user_data)

            # Let caller know focus changed.
            return True

        # Frame does not have footer/buttons, focus did not change.
        return False

    def keypress(self, size, key):
        """Catch tab key for switching focus."""
        if key == 'tab':
            if self.switch_focus():
                return None
            # Didn't switch focus, fall through and pass 'tab' key down.

        return super(DialogFrameWidget, self).keypress(size, key)


# Decorates, handles start/exit exception
class DialogBase(urwid.WidgetWrap):
    """Build dialog into urwid.Overlay, handle running the dialog over the
    current display and returning a status code on exit."""

    def __init__(self, ui, top_w, bottom_w, width=(urwid.RELATIVE, 80),
            height=(urwid.RELATIVE, 80), ignore_keys=None):
        """Initializer.

        Args:
            ui: ui_top.UIMain.
            top_w: dialog widget to overlay.
            bottom_w: widget to display dialog over.  Typically the current
                view but may be another dialog if nested.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            ignore_keys (optional): list of keys for overlay to catch and drop
                or all to drop all keys.
        """
        self.ui = ui

        # If this dialog is called from a key at the top level
        # (MainLoop.__init__ unhandled_input arg) we may want to catch the
        # key in the dialog to prevent multiple instances of the same dialog.
        if ignore_keys is None:
            ignore_keys = tuple()
        self.ignore_keys = ignore_keys

        # Pad area around top_w.
        top_w = urwid.Padding(top_w, (ui_base.FIXED_LEFT, 2),
                (ui_base.FIXED_RIGHT, 2))
        top_w = urwid.Filler(top_w, (ui_base.FIXED_TOP, 1),
                (ui_base.FIXED_BOTTOM, 1))
        top_w = urwid.AttrMap(top_w, {None: 'body'})

        # Create box around the overlay.
        top_w = ui_base.HeavyLineBox(top_w)
        top_w = urwid.AttrMap(top_w, {None: 'border'})

        # Clear space on top of vertical shadow.
        v_shadow = urwid.Filler(urwid.Text(('body', '  ')), urwid.TOP)
        # Use attr map to create vertical shadow.
        v_shadow = urwid.AttrMap(v_shadow, {None: 'shadow'})
        # Apply to widget.
        top_w = urwid.Columns([top_w, (urwid.FIXED, 2, v_shadow)])

        # Clear space on left of horizontal shadow.
        h_shadow = urwid.Text(('body', '  '))
        # Use attr map to create horizontal shadow.
        h_shadow = urwid.AttrMap(h_shadow, {None: 'shadow'})
        # Apply to widget.
        top_w = urwid.Frame(top_w, footer=h_shadow)

        self.overlay = urwid.Overlay(top_w, bottom_w, urwid.CENTER, width,
                urwid.MIDDLE, height)

        self.bottom_w = bottom_w
        self.top_w = top_w

        super(DialogBase, self).__init__(self.overlay)

    def get_ui(self):
        """Get ui_top.UIMain object."""
        return self.ui

    def keypress(self, size, key):
        """Pass keys down to top_w then drop any remaining ignored keys."""
        # Pass keypress down the chain (typically DialogFrameWidget or
        # child).  This will handle DialogWidgetMixin.exit_on_*, text input
        # or buttons.
        key = super(DialogBase, self).keypress(size, key)

        # Next check for specific ignored keys.
        if isinstance(self.ignore_keys, (tuple, list)) \
                and key in self.ignore_keys:
            return None

        # Trap keypress if blanket ignore to prevent it going back up to
        # the top.
        if self.ignore_keys == 'all':
            return None

        return key

    def start(self):
        """Start dialog, catch DialogExit and return status."""
        loop = self.get_ui().loop
        current_widget = loop.widget

        # This is a bit of a kludge but by calling the event_loop directly
        # this function becomes a blocking call while the dialog is active.
        # By using a unique exception to exit it allows any widget contained
        # within DialogBase to provide a return value and exit the dialog.
        # This is similar to how urwid uses the ExitMainLoop exception,
        # but also requires the nested_run function (see below).
        try:
            loop.widget = self
            loop.event_loop.nested_run()
        except DialogExit as e:
            return e.status
        finally:
            loop.widget = current_widget


class SimpleDialog(object):
    """Simple dialog made up of a single markup or widgets with optional title
    and buttons."""

    def __init__(self, ui, markup=None, widget=None,
            width=(urwid.RELATIVE, 25), height=(urwid.RELATIVE, 25),
            title=None, title_attr=None, buttons=None, ignore_keys=None):
        """Initializer.  Either markup or widget must be defined, markup will
        take precedence over widget.

        Args:
            ui: ui_top.UIMain.
            markup (optional): urwid markup to use as body.
            widget (optional): widget or list of widgets to use as body.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            title (optional): string or widget for title.
            title_attr (optional): title default attr key.
            buttons (optional): list of button description tuples.
            ignore_keys (optional): list of dialog ignore keys.
        """
        if markup is None and widget is None:
            raise UIError('No data to display')
        if markup is not None and widget is not None:
            raise UIError('markup and widget both set')

        if isinstance(widget, basestring):
            # urwid just gives error about invalid rows or height if you
            # make this mistake.
            raise UIError('use markup argument for strings')

        if markup is not None:
            widget = ui_base.markup_to_text(markup, align=urwid.CENTER)

        if not isinstance(widget, (tuple, list)):
            widget = [widget,]

        listbox = ui_base.ListBoxBase(urwid.SimpleListWalker(widget))

        self.ui = ui

        self.dialog_frame = DialogFrameWidget(ui, listbox, title=title,
                title_attr=title_attr, buttons=buttons, button_focus=True)

        self.dialog = DialogBase(ui, self.dialog_frame, ui.loop.widget,
                width=width, height=height, ignore_keys=ignore_keys)

    def start(self):
        """Start dialog and return status on exit."""
        return self.dialog.start()


class BusyDialog(SimpleDialog):
    """Buttonless dialog that will call a callback and can clear key input
    before exit."""

    def __init__(self, ui, callback, user_data, markup=None, widget=None,
            width=(urwid.RELATIVE, 25), height=(urwid.RELATIVE, 25),
            title=None, title_attr=None, ignore_keys=None):
        """Initializer.  Either markup or widget must be defined, widget will
        take precedence over markup.

        Args:
            ui: ui_top.UIMain.
            callback: pre exit callback.
            user_data: pre exit callback data.
            markup (optional): urwid markup to use as body.
            widget (optional): widget or list of widgets to use as body.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            title (optional): string or widget for title.
            title_attr (optional): title default attr key.
            ignore_keys (optional): list of dialog ignore keys.
        """
        if not callable(callback):
            raise ValueError('callback must be callable')

        self.callback = callback
        self.user_data = user_data

        # Apply default markup for busy dialog.  If markup and widget
        # are set pass error to SimpleDialog.
        if markup is not None and widget is None:
            widget = ui_base.markup_to_text(markup, align=urwid.CENTER)
            markup = None

        super(BusyDialog, self).__init__(ui, markup=markup, widget=widget,
                width=width, height=height, title=title,
                title_attr=title_attr, buttons=None, ignore_keys=ignore_keys)

    def start(self, clear_input=False):
        """Start dialog and return status on exit.

        Args:
            clear_input (optional): bool clear all key input before returning.
        """
        loop = self.dialog.get_ui().loop
        current_widget = loop.widget
        loop.widget = self.dialog
        loop.draw_screen()

        self.callback(self.user_data)

        loop.widget = current_widget

        if clear_input is True:
            codes = loop.screen.get_available_raw_input()
            dropped = len(codes)
            if dropped:
                log.debug('dropping {} code(s)'.format(dropped))


class ConfirmDialog(SimpleDialog):
    """OK/Cancel confirm dialog.  OK will exit with status 1 and Cancel 0."""

    def __init__(self, ui, markup=None, widget=None,
            width=(urwid.RELATIVE, 25), height=(urwid.RELATIVE, 25),
            ignore_keys=None):
        """Initializer.  Either markup or widget must be defined, widget will
        take precedence over markup.

        Args:
            ui: ui_top.UIMain.
            markup (optional): urwid markup to use as body.
            widget (optional): widget or list of widgets to use as body.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            ignore_keys (optional): list of dialog ignore keys.
        """
        # Apply default markup for confirm dialog.  If markup and widget
        # are set pass error to SimpleDialog.
        if markup is not None and widget is None:
            widget = ui_base.markup_to_text(markup, align=urwid.CENTER)
            markup = None

        buttons = (
            ('OK', DialogFrameWidget.btnexit, 1, True),
            ('CANCEL', DialogFrameWidget.btnexit, 0)
        )

        super(ConfirmDialog, self).__init__(ui, markup=markup, widget=widget,
                width=width, height=height, buttons=buttons,
                ignore_keys=ignore_keys)


class ErrorDialog(SimpleDialog):
    """Simple OK only error dialog that uses 'error' style for the title."""

    def __init__(self, ui, markup=None, widget=None,
            width=(urwid.RELATIVE, 25), height=(urwid.RELATIVE, 25),
            ignore_keys=None):
        """Initializer.  Either markup or widget must be defined, widget will
        take precedence over markup.

        Args:
            ui: ui_top.UIMain.
            markup (optional): urwid markup to use as body.
            widget (optional): widget or list of widgets to use as body.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            ignore_keys (optional): list of dialog ignore keys.
        """
        # Apply default markup for error dialog.  If markup and widget
        # are set pass error to SimpleDialog.
        if markup is not None and widget is None:
            widget = ui_base.markup_to_text(markup, align=urwid.CENTER)
            markup = None

        buttons = (
            ('OK', DialogFrameWidget.btnexit, 1, True),
        )

        super(ErrorDialog, self).__init__(ui, markup=markup, widget=widget,
                width=width, height=height, title='ERROR',
                title_attr='error', buttons=buttons, ignore_keys=ignore_keys)


class SimpleEditDialog(object):
    """Single edit box dialog with OK/Cancel buttons."""

    def __init__(self, ui, field, default=None, markup=None, widget=None,
            width=(urwid.RELATIVE, 25), height=(urwid.RELATIVE, 25),
            title=None, ignore_keys=None):
        """Initializer.  Either markup or widget must be defined, widget will
        take precedence over markup.

        Args:
            ui: ui_top.UIMain.
            field: edit box label.
            default: edit box default value.
            markup (optional): urwid markup to use before edit box.
            widget (optional): widget or list of widgets to use before edit
                box.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            title (optional): string or widget for title.
            ignore_keys (optional): list of dialog ignore keys.
        """
        # simple_edit_dialog does not require markup or widget,
        # the caller may just use field as the full prompt.
        if markup is not None and widget is not None:
            raise UIError('markup and widget both set')

        if isinstance(widget, basestring):
            # urwid just gives error about invalid rows or height if you
            # make this mistake.
            raise UIError('use markup argument for strings')

        if markup is not None:
            widget = ui_base.markup_to_text(markup, align=urwid.CENTER)

        # No data, just build an empty list to add the edit box to.
        if widget is None:
            widget = []

        if not isinstance(widget, (tuple, list)):
            widget = [widget,]

        self.edit = urwid.Edit('{}: '.format(field))
        if default is not None:
            self.edit.edit_text = default
            self.edit.edit_pos = len(default)

        edit_attr = urwid.AttrMap(self.edit, {None: 'body'}, {None: 'focus'})
        widget.append(edit_attr)

        listbox = urwid.ListBox(urwid.SimpleListWalker(widget))

        buttons = (
            ('OK', DialogFrameWidget.btnexit, 1, True),
            ('CANCEL', DialogFrameWidget.btnexit, 0)
        )

        self.ui = ui

        self.dialog_frame = DialogFrameWidget(ui, listbox, title=title,
                buttons=buttons, button_focus=False)

        self.dialog = DialogBase(ui, self.dialog_frame, ui.loop.widget,
                width=width, height=height, ignore_keys=ignore_keys)

    def start(self):
        """Start dialog, if OK is hit return edit box value, if cancel
        return None."""
        ret = self.dialog.start()

        if ret:
            return self.edit.edit_text
        return None


class OnFocusEditDialog(object):
    """Multiple edit box dialog with OK/Cancel buttons.  on_focus_out and
    on_focus_in will be called on each widget in the body."""

    def __init__(self, ui, edit_mapping=None, markup=None, widgets=None,
            width=(urwid.RELATIVE, 25), height=(urwid.RELATIVE, 25),
            title=None, ignore_keys=None):
        """Initializer.  Either widgets or edit_mapping must be defined,
        widgets will take precedence over edit_mapping.

        Args:
            ui: ui_top.UIMain.
            edit_mapping: values in the mapping are either strings for edit
                box labels or tuples in the format (<label>,
                [initial edit text]).  The keys are used to return a mapping
                where values are the edit text values.  Must support item
                iteration, use OrderedDict if edit box ordering is required.
            markup (optional): urwid markup to use before edit boxes.
            widget (optional): widget or list of widgets to use for body.
            width (optional): urwid dimension tuple.
            height (optional): urwid dimension tuple.
            title (optional): string or widget for title.
            ignore_keys (optional): list of dialog ignore keys.
        """
        # mapping must be dict like.
        if edit_mapping is None and widgets is None:
            raise UIError('No edit data to display')
        if edit_mapping is not None and widgets is not None:
            raise UIError('edit_mapping and widgets both set')

        self._widgets = widgets
        self._edit_mapping = edit_mapping

        if widgets is None:
            if markup is None:
                widgets = list()
            else:
                widgets = [ui_base.markup_to_text(markup,
                        align=urwid.CENTER),]
            if hasattr(edit_mapping, 'iteritems'):
                items = edit_mapping.iteritems()
            elif hasattr(edit_mapping, 'items'):
                items = edit_mapping.items()
            else:
                raise TypeError('edit_mapping must support item iteration')

            mapping = {}
            for edit_key, edit_value in items:
                edit_widget = self._edit_value_to_widget(edit_value)
                mapping[edit_key] = edit_widget
                edit_widget = urwid.AttrMap(edit_widget, {None: 'body'},
                        {None: 'focus'})
                widgets.append(edit_widget)

            self._edit_mapping = mapping

        self.list_walker = urwid.SimpleFocusListWalker(widgets)
        self.list_walker.set_focus_changed_callback(self.focus_changed)
        listbox = urwid.ListBox(self.list_walker)

        listbox._command_map = listbox._command_map.copy()
        listbox._command_map['enter'] = urwid.CURSOR_DOWN

        buttons = (
            ('OK', DialogFrameWidget.btnexit, 1, True),
            ('CANCEL', DialogFrameWidget.btnexit, 0)
        )

        self.ui = ui

        self.dialog_frame = DialogFrameWidget(ui, listbox, title=title,
                buttons=buttons, button_focus=False,
                on_focus_changed=self.focus_changed, user_data=-1)

        self.dialog = DialogBase(ui, self.dialog_frame, ui.loop.widget,
                width=width, height=height, ignore_keys=ignore_keys)

    def _edit_value_to_widget(self, edit_value):
        """Change edit_value from mapping to a uwrid.Edit widget.  Overload
        this to change how edit_mapping is used by the class."""
        if isinstance(edit_value, basestring):
            widget = urwid.Edit(caption=edit_value)
        else:
            caption = edit_value[0]
            edit_text = util.getindex(edit_value, 1, u'')
            widget = urwid.Edit(caption=caption, edit_text=edit_text)

        return widget

    def get_widget(self, index):
        """Get widget by index."""
        if index is None:
            return None
        return self.list_walker[index].original_widget

    def widget_on_focus_out(self, widget):
        """Dispatch on_focus_out to widget."""
        widget.on_focus_out()

    def widget_on_focus_in(self, widget):
        """Dispatch on_focus_in to widget."""
        widget.on_focus_in()

    def focus_changed(self, new_focus):
        """Callback when focus changes between body and buttons or when focus
        changes between widgets in body (handled by
        urwid.SimpleFocusListWalker)."""
        if new_focus >= 0:
            focus_out = self.list_walker.focus
            focus_in = new_focus
        else:
            if self.dialog_frame.focus_position == 'body':
                focus_out = None
                focus_in = self.list_walker.focus
            else:
                focus_out = self.list_walker.focus
                focus_in = None

        widget_out = self.get_widget(focus_out)
        if hasattr(widget_out, 'on_focus_out'):
            self.widget_on_focus_out(widget_out)

        widget_in = self.get_widget(focus_in)
        if hasattr(widget_in, 'on_focus_in'):
            self.widget_on_focus_in(widget_in)

    def get_edit_mapping_value(self, edit_value):
        """Get value from edit_mapping text.  Overload to perform automatic
        value conversion."""
        return edit_value.edit_text

    def results(self):
        """If initialized with widgets returns widgets, else extract values
        from widgets created from edit mapping using the same keys."""
        if self._widgets is not None:
            return self._widgets
        else:
            ret = {}
            for k, v in self._edit_mapping.items():
                ret[k] = self.get_edit_mapping_value(v)
            return ret

    def start(self):
        """Start dialog and return edit box results if OK is hit."""
        ret = self.dialog.start()

        if ret:
            return self.results()
        return None


class ValidatedEditDialog(OnFocusEditDialog):
    """Multiple validated edit box dialog with OK/Cancel buttons.  Values in
    edit_mapping are either strings to be used as labels or in the format
    (<label>, [initial edit text], [validator function])."""

    def _edit_value_to_widget(self, edit_value):
        """Change edit_value from mapping to a ui_base.ValidatedEdit
        widget."""
        if isinstance(edit_value, basestring):
            widget = ui_base.ValidatedEdit(caption=edit_value)
        else:
            caption = edit_value[0]
            edit_text = util.getindex(edit_value, 1, u'')
            validator = util.getindex(edit_value, 2, None)
            widget = ui_base.ValidatedEdit(caption=caption,
                    edit_text=edit_text, validator=validator)

        return widget

    def get_edit_mapping_value(self, edit_value):
        """If validator is defined for edit box call value or return string."""
        if hasattr(edit_value, 'value'):
            return edit_value.value()
        else:
            return edit_value.edit_text

    def widget_on_focus_out(self, widget):
        """Call on_focus_out and catch ValidatedEditError logging an info
        and showing a dialog with the validator error."""
        try:
            widget.on_focus_out()
        except ValidatedEditError as e:
            err_msg = util.exception_string(e)
            orig_err_msg = util.exception_string(e.orig_exc)
            log.info('{} caused by: {}'.format(err_msg, orig_err_msg))

            markup = '{}\ncaused by: {}'.format(str(e), orig_err_msg)
            widget = ui_base.markup_to_text(markup, align=urwid.LEFT,
                    wrap=urwid.ANY)

            width, _ = self.ui.get_screen_relative((80, None))
            width, height = widget.original_widget.pack((width,))
            err_dialog = ErrorDialog(self.ui, widget=widget,
                    width=width + ERROR_DIALOG_ROWS_COLS[1],
                    height=height + ERROR_DIALOG_ROWS_COLS[0])
            err_dialog.start()


class SearchDialog(object):
    """Predefined search dialog with any/all/not edit boxes and optional
    table and column."""

    def __init__(self, ui, search_type=None, title=None, prompt_table=False,
            prompt_column=False):
        """Initializer.  Either search_type or title must be defined,
        title will take precedence over search_type.

        Args:
            ui: ui_top.UIMain.
            search_type (optional): search type string, will create title in
                the format 'Search <search_type>'
            title (optional): string or widget for title.
            prompt_table (optional): bool to display table name edit box.
            prompt_column (optional): bool to display column name edit box.
        """
        height = DIALOG_BASE_ROWS_COLS[0]
        edit_mapping = []

        if search_type is not None and title is None:
            title = 'Search {}'.format(search_type)

        if title is not None:
            height += DIALOG_TITLE_ROWS

        if prompt_table is True:
            edit_mapping.append(('table', 'table: '))
        if prompt_column is True:
            edit_mapping.append(('column', 'column: '))

        edit_mapping += [
                ('all_terms', ('all terms: ', '', shlex.split)),
                ('any_terms', ('any terms: ', '', shlex.split)),
                ('not_terms', ('not terms: ', '', shlex.split))
        ]

        edit_mapping = collections.OrderedDict(edit_mapping)
        height += len(edit_mapping)

        self.dialog = ValidatedEditDialog(ui, edit_mapping=edit_mapping,
                width=(urwid.RELATIVE, 80), height=height,
                title=title)

    def start(self):
        """Start dialog and return edit box results if OK is hit."""
        return self.dialog.start()


class EditPreferencesDialog(object):
    """Edit preferences dialog."""

    def __init__(self, ui):
        """Initializer.

        Args:
            ui: ui_top.UIMain.
        """
        height = DIALOG_BASE_ROWS_COLS[0] + DIALOG_TITLE_ROWS

        edit_mapping = []
        for pref_key, pref_value in prefs.iterprefs():
            validator = functools.partial(prefs.convert, pref_key)
            caption = '{}: '.format(pref_key)
            mapping = (pref_key, (caption, str(pref_value), validator))
            edit_mapping.append(mapping)

        edit_mapping.sort(key=operator.itemgetter(0))

        for mapping in edit_mapping:
            log.debug(mapping)

        edit_mapping = collections.OrderedDict(edit_mapping)

        height += len(edit_mapping)
        height = ui_base.min_height(height, (urwid.RELATIVE, 80),
                ui.screen_rows)

        self.dialog = ValidatedEditDialog(ui, edit_mapping=edit_mapping,
                width=(urwid.RELATIVE, 80), height=height,
                title='Edit Preferences')

    def start(self):
        """Start dialog, if OK is hit log preferences and save to database."""
        mapping = self.dialog.start()
        if mapping is None:
            return

        log.debug('edit prefs: {}'.format(mapping))

        for pref_key, pref_value in mapping.iteritems():
            prefs.set(pref_key, pref_value)

        prefs.save()


class SaveDialog(object):
    """Save file dialog.  The dialog remains opens until a path is entered
    that can be created or written.  If an invalid path is entered an error
    dialog will popup and the save dialog will continue.  If the path entered
    already exists it will prompt to ensure overwrite."""

    _err_mapping = {
        errno.EACCES: 'Invalid access for \'{path}\'',
        errno.EISDIR: '\'{path}\' is a directory',
        errno.ENOENT: 'Invalid path \'{path}\''
    }

    def __init__(self, ui, markup=None, title=None, default=None):
        height = DIALOG_BASE_ROWS_COLS[0] + 1
        edit_mapping = []

        if markup is not None and title is None:
            title = '{}'.format(markup)

        if title is not None:
            height += DIALOG_TITLE_ROWS

        self.ui = ui

        self.dialog = SimpleEditDialog(ui, 'path', default=default,
                width=(urwid.RELATIVE, 80), height=height, title=title)

    def start(self):
        """Start dialog.  If OK is hit test if path if file can be created or
        written."""
        while True:
            path = self.dialog.start()
            log.debug('export dialog returned: \'{}\''.format(path))
            if path is None or path == '':
                path = None
                break

            ret = util.test_create(path)
            if ret == 0:
                break
            elif ret == errno.EEXIST:
                markup = ('\'{}\' already exists.\n'
                        'Are you sure you want to overwrite?')
                markup = markup.format(path)
                widget = ui_base.markup_to_text(markup, align=urwid.CENTER)
                width, _ = self.ui.get_screen_relative((80, None))
                width, height = widget.original_widget.pack((width,))
                dialog = ConfirmDialog(self.ui, widget=widget,
                        width=width + DIALOG_BASE_ROWS_COLS[1],
                        height=height + DIALOG_BASE_ROWS_COLS[0])
                ret = dialog.start()
                if ret == 1:
                    break
            elif ret in self._err_mapping.keys():
                markup = self._err_mapping[ret].format(path=path)
                widget = ui_base.markup_to_text(markup, align=urwid.CENTER)
                width, _ = self.ui.get_screen_relative((80, None))
                width, height = widget.original_widget.pack((width,))
                dialog = ErrorDialog(self.ui, widget=widget,
                        width=width + ERROR_DIALOG_ROWS_COLS[1],
                        height=height + ERROR_DIALOG_ROWS_COLS[0])
                dialog.start()
            else:
                err = 'unexpected error \'{}\' for path \'{}\''.format(
                        errno.errorcode.get(ret, 'UNKNOWN'), path)
                raise ValueError(err)

        return path
