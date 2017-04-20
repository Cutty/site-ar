# site-ar
A Python based time-series site scraper with a text UI.  Scraped data is stored
in a SQLite database and skipped over in subsequent scans.  Data can be browsed
in a tree view, searched and exported with images (if available) to a XLSX
file.  The application core provides a simple db interface to handle schema
creation, migrations and an ORM.  It also contains a key/value preference
system and several urwid based widgets.  site-ar can be customized into
different *site types* that define the schema, scrapers, views and how data is
mapped on export.

## Motivation
Many smaller online auction sites publish past bid results but do not provide a
way to search them.  A combination of robots.txt and the way pages link back to
each other renders searching with *site:exampleauction.com* on Google unusable.
This program allows for evaluation of market prices and frequency of select
items sold at these auctions.  These auction sites are typically local pickup
only and the size/weight of items make shipping impracticable, skewing results
when compared to a nationwide auction site like eBay.  While the auction *site
type* is provided it only includes test scrapers since this is not a TOS
friendly program.  Writing custom scrapers using lxml is trivial though.

## Installation
* This was tested on a clean and updated Ubuntu 16.04.2 install.
```
sudo apt-get install python-pip python-pil python-lxml python-urwid
sudo pip install openpyxl
git clone https://github.com/Cutty/site-ar.git
```

Only openpyxl was installed from pip because the version in Ubuntu's apt
repositories is too old.  Exported files were only tested using LibreOffice
Calc.  For people who prefer pip over apt for their Python packages the
versions tested are listed below:
```
Python: 2.7.12
LibreOffice: 5.1.6.2
lxml: 3.5.0
PIL: 3.1.2
openpyxl: 2.3.5, 2.4.0, 2.4.5, 2.4.6
urwid: 1.3.1
```

## Usage
* In terminal 1 start the local test-site HTTP server:
```
cd site-ar/test-site/
./http_server.py
```

* In terminal 2 (you may want to resize the terminal to ~60/140 rows/cols):
```
cd site-ar/
./site-ar.py
```
Once in the application press `Shift-U` to update all auctions at once.
Navigate using the `Left,Down,Up,Right` or `H,J,K,L` keys and `space` for a
detailed view.  Common keys are listed in the footer and the help dialog can be
brought up using `?`.  Once the db schema has been created the raw ORM objects
can be browsed by using the `--site-type generic` command line switch.

## Screenshots

|       |       |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_01_lg.jpg" target="_blank"><img src="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_01.jpg" alt="screenshot 01" width="400" height="330" border="10"/></a> | <a href="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_02_lg.jpg" target="_blank"><img src="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_02.jpg" alt="screenshot 02" width="400" height="330" border="10"/></a> |
| <a href="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_03_lg.jpg" target="_blank"><img src="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_03.jpg" alt="screenshot 03" width="400" height="330" border="10"/></a> | <a href="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_04_lg.jpg" target="_blank"><img src="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_04.jpg" alt="screenshot 04" width="400" height="330" border="10"/></a> |
| <a href="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_05_lg.jpg" target="_blank"><img src="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_05.jpg" alt="screenshot 05" width="400" height="330" border="10"/></a> | <a href="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_06_lg.jpg" target="_blank"><img src="https://raw.githubusercontent.com/Cutty/site-ar/gh-res/img/screenshot_06.jpg" alt="screenshot 06" width="400" height="330" border="10"/></a> |

## Troubleshooting
* If the program crashes during export or the XLSX file contains broken images
try disabling jpeg conversion; `ctrl-p` to open preferences and set
`export.xlsx.img.jpeg.enable` to `False`.  Most versions of openpyxl will
always convert images to png.  For space savings site-ar will monkey patch
openpyxl and PIL to force converting/referencing images as a jpeg.  This may
not work on all versions of openpyxl.

* Debugging must be done using [pudb](https://documen.tician.de/pudb) available
in apt and pip.  pudb uses the same UI library (urwid) as site-ar and will
switch seamlessly between the inferior and debugger.

## License
See [LICENSE](LICENSE).

All images in [test-site/img](test-site/img) were retrieved from
http://www.publicdomainpictures.net and believed to be in the public domain.
