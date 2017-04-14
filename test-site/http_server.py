#!/usr/bin/env python

import BaseHTTPServer
import SimpleHTTPServer
import sys


if len(sys.argv) > 1:
    port = int(sys.argv[1])
else:
    port = 8080

server_address = ('127.0.0.1', port)

httpd = BaseHTTPServer.HTTPServer(server_address,
        SimpleHTTPServer.SimpleHTTPRequestHandler)

print('Serving HTTP on {} port {} ...'.format(*server_address))

httpd.serve_forever()
