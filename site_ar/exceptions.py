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

class Error(Exception):
    pass

class DBError(Error):
    pass

class DBColumnError(DBError):
    pass

class DBDriverError(DBError):
    pass

class ExportError(Error):
    pass

class ExtractError(Error):
    pass

class ExtractSaveError(ExtractError):
    pass

class MigrationError(Error):
    pass

class PreferencesError(Error):
    pass

class PreferencesKeyError(PreferencesError):
    pass

class PreferencesTypeError(PreferencesError):
    pass

class RequestError(Error):
    pass

class RowDOError(Error):
    pass

class UIError(Error):
    pass

class ValidatedEditError(Error):
    def __init__(self, text, orig_exc):
        msg = 'invalid text: \'{}\''.format(text)
        super(ValidatedEditError, self).__init__(msg)
        self.text = text
        self.orig_exc = orig_exc
