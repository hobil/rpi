#!/usr/bin/env python3
#
# Inspired by the chat application demo in 
# https://github.com/tornadoweb/tornado/tree/master/demos/chat

import asyncio
import tornado.escape
import tornado.ioloop
import tornado.locks
import tornado.web
from tornado.options import define, options, parse_command_line
import os.path
import uuid

import RPi.GPIO as GPIO
from time import sleep
import requests
import threading

port = 8000

define("port", default=port, help="run on the given port", type=int)
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
        self.render("index.html")


class MessageNewHandler(tornado.web.RequestHandler):
    """Post a new message to the chat room."""

    def post(self):

        message = {"id": str(uuid.uuid4()), "body": self.get_argument('body')}
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

led_colors = ['green', 'yellow', 'orange', 'red']
pins = [21, 16, 12, 8]
delay = 1


def rpi_client():
    GPIO.setmode(GPIO.BCM)
    for color, pin in zip(led_colors, pins):
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    widerstand_pin = 25
    GPIO.setup(widerstand_pin, GPIO.IN)
    i = 0
    while True:
        while GPIO.input(widerstand_pin) == GPIO.LOW:
            GPIO.output(pins[i], 1)
            GPIO.output(pins[i - 1], 0)
            requests.post('http://localhost:' + str(port) + '/a/message/new',{'body': led_colors[i]})
            i = (i + 1) % 4
            sleep(delay)
    GPIO.cleanup


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
        # xsrf_cookies=True, #TODO: SAFETY?
        debug=options.debug,
    )
    app.listen(options.port)

    rpi_thread = threading.Thread(target=rpi_client)
    rpi_thread.start()

    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
