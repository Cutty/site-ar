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

from ..dbdrv import Migration
from ..preferences import add_prefs_schema_up, add_prefs_schema_down


class AuctionMig_0001(Migration):
    version = 1

    def up(self, db):
        add_prefs_schema_up(db)

        db.add_table(
                'auction_house',
                db.col('id', 'INTEGER', primary_key=True, unique=True,
                        protected=True),
                db.col('name', 'TEXT'),
                db.col('url', 'TEXT'))

        db.add_table(
                'auction',
                db.col('id', 'INTEGER', primary_key=True, unique=True,
                        protected=True),
                db.col('house_id', 'INTEGER'),
                db.col('vendor_id', 'TEXT'),
                db.col('name', 'TEXT'),
                db.col('location', 'TEXT'),
                db.col('start_date', 'DATE'),
                db.col('end_date', 'DATE'),
                db.col('closed', 'INTEGER'),
                db.col('url', 'TEXT'),
                db.col('status', 'TEXT'),
                db.col('house_id', None, foreign_key='auction_house(id)'))

        db.add_table(
                'lot',
                db.col('id', 'INTEGER', primary_key=True, unique=True,
                        protected=True),
                db.col('house_id', 'INTEGER'),
                db.col('auction_id', 'INTEGER'),
                db.col('vendor_id', 'TEXT'),
                db.col('desc', 'TEXT'),
                db.col('price', 'REAL'),
                db.col('img', 'TEXT'),
                db.col('url', 'TEXT'),
                db.col('house_id', None, foreign_key='auction_house(id)'),
                db.col('auction_id', None, foreign_key='auction(id)'))

    def down(self, db):
        db.del_table('lot')
        db.del_table('auction')
        db.del_table('auction_house')
        add_prefs_schema_down(db)


class AuctionMig_0002(Migration):
    version = 2

    def up(self, db):
        db.add_table(
                'auction_location',
                db.col('id', 'INTEGER', primary_key=True, unique=True,
                        protected=True),
                db.col('name', 'TEXT'),
                db.col('lat', 'REAL', default=0.0),
                db.col('lon', 'REAL', default=0.0))

    def down(self, db):
        db.del_table('auction_location')


def get_schema():
    return [
        AuctionMig_0001(),
        AuctionMig_0002()
    ]
