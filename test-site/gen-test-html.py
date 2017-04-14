#!/usr/bin/env python

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

import csv
import datetime
import errno
import math
import os
import random
import re


LISTING_PATH = './listing.csv'
HTML_ROOT = './html'


def makedirs(path, mode=0777):
    try:
        os.makedirs(path, mode)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def dedent(s, count):
    pattern = r'^\s{{0,{}}}'.format(count)
    s = s.split('\n')
    s = [re.sub(pattern, '', x) for x in s]
    s = '\n'.join(s)
    return s


def indent(s, count):
    s = s.split('\n')
    s = [' ' * count + x for x in s]
    s = '\n'.join(s)
    return s


def ran_list_non_repeating(count, a, b):
    if b - a + 1 < count:
        raise ValueError('Impossible list count')

    ret = []
    while len(ret) != count:
        ran = random.randint(a, b)
        if ran not in ret:
            ret.append(ran)

    return ret


def ran_split(lst, count):
    lst = lst[:]
    random.shuffle(lst)
    size = len(lst)
    base = 100. / (count * 1.3)
    var = (100 - (base * count)) / count

    ret = []
    for x in range(count - 1):
        ran = random.randint(int(base), int(base + var))
        ran = int(ran / 100. * size)
        ret.append(lst[:ran])
        lst = lst[ran:]

    ret.append(lst)
    random.shuffle(ret)

    return ret


def read_listing(path):
    listing_file = open(path, 'r')
    listing = csv.reader(listing_file, delimiter=',', quotechar='"')
    listing = list(listing)
    return listing


def usa_gen_link_table(title, heading_list, link_list):
    # link_list is list of href, link text tuples.
    ret = ''

    s = """\
            <!DOCTYPE html>
            <html>
                <head>
                    <title>{title}</title>
                </head>
                <body>
                    <div class="main-body">
                        <table width="100%" border="0" cellpadding="0" cellspacing="0">
                            <tr>
                                <td>
                                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                        <tr>
                                            <td valign="top">
                                                <table border=0 cellspacing=0 cellpadding=0 width="100%" align="center">
                                                    <tr class="bright">
                                                        <td class="page-title-text">\n"""
    s = s.format(title=title)
    s = dedent(s, 12)
    ret += s

    if len(heading_list):
        s = '<h2 class="page-hdr">{}</h2>\n'.format(heading_list[0])
        for heading in heading_list[1:]:
            s += '<h3 class="page-sub-hdr">{}</h3>\n'.format(heading)
        s = indent(s[:-1], 48)
        ret += s + '\n'

    s = """\
                </td>
            </tr>
        </table>

        <table border=0 cellspacing=0 cellpadding=0 width="100%" align="center">
            <tr>
                <td class="page-body-text" border="0" cellpadding="0" cellspacing="0">
                    <table cellpadding="0" cellspacing="0" border="0">
                        <tr>"""
    s = indent(s, 28)
    ret += s + '\n'

    # Split list
    # Divide link_list in two, first half will be great if odd length.
    link_list = [link_list[:int(math.ceil(len(link_list) / 2.))],
            link_list[(len(link_list) + 1) / 2:]]
    fmt = '    <a class="link" href="{href}">{text}</a><br>\n'
    for links in link_list:  # column
        s = '<td align="left" nowrap valign="top" style="border: solid 2px ' \
                '#403F3B; padding: 5px 5px 5px 5px;">\n'

        for href, text in links:
            s += fmt.format(href=href, text=text)

        s += '</td>'
        s = indent(s, 56)
        ret += s + '\n'


    s = """\
                                                                </tr>
                                                            </table>
                                                        </td>
                                                    </tr>
                                                </table>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                        </table>
                    </div>
                </body>
            </html>"""
    s = dedent(s, 12)
    ret += s

    return ret


def usa_gen_lot(root, listing):
    lot_id, img, desc, price = listing
    zipcode = '{:05d}'.format(random.randint(0, 99999))
    html = """\
            <!DOCTYPE html>
            <html>
                <head>
                    <title>USA Auctions - Lot {lot_id} - {desc}</title>
                </head>
                <body>
                    <div class="main-body">
                        <div class="auction-info">
                            <div class="lot-container" id="auction-photos-video">
                                <div id="auction-photos">
                                    <table cellpadding="0" cellspacing="0" border="0">
                                        <tr>
                                            <td align="center" valign="middle">
                                                <img class="large-thumbnail" src="/img/{img}"/>
                                            </td>
                                        </tr>
                                    </table>
                                </div>
                                <div class="auction-details">
                                    <h1 id="details-lot-title">{desc}</h1>
                                    <table cellspacing="0" cellpadding="0" border="0">
                                        <tr>
                                            <td>
                                                <h4>Lot {lot_id}</h4>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td>
                                                <h4>Closing Bid: {price}</h4>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td>
                                                <h4>Location zip: {zipcode}</h4>
                                            </td>
                                        </tr>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </body>
            </html>"""
    html = html.format(lot_id=lot_id, img=img, desc=desc, price=price,
            zipcode=zipcode)
    html = dedent(html, 12)

    lot_file = open(os.path.join(root, '{}.html'.format(lot_id)), 'w')
    lot_file.write(html)
    lot_file.close()


def usa_gen_au(root, listing, au_id, time_base):
    time_base += datetime.timedelta(days=random.randint(7, 14),
            seconds=random.randint(0, 3600 * 24))
    times = [time_base,]
    time_base += datetime.timedelta(days=random.randint(7, 14),
            seconds=random.randint(0, 3600 * 24))
    times.append(time_base)
    times  = [x.strftime('%Y-%m-%d %H:%M:%S') for x in times]

    lot_ids = ran_list_non_repeating(len(listing), 0, 999999)
    lot_ids = ['{:06d}'.format(x) for x in lot_ids]
    listing = zip(lot_ids, *zip(*listing))

    lot_link_href = ['{}.html'.format(x[0]) for x in listing]
    lot_link_text = ['{} - {}'.format(x[0], x[2]) for
            x in listing]
    lot_links = zip(lot_link_href, lot_link_text)
    title = 'USA Auctions - Past Bid Results - Auction {}'.format(au_id)
    heading_list = ['USA Auctions', 'Auction {}'.format(au_id),
            'Opened: {}'.format(times[0]), 'Closed: {}'.format(times[1]),
            'Past Bid Results']

    au_html = usa_gen_link_table(title, heading_list, lot_links)
    au_file = open(os.path.join(root, 'index.html'), 'w')
    au_file.write(au_html)
    au_file.close()

    for lot in listing:
        usa_gen_lot(root, lot)

    return time_base


def usa_gen_auctions(root, listing, au_count=4):
    # Not perfect as changes in the code may result in completely different
    # data and git diff.
    random.seed('usa_auctions')
    au_listings = ran_split(listing, au_count)
    au_ids = ['{:05d}'.format(random.randint(0, 99999)) for x in
            range(au_count)]

    auction_links = [('{}/index.html'.format(x),
            '{} - USA Auction {}'.format(x, x)) for x in au_ids]
    title = 'USA Auctions - Past Bid Results'
    heading_list = ['USA Auctions', 'Past Event Bid Results']

    main_html = usa_gen_link_table(title, heading_list, auction_links)
    makedirs(root)
    main_file = open(os.path.join(root, 'index.html'), 'w')
    main_file.write(main_html)
    main_file.close()

    time_base = datetime.datetime(year=2016, month=4, day=5, hour=12)

    for au_id, au_list in zip(au_ids, au_listings):
        au_root = os.path.join(root, au_id)
        makedirs(au_root)
        time_base = usa_gen_au(au_root, au_list, au_id, time_base)


def ll_gen_main(root, au_ids):
    path = os.path.join(root, 'index.html')
    html = open(path, 'w')

    s = """\
            <!DOCTYPE html>
            <html>
                <head>
                    <title>Local Liquidators - Past Auctions</title>
                </head>

                <div class="content">
                    <div class="column text-center">
                        <h1>Local Liquidators</h1>
                        <h2>Past auctions</h2>

                        <table cellpadding="0" cellspacing="0" border="0">"""
    s = dedent(s, 12)
    html.write(s)
    html.write('\n')

    fmt = """\
                <tr>
                    <td style="padding: 10px 10px 10px 10px">
                        <p><a ID=ayty href="{au_id}/1.html">Sample auction {au_id}</a></p>
                    </td>
                    <td>
                        <p>Auction held in: {zipcode}</p>
                    </td>
                </tr>\n"""
    for au_id in au_ids:
        zipcode = '{:05d}'.format(random.randint(45500, 45599))
        s = fmt.format(au_id=au_id, zipcode=zipcode)
        html.write(s)

    s = """\
                        </table>
                    </div>
                </div>
            </html>"""
    s = dedent(s, 12)
    html.write(s)
    html.write('\n')

    html.close()


def ll_gen_page(root, listing, au_id, page, page_count, times):
    times = [x.strftime('%Y-%m-%d %H:%M:%S') for x in times]

    path = os.path.join(root, '{}.html'.format(page))
    html = open(path, 'w')

    s = """\
            <!DOCTYPE html>
            <html>
                <head>
                    <title>Local Liquidators - Sample auction {au_id} - page {page}</title>
                </head>

                <div class="content">
                    <div class="column text-center">
                        <h1>Local Liquidators</h1>
                        <h2>Sample auction {au_id}</h2>

                        <p class="general">Opens: {opens}</p>
                        <p class="general">Closes: {closes}</p>

                        <p>""".format(au_id=au_id, page=page, opens=times[0],
                                closes=times[1])
    s = dedent(s, 12)
    html.write(s)
    html.write('\n')

    pages = [[x, x] for x in range(1, page_count + 1)]
    pages[page - 1][1] = '<font color=red>{}</font>'.format(page)
    pages = ['{}<a ID=ayty href="{}.html">{}</a>'.format(' ' * 16, x[0], x[1])
            for x in pages]
    html.write('\n'.join(pages))
    html.write('\n')

    s = """\
            </p>

            <div class="view-past-lots">"""
    html.write(s)
    html.write('\n')

    for img, desc, price in listing:
        s = """\
                <div class="column text-center">
                    <img src="/img/{img}" border="0" width="200">
                </div>
                <div class="column text-left">
                    <p class="general">Lot ID: #{lot:06d}</p>
                    <p class="general">{desc}</p>
                    <p class="general"></p>
                    <p class="general"></p>
                    <p class="general">
                        SOLD:
                        {price}
                    </p>
                </div>
                """.format(img=img, lot=random.randint(0, 999999), desc=desc,
                        price=price)
        html.write(s)
        html.write('\n')

    s = """\
                        </div>
                    </div>
                </div>
            </html>"""
    s = dedent(s, 12)
    html.write(s)
    html.write('\n')

    html.close()


def ll_gen_au(root, listing, au_id, time_base, lot_per_page=5):
    page_count = int(math.ceil(len(listing) / float(lot_per_page)))

    time_base += datetime.timedelta(days=random.randint(7, 14),
            seconds=random.randint(0, 3600 * 24))
    times = [time_base,]
    time_base += datetime.timedelta(days=random.randint(7, 14),
            seconds=random.randint(0, 3600 * 24))
    times.append(time_base)

    for index in range(page_count):
        start = index * lot_per_page
        ll_gen_page(root, listing[start:start + lot_per_page], au_id,
                index + 1, page_count, times)

    return time_base


def ll_gen_auctions(root, listing, au_count=3):
    # Not perfect as changes in the code may result in completely different
    # data and git diff.
    random.seed('ll_auctions')
    au_listings = ran_split(listing, au_count)
    au_ids = ['{:03d}'.format(random.randint(0, 999)) for x in
            range(au_count)]

    makedirs(root)
    ll_gen_main(root, au_ids)
    time_base = datetime.datetime(year=2016, month=6, day=5, hour=12)

    for au_id, au_list in zip(au_ids, au_listings):
        au_root = os.path.join(root, au_id)
        makedirs(au_root)
        time_base = ll_gen_au(au_root, au_list, au_id, time_base)


def main():
    listing = read_listing(LISTING_PATH)
    ll_gen_auctions(os.path.join(HTML_ROOT, 'll_auctions'), listing)
    usa_gen_auctions(os.path.join(HTML_ROOT, 'usa_auctions'), listing)
    print('Done')


if __name__ == '__main__':
    main()
