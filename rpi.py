#!/usr/bin/env python3
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import asyncio
import tornado.escape
import tornado.ioloop
import tornado.locks
import tornado.web
import os.path
import uuid
import urllib

from tornado.options import define, options, parse_command_line

import requests
import threading
import datetime
from time import sleep

define("port", default=8888, help="run on the given port", type=int)
define("debug", default=True, help="run in debug mode")


class MessageBuffer(object):
    def __init__(self):
        # cond is notified whenever the message cache is updated
        self.cond = tornado.locks.Condition()
        self.message = dict()
    
    def check_for_messages(self, cursor):
        if self.message == dict() or self.message['id'] == cursor:
            result = None
        else:
            result = [self.message]
        return result

    def update_message(self, message):
        self.message = message
        self.cond.notify_all()

global_message_buffer = MessageBuffer()


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("index.html", messages=global_message_buffer.message)


class MessageNewHandler(tornado.web.RequestHandler):
    """Post a new message to the chat room."""

    def post(self):

        #body_str = self.request.body.decode('utf-8')
        #body = urllib.parse.parse_qs(body_str)['body'][0]

        message = {"id": str(uuid.uuid4()), "body": self.get_argument('body')}
        # render_string() returns a byte string, which is not supported
        # in json, so we must convert it to a character string.
        message["html"] = tornado.escape.to_unicode(
            self.render_string("message.html", message=message)
        )
        # print(message)
        if self.get_argument("next", None):
            self.redirect(self.get_argument("next"))
        else:
            self.write(message)
        global_message_buffer.update_message(message)


class MessageUpdatesHandler(tornado.web.RequestHandler):
    """Long-polling request for new messages.

    Waits until new messages are available before returning anything.
    """

    async def post(self):
        cursor = self.get_argument("cursor", None)
        new_message = global_message_buffer.check_for_messages(cursor)
        while not new_message:
            # Save the Future returned here so we can cancel it in
            # on_connection_close.
            self.wait_future = global_message_buffer.cond.wait()
            try:
                await self.wait_future
            except asyncio.CancelledError:
                return
            new_message = global_message_buffer.check_for_messages(cursor)
        if self.request.connection.stream.closed():
            return
        self.write(dict(messages=new_message))

    def on_connection_close(self):
        self.wait_future.cancel()

def dummy_f():
    while True:
        #r = requests.post('http://localhost:8888/a/message/new', {'body': f'{datetime.datetime.now()}'})
        for color in ['yellow','red','green']:
            r = requests.post('http://localhost:8888/a/message/new',{'body': color})
            sleep(1)


def main():
    parse_command_line()
    app = tornado.web.Application(
        [
            (r"/", MainHandler),
            (r"/a/message/new", MessageNewHandler),
            (r"/a/message/updates", MessageUpdatesHandler),
        ],
        cookie_secret="__TODO:_GENERATE_YOUR_OWN_RANDOM_VALUE_HERE__",
        template_path=os.path.join(os.path.dirname(__file__), "templates"),
        static_path=os.path.join(os.path.dirname(__file__), "static"),
        #xsrf_cookies=True, #TODO: SAFETY?
        debug=options.debug,
    )
    app.listen(options.port)

    # dummy thread
    dummy_thread = threading.Thread(target=dummy_f, args=[])  # <- 1 element list
    #dummy_thread.start()

    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
