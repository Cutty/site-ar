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
import logging
import os
import random
import time

try:
    from urllib.request import urlopen
except:
    from urllib2 import urlopen


from . import prefs
from . import util
from .exceptions import *


log = logging.getLogger(__name__)


prefs.add('extract.save.defer', bool, True, default=True,
        help='True to wait until images are needed to download.  False to '
        'download immediately')
prefs.add('extract.req_throttle', bool, True, default=False,
        help='True to enable request throttling')
prefs.add('extract.req_throttle.base', float, True, default=0.5,
        help='Base value in seconds to wait between throttled requests')
prefs.add('extract.req_throttle.var', float, True, default=0.2,
        help='Random max value in seconds req_throttle.base')


# URLPATH Format: [<__url__><url>] [<__path__><path>]
# Since a url can not have a space but a path can path must always follow the
# url if present so the first encountered space is the delimeter between the
# two.
def urlpath_join(url, path):
    """Join file url and path to save in database.  Since a url can not have
    a space the two strings are tagged and joined by a space in the format:
    [<__url__><url>] [<__path__><path>].

    Args:
        url: None or url string (may not contain spaces).
        path: None or path string.

    Returns:
        urlpath string or None.
    """
    if not util.isnonestr(url):
        raise TypeError('url must be type None or basestring')
    if not util.isnonestr(path):
        raise TypeError('path must be type None or basestring')

    ret = []

    url = url or ''
    if len(url):
        if url.find(' ') != -1:
            raise ValueError('url \'{}\' can not have spaces'.format(url))
        ret.append('__url__' + url)

    path = path or ''
    if len(path):
        ret.append('__path__' + path)

    if len(ret) == 0:
        return None
    return ' '.join(ret)


def urlpath_split(urlpath):
    """Splits properly formatted urlpath into url and path.

    Args:
        urlpath: urlpath string

    Returns:
        tuple (url, path) where url and path may be string or None.
    """
    if not util.isnonestr(urlpath):
        raise TypeError('urlpath must be type None or basestring')

    if urlpath is None or len(urlpath) == 0:
        return None, None

    if urlpath.startswith('__url__'):
        # Keep urlpath if needed for exception below.
        url = urlpath.split(' ', 1)
        path = util.getindex(url, 1, None)
        url = url[0][7:]
        if url.find('__path__') != -1:
            log.warn('url: \'{}\' contains __path__, may be a bug'.format(
                    url))
    else:
        url = None
        path = urlpath

    #if path is not None and path.startswith('__path__'):
    if isinstance(path, basestring):
        if path.startswith('__path__'):
            path = path[8:]
            if path.find('__url__') != -1:
                log.warn('path: \'{}\' contains __url__, may be a bug'.format(
                        path))
        else:
            # Either __url__ and/or __path__ tests above failed.
            raise ValueError('invalid urlpath: \'{}\''.format(urlpath))

    return url, path


class ExtractBase(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, db, dl_dir, req_throttle=None, req_stall=(None, None)):
        """Initializer for extractor base class.  Can not be used on its own.

        Args:
            db: DBDriver object.
            dl_dir: string path to existing directory to download to file to.
            req_throttle (optional): True to enable request throttling.  If not
                set req_throttle will be based on preferences.
            req_stall (optional): tuple of (throttle base, throttle var)
                floats.  If left unset these values will be based on
                preferences.
        """
        util.require_dir(dl_dir)

        self.db = db
        self.dl_dir = dl_dir

        if req_throttle is None:
            self.req_throttle = prefs['extract.req_throttle']
        else:
            self.req_throttle = req_throttle

        log.debug('req_throttle: {}'.format(self.req_throttle))

        self.req_stall_base = req_stall[0] \
                or prefs['extract.req_throttle.base']
        self.req_stall_var = req_stall[1] or prefs['extract.req_throttle.var']
        self.req_last = 0

        self.db_ready = False
        self.id = None

    def request(self, url):
        """Opens a request but does not download a url.

        Args:
            url: string (must include http://)

        Returns:
            request object or None.
        """
        if self.req_throttle:
            req_next = self.req_last + self.req_stall_base
            req_next += (random.random() * 2 * self.req_stall_var) \
                    - self.req_stall_var
            now = time.time()
            if req_next > now:
                time.sleep(req_next - now)

            # Mark req_last to prevent spamming requests (will happen again
            # in _dl so the delay actually happens after the last activity).
            self.req_last = time.time()

        # TODO: handle connection refused.
        #urllib2.URLError, need to figure out what python3 would be.
        req = urlopen(url)

        return req

    def _req_ext(self, req):
        """Extract file extension from request object.

        Args:
            req: request object.

        Returns:
            string of extension without leading '.'
        """
        # 1) Try to use the url.
        _, ext = os.path.splitext(req.url)
        if ext != '':
            return ext[1:]

        # 2) Check content-disposition, used by server to suggest default
        #    filename.
        if req.info().has_key('content-disposition'):
            filename = req.info()['content-disposition']
            filename = filename.split('filename=')
            filename = filename.replace('"', '')
            filename = filename.replace(';', '')
            _, ext = os.path.splitext(req.url)
            if ext != '':
                return ext[1:]

        # 3) Fall back to content-type.  This is less than ideal since we may
        #    end up with 'octect-stream' as an extension.  It should be fine
        #    if we continue to just deal with images.
        if req.headers.subtype and req.headers.subtype != '':
            return req.headers.subtype

        # Another alternative would be passing the data through magic or
        # binwalk.

        log.warn('unknown extension for url: {}'.format(req.url))
        return 'unk'

    def _dl(self, req):
        """Download data from request object.

        Args:
            req: request object.

        Returns:
            data in string format.
        """
        if req.code != 200:
            return None

        data = req.read()

        # If throttling mark last download time after read is done.
        if self.req_throttle:
            self.req_last = time.time()

        return data

    def dl(self, url):
        """Request and download url.

        Args:
            url: string (must include http://)

        Returns:
            data in string format.
        """
        return self._dl(self.request(url))

    def _open_dl_file(self, path, mode='r'):
        """Open a file from the download directory.

        Args:
            path: path string relative to the download directory.
            mode (optional): open mode string, default is 'r'.
        Returns:
            file pointer or None.
        """
        return util.tryopen(os.path.join(self.dl_dir, path), mode)

    def _dl_file(self, url, ext=None):
        """Download and save file to download directory.

        Args:
            url: string (must include http://)
            ext (optional): string extension.  If not set the extension will
                try to be determined by _req_ext.

        Returns:
            string path to file based on md5 of data relative to download
            directory or None.
        """
        req = self.request(url)
        if req is None:
            return None

        if ext is None:
            ext = self._req_ext(req)

        # Note: if this is going to download very large files it would be best
        # to read chunks from the request while at the same time feeding it
        # through md5 and writing to a temporary file which can be moved
        # to the correct path later.
        data = self._dl(req)

        path = util.md5_path(data, self.dl_dir, ext)
        if path is None:
            # If we run out of paths we probably downloaded the file (or
            # empty files) too many times.
            err = 'Could not find unused path for {}'.format(req.url)
            raise ExtractSaveError(err)

        wfile = self._open_dl_file(path, 'w')
        if wfile is None:
            log.warn('could not open {} for write'.format(path))
            return None

        wfile.write(data)
        wfile.close()

        return path

    # TODO: trackdown calls to dl_save and make sure file is closed.
    def dl_save(self, url, ext=None, now=None):
        """Defer or download and save file to download directory.

        Args:
            url: string (must include http://)
            ext (optional): string extension.  If not set the extension will
                try to be determined by _req_ext.
            now (optional): True to download now.  If not set now will be
                set based on preferences.

        Returns:
            tuple of (urlpath, file or None).  urlpath is string created
            by urlpath_join.  If file was downloaded it will be opened for
            read at position 0.  None if an error occurred.
        """
        # download and save file:
        # now == None (now = pref)
        # now == True download now
        # now == False do nothing, return url
        # return urlpath, file or None (failed or did not download)
        if now is None:
            now = not prefs['extract.save.defer']

        if now is True:
            path = self._dl_file(url, ext)
        else:
            path = None

        if path is not None:
            dlfile = self._open_dl_file(path)
        else:
            dlfile = None

        # TODO: need to handle bad urls probably around here.
        urlpath = urlpath_join(url, path)
        return urlpath, dlfile

    def get_file(self, urlpath):
        """Get file in urlpath.  If path part of urlpath is unset it will be
        downloaded immediately.

        Args:
            urlpath: urlpath string

        Returns:
            tuple of (urlpath, file or None).  urlpath is string created
            by urlpath_join and may be different than the argument urlpath if
            the file was downloaded.  If file was downloaded it will be opened
            for read at position 0.  None if an error occurred.
        """
        # will downlaod always, return path, file
        # return urlpath, file or None (failed)
        url, path = urlpath_split(urlpath)

        if url is None and path is None:
            raise ValueError('url and path are None')

        if path is not None:
            dlfile = self._open_dl_file(path, 'r')
            if dlfile is None:
                err = 'could not open: \'{}\', trying to download again'
                log.warn(err.format(path))
                path = None

        if path is None:
            urlpath, dlfile = self.dl_save(url, ext=None, now=True)

        return urlpath, dlfile

    @abc.abstractmethod
    def dbinit(self):
        self.db_ready = True

    @abc.abstractmethod
    def update_all(self):
        pass
