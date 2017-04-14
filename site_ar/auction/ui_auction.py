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

import functools
import logging
import unicodedata
import urwid


from .. import dbdrv
from .. import export
from .. import ui_base
from .. import ui_dialog
from .. import ui_top
from .. import util
from ..exceptions import ExtractError


log = logging.getLogger(__name__)


AUCTION_EXTRACT_LIST = [
    '.extract_auction_test.ExtractAuctionTestLL',
    '.extract_auction_test.ExtractAuctionTestUSAAuctions'
]
# Call get_mod_obj at the top level so all extractors are loaded when this
# file is loaded.  This ensures any preferences are added before the UI
# is started.
map(lambda x: util.get_mod_obj(x, package=__package__), AUCTION_EXTRACT_LIST)


class AuctionHouseNode(ui_base.TreeRootNodeList):
    """Top level node representing each auction house site."""

    def __init__(self, ui, value_list, parent=None, key=None, depth=None):
        """Initializer.

        Args:
            db DBDriver object.
            ui: UIMain.
            value_list: either list of auction house extractor objects or
                SiblingList.
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
        """
        self.ui = ui
        super(AuctionHouseNode, self).__init__(value_list, parent=parent,
                key=key, depth=depth)

    def load_widget(self):
        """Create and return ui_top.UITreeWidget for self."""
        return ui_top.UITreeWidget(self)

    def load_child_keys(self):
        """Return list of auction ids for children of this auction house."""
        ah = self.get_auction_house()
        return ah.get_auction_ids()

    def load_child_node(self, key):
        """Create and return an AuctionNode for child by key (auction id)."""
        return AuctionNode(self.get_ui(), self.get_auction_house(),
                parent=self, key=key, depth=self.get_depth() + 1)

    def get_sibling_node(self, key=None):
        """Get sibling auction house node by key.

        Args:
            key (optional): sibling key, if omitted gets self as sibling.

        Returns:
            Sibling AuctionHouseNode.
        """
        sibling = self.get_sibling(key)
        if sibling['node'] is None:
            sibling['node'] = AuctionHouseNode(self.ui,
                    self.get_value_list(), key=key)
        return sibling['node']

    def get_ui(self):
        """Get ui_top.UIMain object."""
        return self.ui

    def get_auction_house(self):
        """Return auction house extractor object for this node."""
        return self.get_sibling_data()

    def get_display_text(self):
        """Return nice auction house name for this node as string for display
        text."""
        return self.get_auction_house().name

    def get_type(self):
        return 'auction house'

    def get_detail_mapping(self):
        """Return auction house RowDO object as mapping."""
        return self.get_auction_house().get_auction_house_rdo()

    @property
    def export_title(self):
        return 'Export auction house: \'{}\''.format(self.get_display_text())

    def export(self, exporter):
        """Export all lots for all auctions in this auction house.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
        """
        log.debug('export called on: {}'.format(self))

        child_keys = self.get_child_keys()

        for child_key in child_keys:
            child_node = self.get_child_node(child_key)
            child_node.export(exporter)

            if child_key != child_keys[-1]:
                exporter.write_blank(2)

    def _do_update_cb(self, user_data):
        """Busy dialog callback to do update_all on this auction house."""
        self.get_auction_house().update_all()
        self._children.clear()
        self.get_child_keys(reload=True)

    def _do_update(self):
        """Show busy dialog and do update for this auction house."""
        title = 'Updating auction house...'

        markup = self.get_display_text()
        widget = ui_base.markup_to_text(markup, align=urwid.CENTER,
                wrap=urwid.ANY)

        width, _ = self.get_ui().get_screen_relative((80, None))
        width, height = widget.original_widget.pack((width,))
        width = max(width, len(title))

        busy_dialog = ui_dialog.BusyDialog(self.get_ui(), self._do_update_cb,
                None, widget=widget,
                width=width + ui_dialog.DIALOG_BASE_ROWS_COLS[1],
                height=height + ui_dialog.DIALOG_BASE_ROWS_COLS[0],
                title='Updating auction house...')
        busy_dialog.start(clear_input=True)

    def update(self):
        """Show busy dialog and do update for this auction house."""
        self._do_update()

    def update_all(self):
        """Call update on this auction house and all siblings."""
        for key in self.get_sibling_keys():
            self.get_sibling_node(key=key)._do_update()


def _csv_lot_rdo_export_prepare(rdo, disp_rdo):
    """Prepare callback for lot RowDO objects when using CSVExporter.  Changes
    price value into a nice format."""
    # Note: LibreOffice Calc does not handle the leading ' when opening
    # csv files.
    return util.mapping_price_fmt(rdo, fmt=util.CSV_PRICEFMT)


def _xlsx_lot_rdo_export_prepare(img_support, img_func, get_img, rdo,
        disp_rdo):
    """Prepare callback for lot RowDO objects when using XLSXExporter.  Changes
    price value into a nice format and embeds image object into RowDO
    object.

    Args:
        img_support: bool if embedding images is supported.
        img_func: function to convert image file to embeddable object.
        get_img: function to get image file from lot RowDO object.
        rdo: lot RowDO object to prepare.
        disp_rdo: lot RowDO being used for display and will not be changed.
    """
    if img_support is True:
        img_file = get_img(disp_rdo)
        if img_file is not None:
            rdo['img'] = img_func(img_file)
        else:
            rdo['img'] = 'Error: image not found'

    rdo['price'] = export.XLSXCurrency(rdo['price'])

    return rdo


class AuctionNode(ui_base.WeakRefParentNode,
        ui_base.RowDOChildrenExportMixin):
    """Parent node representing auction."""

    export_keys = ['img', 'desc', 'price', 'url']

    def __init__(self, ui, value, parent=None, key=None, depth=None):
        """Initializer.

        Args:
            db DBDriver object.
            ui: UIMain.
            value: auction RowDO object.
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
        """
        self.ui = ui
        self.db = ui.db
        super(AuctionNode, self).__init__(self.get_ui().loop, value,
                parent=parent, key=key, depth=depth)

    def load_widget(self):
        """Create and return ui_top.UITreeWidget for self."""
        return ui_top.UITreeWidget(self)

    def load_child_keys(self):
        """Return list of lot ids for children of this auction."""
        ah = self.get_auction_house()
        return ah.get_lot_ids(self.get_key())

    def _load_rdo(self, key):
        """Return lot RowDO object by key (lot id)."""
        return self.get_auction_house().get_lot(key)

    def load_child_node(self, key):
        """Create and return LotNode for child by key (lot id)."""
        return LotNode(self.ui, self._load_rdo(key), parent=self, key=key,
                depth=self.get_depth() + 1)

    def get_ui(self):
        """Get ui_top.UIMain object."""
        return self.ui

    def get_auction_house(self):
        """Return auction house extractor object for this node."""
        return self.get_value()

    def get_auction_rdo(self):
        """Return this auction as RowDO object."""
        ah = self.get_auction_house()
        auction = ah.get_auction(self.get_key())
        if auction is None:
            raise ExtractError('Invalid auction key {}'.format(self.get_key()))
        return auction

    def get_display_text(self):
        """Return nice auction name for this node as string for display
        text."""
        return self.get_auction_rdo()['name']

    def get_type(self):
        return 'auction'

    def get_detail_mapping(self):
        """Return auction RowDO object as mapping."""
        return self.get_auction_rdo()

    @property
    def export_title(self):
        return 'Export auction: \'{}\''.format(self.get_display_text())

    def export(self, exporter):
        """Export all lots for this auction.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
        """
        log.debug('export called on: {} exporter: {}'.format(self, exporter))

        house_name = self.get_auction_house().name
        auction_name = self.get_auction_rdo()['name']

        exporter.write_hdr(['Company: {}'.format(house_name),
                'Auction: {}'.format(auction_name)])

        if isinstance(exporter, export.CSVExporter):
            callback = _csv_lot_rdo_export_prepare
        elif isinstance(exporter, export.XLSXExporter):
            callback = functools.partial(_xlsx_lot_rdo_export_prepare,
                    exporter.img_support, exporter.image,
                    self.get_auction_house().get_lot_img)
        else:
            raise ValueError('unknown exporter: {}'.format(
                    type(exporter).__name__))

        log.debug('callback: {}'.format(callback))

        self.export_children(exporter, 'lot', get_child_mapping='get_value',
                rdo_callback=callback)


class LotNode(urwid.TreeNode):
    """Leaf node representing lot."""

    def __init__(self, ui, value, parent=None, key=None, depth=None):
        """Initializer.

        Args:
            db DBDriver object.
            ui: UIMain.
            value: lot RowDO object.
            parent (optional): urwid.TreeNode of parent.
            key (optional): int node key (list index).
            depth (optional): int this nodes depth.
        """
        self.ui = ui
        super(LotNode, self).__init__(value, parent=parent, key=key,
                depth=depth)

    def load_widget(self):
        """Create and return ui_top.UITreeWidget for self."""
        return ui_top.UITreeWidget(self)

    def get_ui(self):
        """Get ui_top.UIMain object."""
        return self.ui

    def get_auction_house(self):
        """Return auction house extractor object for this node."""
        # Lots will always have a parent with the auction house object.
        return self.get_parent().get_auction_house()

    def get_display_text(self):
        """Return lot description for this node as string for display text."""
        return self.get_value()['desc']

    def get_type(self):
        return 'lot'

    def get_detail_mapping(self):
        """Return lot RowDO object with pretty price formatting as mapping."""
        return util.mapping_price_fmt(self.get_value())


class AuctionSearchListBox(ui_top.UIRowDOSearchListBox):
    """Lot search result data view.  Results are displayed with the format
    '{:>16s} {}   {}' with formatter arguments (pretty price, separator,
    lot description)."""

    rdo_name = 'lot'
    export_keys = ['img', 'desc', 'price', 'house_id', 'auction_id', 'url']

    def format_rdo(self, rdo):
        """Return formatted string for lot RowDO object."""
        price = util.PRICEFMT.format(rdo['price'])
        return u'{:>16s} {}   {}'.format(price,
        unicodedata.lookup('BOX DRAWINGS HEAVY VERTICAL'), rdo['desc'])

    def get_type(self):
        return 'Lot'

    def get_detail_mapping(self):
        """Return lot RowDO object with pretty price formatting as mapping."""
        mapping = super(AuctionSearchListBox, self).get_detail_mapping()
        return util.mapping_price_fmt(mapping)

    @property
    def export_title(self):
        return 'Export lot search results'

    def _get_auction_house(self, lot_rdo):
        """Get auction house extractor object by lot RowDO object."""
        return self.ui.ah_mapping.get(lot_rdo['house_id'])

    def _get_auction_house_name(self, cache, lot_rdo):
        """Get nice auction house name by lot RowDO object.

        Args:
            cache: dict to be used as cache during export.
            lot_row: lot RowDO object.
        """
        house_id = lot_rdo['house_id']
        name, _ = cache.get(house_id, (None, None))
        if name is None:
            ah = self._get_auction_house(lot_rdo)
            name = ah.name
            cache[house_id] = (name, dict())
        return name

    def _get_auction_name(self, cache, lot_rdo):
        """Get nice auction name by lot RowDO object.

        Args:
            cache: dict to be used as cache during export.
            lot_row: lot RowDO object.
        """
        house_id = lot_rdo['house_id']
        auction_id = lot_rdo['auction_id']
        if not cache.has_key(house_id):
            self._get_auction_house_name(cache, lot_rdo)
        _, au_cache = cache[house_id]
        name = au_cache.get(auction_id, None)
        if name is None:
            auction = self._get_auction_house(lot_rdo).get_auction(
                    auction_id)
            name = auction['name']
            au_cache[auction_id] = name
        return name

    def export(self, exporter):
        """Export lot search results.

        Args:
            exporter: export object (CSVExporter or XLSXExporter).
        """
        log.debug('export called on: {}'.format(self))

        if isinstance(exporter, export.CSVExporter):
            is_xlsx = False
        elif isinstance(exporter, export.XLSXExporter):
            is_xlsx = True
        else:
            raise ValueError('unknown exporter: {}'.format(
                    type(exporter).__name__))

        contents = self.contents()

        keys = self.get_export_keys(contents)

        hdr = keys[:]
        util.listreplace(hdr, 'house_id', 'auction_house')
        util.listreplace(hdr, 'auction_id', 'auction')
        exporter.write_hdr(hdr)
        exporter.write_blank()

        cache = {}

        for widget in ui_base.listbox_contents_iter(contents):
            disp_rdo = self.get_rdo(widget)
            # Make a copy to leave the search results unchanged.
            lot_rdo = dbdrv.RowDO(disp_rdo)

            # Call *_export_prepare before modifying house_id.
            if is_xlsx:
                lot_rdo = _xlsx_lot_rdo_export_prepare(
                        exporter.img_support, exporter.image,
                        self._get_auction_house(lot_rdo).get_lot_img,
                        lot_rdo, disp_rdo)
            else:
                lot_rdo = _csv_lot_rdo_export_prepare(lot_rdo, disp_rdo)

            # Get house and auction names first before modifying the lot_rdo.
            house_name = self._get_auction_house_name(cache, lot_rdo)
            auction_name = self._get_auction_name(cache, lot_rdo)
            lot_rdo['house_id'] = house_name
            lot_rdo['auction_id'] = auction_name

            values = lot_rdo.values(keys)
            exporter.write_row(values)


def create_ah_list(db, dl_dir):
    """Dynamically load auction house extractor objects from paths defined
    in AUCTION_EXTRACT_LIST.

    Args:
        db: DBDriver object.
        dl_dir: path to download directory.

    Returns:
        List of ExtractAuctionBase objects.
    """
    ah_list = [util.get_mod_obj(x, package=__package__)[1] for x in
            AUCTION_EXTRACT_LIST]
    if None in ah_list:
        missing = AUCTION_EXTRACT_LIST[ah_list.index(None)]
        raise ImportError('Could not import object path: {}'.format(missing))
    ah_list = [x(db, dl_dir) for x in ah_list]

    for ah in ah_list:
        ah.dbinit()
    return ah_list


class AuctionUI(ui_top.UIMain):
    """Top level UI class for auction sites."""

    title = [
        'Auction site archiver'
    ]

    search_markup = [
        'Lot search results'
    ]

    def __init__(self, db, dl_dir, log_handler=None):
        """Initializer.

        Args:
            db: DBDriver object.
            dl_dir: path to download directory.
            log_handler (optional): UILoggingHandler object.
        """
        super(AuctionUI, self).__init__(db, dl_dir, log_handler)

    def init_data_view(self):
        """Initialize data view using AuctionHouseNodes for each auction house
        extractor object returned by create_ah_list."""
        ah_list = create_ah_list(self.db, self.dl_dir)
        self.ah_mapping = {x.id: x for x in ah_list}
        self.ah_root_node = AuctionHouseNode(self, ah_list)
        self.ah_data_view = ui_top.UITreeListBox(urwid.TreeWalker(
                self.ah_root_node))
        self.ah_data_view.offset_rows = 1

        return urwid.AttrMap(self.ah_data_view, {None: 'body'})

    def create_search_listbox(self, iterable):
        """Create and return search list box using AuctionSearchListBox.

        Args:
            iterable: iterable of RowDO objects.

        Returns:
            Decorated UIRowDOSearchListBox.
        """
        ret = AuctionSearchListBox(self, iterable, 'body', 'focus')
        return urwid.AttrMap(ret, {None: 'body'})

    def search_dialog(self):
        """Return parameters from search dialog with table and column
        fields predefined as lot and desc respectively."""
        dialog = ui_dialog.SearchDialog(self, search_type='lots',
                prompt_table=False, prompt_column=False)
        params = dialog.start()

        if params is not None:
            params['table'] = 'lot'
            params['column'] = 'desc'

        return params
