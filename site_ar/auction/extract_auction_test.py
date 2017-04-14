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

from lxml import html
import logging
import re
import urlparse


from .. import extract_base
from .. import util
from .extract_auction_base import ExtractAuctionBase


log = logging.getLogger(__name__)


class ExtractAuctionTestLL(ExtractAuctionBase):
    """Test extractor for Local Liquidators local test site."""

    def __init__(self, db, dl_dir, req_throttle=None, req_stall=(None, None)):
        """Initializer for Local Liquidators local test site extractor base
        class.

        Args:
            db: DBDriver object.
            dl_dir: string path to existing directory to download to file to.
            req_throttle (optional): True to enable request throttling.  If not
                set req_throttle will be based on preferences.
            req_stall (optional): tuple of (throttle base, throttle var)
                floats.  If left unset these values will be based on
                preferences.
        """
        super(ExtractAuctionTestLL, self).__init__(db, dl_dir, req_throttle,
                req_stall)

    @property
    def name(self):
        return 'Local Liquidators'

    @property
    def url(self):
        return 'http://localhost:8080/html/ll_auctions/index.html'

    def extract_auctions(self):
        """Extract auction master list from Local Liquidators local test
        site."""
        auction_list = []

        listing_page = self.dl(self.url)
        if listing_page is None:
            log.error('Could not download {} main page.'.format(self.name))
            return auction_list
        listing_html = html.fromstring(listing_page)

        table_xpath = ('/html/body/div[@class="content"]/'
                'div[@class="column text-center"]/table')
        auction_table = util.getindex(listing_html.xpath(table_xpath), 0, None)
        if auction_table is None:
            log.warn('Could not find auction table')
            return auction_list

        auction_tr_elems = auction_table.xpath('./tr')
        if len(auction_tr_elems) == 0:
            log.warn('Coult not find auction rows')
            return auction_list

        for index, elem in enumerate(auction_tr_elems):
            a_elem = util.getindex(elem.xpath('.//p/a[@id="ayty"]'), 0, None)
            if a_elem is None:
                log.warn('Could not find auction link in tr element {}'.format(
                        index))
                continue

            title = a_elem.text
            if not isinstance(title, basestring) or len(title) == 0:
                log.warn('Invalid auction title in tr element {}'.format(
                        index))
                continue

            url = a_elem.attrib.get('href', None)
            vendor_id = url.split('/')[0]
            if url is None:
                log.warn('Invalid auction link in tr element {}'.format(
                        index))
                continue
            url = urlparse.urljoin(self.url, url)

            p_text_list = elem.xpath('.//p/text()')
            location = [x for x in p_text_list if x.lower().find(
                    'auction held in: ') != -1]
            location = util.getindex(location, 0, '')
            # All of the spaces should be cleaned up so just strip
            # 'Auction held in: ' by index, or the find failed and
            # location is an empty string.
            location = util.wsclean(location)[17:]

            # Peek at the first auction page to get the start/end times.
            auction_page = self.dl(url)
            if auction_page is None:
                fmt = 'Could not download auction page for tr element {}'
                log.error(fmt.format(index))
                continue
            auction_html = html.fromstring(auction_page)

            time_xpath = ('/html/body/div[@class="content"]/'
                    'div[@class="column text-center"]/p[@class="general"]/'
                    'text()')
            time_texts = auction_html.xpath(time_xpath)
            time_texts = [util.wsclean(x.lower()) for x in time_texts]
            start = [x for x in time_texts if x.find('opens: ') != -1]
            end = [x for x in time_texts if x.find('closes: ') != -1]
            start = util.getindex(start, 0, '')[7:]
            end = util.getindex(end, 0, '')[8:]

            if start == '':
                log.warn('Could not find start time for {}'.format(url))
            if end == '':
                log.warn('Could not find end time for {}'.format(url))

            auction_rdo = self.db.rdo_ctors['auction'](house_id=self.id,
                    vendor_id=vendor_id, name=title, location=location,
                    start_date=start, end_date=end, closed=1,
                    url=url, status='new')
            auction_list.append(auction_rdo)

        return auction_list

    def _extract_lot_rdos(self, auction_rdo, lot_list, url, lot_html):
        """Extract lot RowDO object by auction RowDO object from Local
        Liquidators lot page and append to lot_list."""
        lot_xpath = ('/html/body/div[@class="content"]/'
                'div[@class="column text-center"]/div[@class="view-past-lots"]')
        lot_elem = util.getindex(lot_html.xpath(lot_xpath), 0, None)
        if lot_elem is None:
            msg = 'Could not find lot element for {}'.format(url)
            log.warn(msg)
            return

        img_xpath = './div[@class="column text-center"]/img/@src'
        img_urls = lot_elem.xpath(img_xpath)
        if len(img_urls) == 0:
            # Don't really support text only descriptions since we
            # match img and description counts below.
            msg = 'No images found in {}'.format(url)
            log.warn(msg)
            return

        text_div_xpath = './div[@class="column text-left"]'
        div_elems = lot_elem.xpath(text_div_xpath)
        if len(img_urls) != len(div_elems):
            fmt = 'Mismatch number of images and lot descriptions for {}'
            log.warn(fmt.format(url))
            return

        text_xpath = './/p/text()'
        lot_texts = [x.xpath(text_xpath) for x in div_elems]

        for img_url, texts in zip(img_urls, lot_texts):
            texts = [util.wsclean(x) for x in texts]
            texts = [x for x in texts if x != '']

            lot_id = util.listfindremove(texts, 'lot id: #') or ''
            lot_id = lot_id[9:]

            price = util.listfindremove(texts, 'sold: $') or ''
            try:
                price = float(price[7:].replace(',', ''))
            except ValueError:
                if price != '':
                    fmt = 'Could not parse price: {} from url {}'
                    log.warn(fmt.format(price, url))
                price = 0.

            desc = ' '.join(texts)

            img_url = urlparse.urljoin(url, img_url)
            img_url = extract_base.urlpath_join(img_url, None)

            lot_rdo = self.db.rdo_ctors['lot'](house_id=self.id,
                    auction_id=auction_rdo['id'], vendor_id=lot_id,
                    desc=desc, price=price, img=img_url, url=url)
            lot_list.append(lot_rdo)

    def extract_lots(self, auction_rdo):
        """Extract lots from Local Liquidators local test site by auction RowDO
        object."""
        lot_list = []

        root_url = auction_rdo['url']
        lot_page = self.dl(root_url)
        if lot_page is None:
            msg = 'Could not download lot page at {}'.format(root_url)
            log.error(msg)
            return lot_list
        lot_html = html.fromstring(lot_page)

        url_xpath = ('/html/body/div[@class="content"]/'
                'div[@class="column text-center"]/p/a[@id="ayty"]/@href')
        lot_urls = lot_html.xpath(url_xpath)
        if len(lot_urls) == 0:
            log.warn('Can not extract secondary pages for url: {}'.format(
                    root_url))
            # Can still process lots on this page so don't return.

        self._extract_lot_rdos(auction_rdo, lot_list, root_url, lot_html)

        # Already extracted first page.
        for url in lot_urls[1:]:
            url = urlparse.urljoin(root_url, url)
            lot_page = self.dl(url)
            if lot_page is None:
                msg = 'Could not download lot page at {}'.format(url)
                log.warn(msg)
                continue
            lot_html = html.fromstring(lot_page)
            self._extract_lot_rdos(auction_rdo, lot_list, url, lot_html)

        return lot_list


class ExtractAuctionTestUSAAuctions(ExtractAuctionBase):
    """Test extractor for USA Auctions local test site."""

    def __init__(self, db, dl_dir, req_throttle=None, req_stall=(None, None)):
        """Initializer for USA Auctions local test site extractor base class.

        Args:
            db: DBDriver object.
            dl_dir: string path to existing directory to download to file to.
            req_throttle (optional): True to enable request throttling.  If not
                set req_throttle will be based on preferences.
            req_stall (optional): tuple of (throttle base, throttle var)
                floats.  If left unset these values will be based on
                preferences.
        """
        super(ExtractAuctionTestUSAAuctions, self).__init__(db, dl_dir,
                req_throttle, req_stall)

    @property
    def name(self):
        return 'USA Auctions'

    @property
    def url(self):
        return 'http://localhost:8080/html/usa_auctions/index.html'

    def extract_auctions(self):
        """Extract auction master list from USA Auctions local test site."""
        auction_list = []

        listing_page = self.dl(self.url)
        if listing_page is None:
            log.error('Could not download {} main page.'.format(self.name))
            return auction_list
        listing_html = html.fromstring(listing_page)

        table_xpath = ('/html/body/div[@class="main-body"]/table/tr/td/'
                'table/tr/td[@valign="top"]//table/tr/'
                'td[@class="page-body-text"]/table')
        auction_table = util.getindex(listing_html.xpath(table_xpath), 0, None)
        if auction_table is None:
            log.warn('Could not find auction table')
            return auction_list

        urls = auction_table.xpath('.//a[@class="link"]/@href')
        texts = auction_table.xpath('.//a[@class="link"]/text()')
        texts = [util.wsclean(x) for x in texts]
        if len(urls) != len(texts):
            fmt = 'Mismatch url and auction descriptions in {} main page'
            log.error(fmt.format(self.name))
            return auction_list

        for url, text in zip(urls, texts):
            text = text.split(' - ')
            if len(text) == 2:
                vendor_id, title = text
            else:
                title = text[0]
                vendor_id = url.split('/')[0]

            url = urlparse.urljoin(self.url, url)

            # Peek at auction page to get start/end times.
            auction_page = self.dl(url)
            if auction_page is None:
                fmt = 'Could not download auction page for tr element {}'
                log.error(fmt.format(index))
                continue
            auction_html = html.fromstring(auction_page)

            title_text_xpath = ('/html/body/div[@class="main-body"]/table/'
                    'tr/td/table/tr/td[@valign="top"]/table/tr/'
                    'td[@class="page-title-text"]')
            title_td_elem = auction_html.xpath(title_text_xpath)
            title_td_elem = util.getindex(title_td_elem, 0, None)
            if title_td_elem is None:
                log.warn('Can not find title element in {}'.format(url))
                start = ''
                end = ''
            else:
                sub_hdr_xpath = './h3[@class="page-sub-hdr"]/text()'
                sub_hdrs = title_td_elem.xpath(sub_hdr_xpath)
                sub_hdrs = [util.wsclean(x.lower()) for x in sub_hdrs]
                start = [x for x in sub_hdrs if x.find('opened: ') != -1]
                end = [x for x in sub_hdrs if x.find('closed: ') != -1]
                start = util.getindex(start, 0, '')[8:]
                end = util.getindex(end, 0, '')[8:]

            if start == '':
                log.warn('Could not find start time for {}'.format(url))
            if end == '':
                log.warn('Could not find end time for {}'.format(url))

            auction_rdo = self.db.rdo_ctors['auction'](house_id=self.id,
                    vendor_id=vendor_id, name=title, location='USA',
                    start_date=start, end_date=end, closed=1,
                    url=url, status='new')
            auction_list.append(auction_rdo)

        return auction_list

    def _extract_lot_page(self, url):
        """Extract img, price, location from test USA Auctions lot page."""
        # img, price, location
        ret = [None, None, None]

        lot_page = self.dl(url)
        if lot_page is None:
            msg = 'Could not download lot page at {}'.format(url)
            log.error(msg)
            return ret
        lot_html = html.fromstring(lot_page)

        container_xpath = ('/html/body/div[@class="main-body"]/'
                'div[@class="auction-info"]/div[@class="lot-container"]')
        lot_container = lot_html.xpath(container_xpath)
        lot_container = util.getindex(lot_container, 0, None)
        if lot_container is None:
            msg = 'Could not find lot container in page {}'.format(url)
            lot.error(msg)
            return ret

        img_xpath = './div[@id="auction-photos"]/table/tr/td/img/@src'
        img_url = lot_container.xpath(img_xpath)
        img_url = util.getindex(img_url, 0, None)
        if img_url is not None:
            img_url = urlparse.urljoin(url, img_url)
            img_url = extract_base.urlpath_join(img_url, None)
            ret[0] = img_url

        details_xpath = './div[@class="auction-details"]/table/tr/td/h4/text()'
        details_text = lot_container.xpath(details_xpath)
        details_text = [util.wsclean(x) for x in details_text]

        price = util.listfindremove(details_text, 'closing bid: $') or ''
        try:
            price = float(price[14:].replace(',', ''))
        except ValueError:
            if price != '':
                fmt = 'Could not parse price: {} from url {}'
                log.warn(fmt.format(price, url))
            price = 0.
        ret[1] = price

        location = util.listfindremove(details_text, 'location zip: ') or ''
        location = location[14:]
        ret[2] = location

        return ret

    def extract_lots(self, auction_rdo):
        """Extract lots from USA Auctions local test site by auction RowDO
        object."""
        lot_list = []

        root_url = auction_rdo['url']
        auction_page = self.dl(root_url)
        if auction_page is None:
            msg = 'Could not download auction page at {}'.format(root_url)
            log.error(msg)
            return lot_list
        auction_html = html.fromstring(auction_page)

        body_text_xpath = ('/html/body/div[@class="main-body"]/table/'
                'tr/td/table/tr/td[@valign="top"]/table/tr/'
                'td[@class="page-body-text"]')
        body_td_elem = auction_html.xpath(body_text_xpath)
        body_td_elem = util.getindex(body_td_elem, 0, None)
        if body_td_elem is None:
            log.error('Can not find body element in {}'.format(root_url))
            return lot_list

        a_elems = body_td_elem.xpath('./table/tr/td//a')
        if len(a_elems) == 0:
            log.error('Can not find lot links in {}'.format(root_url))
            return lot_list

        lot_links = [(x.attrib.get('href', None), util.wsclean(x.text)) for
                x in a_elems]

        for url, text in lot_links:
            text = text.split(' - ')
            if len(text) == 2:
                lot_id, desc = text
            else:
                desc = text[0]
                lot_id = url.split('/')[0]

            url = urlparse.urljoin(root_url, url)

            img_url, price, location = self._extract_lot_page(url)

            # Must have errored out early already with a log message, just
            # continue.
            if img_url is None:
                continue

            lot_rdo = self.db.rdo_ctors['lot'](house_id=self.id,
                    auction_id=auction_rdo['id'], vendor_id=lot_id,
                    desc=desc, price=price, img=img_url, url=url)
            lot_list.append(lot_rdo)

        return lot_list
