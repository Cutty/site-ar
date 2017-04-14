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

import abc
import functools
import logging


from .. import extract_base
from .. import util
from .. import dbdrv
from ..exceptions import ExtractSaveError


log = logging.getLogger(__name__)


class ExtractAuctionBase(extract_base.ExtractBase):
    """Base class for auction site extractors."""

    def __init__(self, db, dl_dir, req_throttle=None, req_stall=(None, None)):
        """Initializer for auction site extractor base class.  Can not be
        used on its own.

        Args:
            db: DBDriver object.
            dl_dir: string path to existing directory to download to file to.
            req_throttle (optional): True to enable request throttling.  If not
                set req_throttle will be based on preferences.
            req_stall (optional): tuple of (throttle base, throttle var)
                floats.  If left unset these values will be based on
                preferences.
        """
        super(ExtractAuctionBase, self).__init__(db, dl_dir, req_throttle,
                req_stall)

    def get_auction_house_rdo(self):
        """Return RowDO object from database for this auction house."""
        sql = 'SELECT * FROM auction_house WHERE name = \'{}\''.format(
                self.name)
        data = self.db.sr_execute(sql).fetchone()

        if data is not None:
            return self.db.rdo_ctors['auction_house']().from_row(data)

        return data

    def get_id(self):
        """Return auction house id (value from id column)."""
        rdo = self.get_auction_house_rdo()
        if rdo is not None:
            return rdo['id']
        return rdo

    def dbinit(self):
        """Initialize database.  If RowDO object for this auction house does
        not exist in database, create one."""
        super(ExtractAuctionBase, self).dbinit()

        au_id = self.get_id()

        if au_id is None:
            self.db.ins_rdo('auction_house',
                    self.db.rdo_ctors['auction_house'](
                    name=self.name, url=self.url))
            au_id = self.get_id()

        self.id = au_id

    def set_auction_status(self, auction_rdo, status):
        """Set status for auction in database.  Setting a status of 'complete'
        will cause update calls on this auction to be skipped.

        Args:
            auction_rdo: auction RowDO object.
            status: string to set.
        """
        sql = ('UPDATE auction SET status=\'{}\' '
                'WHERE id = {}').format(status, auction_rdo['id'])
        self.db.execute(sql)

    def update_auctions(self):
        """Update auction master list."""
        auctions = self.extract_auctions()

        sql = 'SELECT vendor_id FROM auction where house_id = {}'.format(
                self.id)
        existing_auctions = zip(*self.db.execall(sql))
        if len(existing_auctions) != 0:
            existing_auctions = existing_auctions[0]

        for auction_rdo in auctions:
            if auction_rdo['vendor_id'] in existing_auctions:
                log.debug('skipping: {}'.format(auction_rdo['vendor_id']))
                continue

            self.db.ins_rdo('auction', auction_rdo)

    def update_lots(self, auction_rdo):
        """Update lots for auction by auction RowDO object.  Once auction
        will be marked as 'complete'."""
        self.set_auction_status(auction_rdo, 'downloading')

        lots = self.extract_lots(auction_rdo)

        sql = 'SELECT vendor_id FROM lot WHERE auction_id = {}'.format(
                auction_rdo['id'])
        existing_lots = zip(*self.db.execall(sql))
        if len(existing_lots) != 0:
            existing_lots = existing_lots[0]

        for lot_rdo in lots:
            if lot_rdo['vendor_id'] in existing_lots:
                continue

            img_url, img_path = extract_base.urlpath_split(lot_rdo['img'])
            if img_url is not None and img_path is None:
                log.debug('calling dl_save: {}'.format(img_url))
                util.flush_log()
                try:
                    img_urlpath, _ = self.dl_save(img_url)
                except ExtractSaveError as e:
                    err = 'save error: {}'.format(util.exception_string(e))
                    log.error(err)
                    log.info('save error occurred for lot: {}'.format(
                            lot_rdo['desc']))
                    img_urlpath = None

                if img_urlpath is not None:
                    lot_rdo['img'] = img_urlpath

            self.db.ins_rdo('lot', lot_rdo)

        self.set_auction_status(auction_rdo, 'complete')

    def update_all(self):
        """Update master auction list and each auction not marked as
        'complete'."""
        self.update_auctions()

        sql = ('SELECT * FROM auction where house_id = {} '
                'AND NOT status = \'complete\'').format(self.id)
        auctions = self.db.sr_execall(sql)
        auctions = [self.db.rdo_ctors['auction']().from_row(x) for x in
                auctions]

        log.debug('updating: {}'.format(len(auctions)))

        for auction_rdo in auctions:
            self.update_lots(auction_rdo)

    def get_auction_ids(self):
        """Return list of ids for all auctions in this auction house."""
        return self.db.get_single_column('id', 'auction',
                'house_id = {}'.format(self.id))

    def _get_auction_data(self, func):
        """Create query to get all auction data and call func with string
        returning results."""
        sql = 'SELECT * FROM auction where house_id = {}'.format(self.id)
        return func(sql)

    def get_auction_rows(self):
        """Return all auction data for this auction house as sqlite3.Row
        objects."""
        return self._get_auction_data(self.db.row_iter)

    def get_auction_rdos(self):
        """Return all auction data for this auction house as RowDO objects."""
        func = functools.partial(self.db.rdo_iter,
                self.db.rdo_ctors['auction'])
        return self._get_auction_data(func)

    def get_auction(self, auction_id):
        """Return auction RowDO object by id."""
        sql = 'SELECT * FROM auction WHERE id = {}'.format(auction_id)
        auction = self.db.sr_execute(sql).fetchone()
        if auction is not None:
            auction = self.db.rdo_ctors['auction']().from_row(auction)
        return auction

    def get_lot_ids(self, auction_id):
        """Return list of ids for all lots in an auction by auction id."""
        return self.db.get_single_column('id', 'lot',
                'auction_id = {}'.format(auction_id))

    def _get_lot_data(self, func, auction_id):
        """Create query to get all lot data in auction by auction id and call
        func with string returning results."""
        sql = 'SELECT * FROM lot where auction_id = {}'.format(auction_id)
        return func(sql)

    def get_lot_rows(self, auction_id):
        """Return all lot data in auction by auction id as sqlite3.Row
        objects."""
        return self._get_lot_data(self.db.row_iter, auction_id)

    def get_lot_rdos(self, auction_id):
        """Return all lot data in auction by auction id as RowDO objects."""
        func = functools.partial(self.db.rdo_iter,
                self.db.rdo_ctors['lot'])
        return self._get_lot_data(func, auction_id)

    def get_lot(self, lot_id):
        """Return RowDO object for lot by lot id."""
        sql = 'SELECT * FROM lot WHERE id = {}'.format(lot_id)
        lot = self.db.sr_execute(sql).fetchone()
        if lot is not None:
            lot = self.db.rdo_ctors['lot']().from_row(lot)
        return lot

    def get_lot_img(self, lot_rdo):
        """Return image file in lot_rdo.  If file has not been downloaded it
        will be saved and then opened."""
        if not isinstance(lot_rdo, dbdrv.RowDO) or lot_rdo.name != 'lot':
            raise TypeError('lot_rdo must be \'lot\' dbdrv.RowDO')

        rdo_urlpath = lot_rdo['img']
        if not isinstance(rdo_urlpath, basestring) or rdo_urlpath == '':
            return None

        img_urlpath, img_file = self.get_file(rdo_urlpath)
        if img_urlpath != rdo_urlpath:
            sql = 'UPDATE lot SET img = \'{}\' WHERE id = {}'.format(
                    img_urlpath, lot_rdo['id'])
            self.db.execute(sql)
            lot_rdo['img'] = img_urlpath

        return img_file

    @abc.abstractproperty
    def name(self):
        """Return nice name for auction house."""
        pass

    @abc.abstractproperty
    def url(self):
        """Return top level url for auction house site."""
        pass

    @abc.abstractmethod
    def extract_auctions(self):
        """Extract auction master list from auction house site."""
        pass

    @abc.abstractmethod
    def extract_lots(self, auction_rdo):
        """Extract lots from auction house site by auction RowDO object."""
        pass
