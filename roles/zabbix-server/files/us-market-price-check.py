#!/usr/bin/python
#coding: UTF-8
###############################################################################
# @(#) US Market Price Checker
#
# Get a price from stocks.finance.yahoo.com
#
#
# MIT License
#
# Copyright (c) 2016 Tats Shibata
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
###############################################################################
# {{{ const

__version__ = "1.5.0"

BASE_URL = "http://finance.yahoo.com/quote/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.98 Safari/537.36"

#}}}
# {{{ import

import getopt
import re
import sys
import urllib
import urllib2

# }}}
# {{{ usage()

def usage():
  print >>sys.stderr, """
[USAGE] market-price-checker [-V] <SYMBOL>

OPTION:
  -V, --version     Output version information and exit

RETURN CODE:
  0                 Success
  1                 Error but you can fix yourself
  2                 Critical Error
 -1                 Unexpected Error. File a bug
"""

# }}}
# {{{ version()

def version():
  print """US Market Price Checker %s
""" % (__version__)

# }}}
# {{{ Option

class Option(object):
  def __init__(self, opts, args):
    self._set_opts(opts)
    self._set_args(args)

  def _set_opts(self, opts):
    for o, a in opts:
      if o in ("-V", "--version"):
        version()
        sys.exit(1)

  def _set_args(self, args):
    try:
      self.symbol = args[0]
    except IndexError:
      print >>sys.stderr, "<ERROR> SYMBOL is required"
      usage()
      sys.exit(1)

# }}}
# {{{ valid_opt()

def valid_opt(argv):
  try:
    opts, args = getopt.gnu_getopt(
      argv[1:],
      "V",
      ["version"]
    )
  except getopt.GetoptError:
    print >>sys.stderr, "<ERROR> Unknown option"
    usage()
    sys.exit(1)

  return Option(opts, args)

# }}}
# {{{ buid_opener()

def buid_opener():
  opener = urllib2.build_opener()
  opener.addheaders = [('User-Agent', USER_AGENT)]

  return opener

# }}}
# {{{ req_product()

def req_product(opener, symbol):
  try:
    res = opener.open(BASE_URL + symbol)
  except urllib2.URLError:
    print >>sys.stderr, "<ERROR> URL request error [URL=%s]" % (BASE_URL + symbol)
    sys.exit(1)

  return res.read()

# }}}
# {{{ get_price()

def get_price(res, symbol):
  pat = re.compile(r'<span class="Fw\(b\) Fz\(36px\) Mb\(-4px\)" data-reactid="264">(.+?)</span>')
  price = "-----"

  for match in pat.finditer(res):
    price = match.group(1)

  return price

# }}}
# {{{ main()

def main():
  opt = valid_opt(sys.argv)

  opener = buid_opener()

  res = req_product(opener, opt.symbol)
  print get_price(res, opt.symbol)

if __name__ == "__main__":
  main()
