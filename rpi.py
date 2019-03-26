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

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    import FakeRPi.GPIO as GPIO

import time
import requests
import threading
import multiprocessing
import logging
import wiringpi

from songs import ovcaci_ctveraci_notes, bezi_liska_k_taboru_notes


logger = logging.getLogger('__name__')
logger.setLevel(logging.INFO)

port = 8000
new_message_url = "http://localhost:%s/a/message/new" % port

define("port", default=port, help="run on the given port", type=int)
define("debug", default=True, help="run in debug mode")

# interrupt_flag = threading.Event()
button_click_flag = threading.Event()

led_colors = ['green', 'yellow', 'orange', 'red', 'purple']
pins = [21, 20, 16, 12, 25]
resistor_pin = 23
# tones = [262, 294, 330, 349, 392] # C1, D1, E1, F1, G1
tones = [523, 587, 659, 698, 784] # C2, D2, E2, F2, G2
#tones = [x + x // 2 for x in [262, 294, 330, 349, 392]] # C1, D1, E1, F1, G1
tone_pin = 40
# frequency of LED change in seconds
pause_length = 0.3
pattern = None



GPIO.setmode(GPIO.BCM)
GPIO.setup(40, GPIO.IN)
wiringpi.wiringPiSetupGpio()
wiringpi.softToneCreate(tone_pin)


def rpi_client(button_click_flag):
    
    led_array = LEDArray(pins, tones, led_colors)
    button_click_flag.wait()
    while True:
        t = multiprocessing.Process(target=led_array.shine, args=[pattern, pause_length, tone_pin])
        t.start()
        button_click_flag.wait()
        # if button was clicked before t ended, terminate t and clear all LEDs (set to 0)
        if t.exitcode is None or t.exitcode != 0:
            t.terminate()
            time.sleep(0.1)
            led_array.clear()
    GPIO.cleanup


rpi_thread = threading.Thread(target=rpi_client, args=[button_click_flag])

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
        self.render("index.html", pause_length=pause_length)


class SliderHandler(tornado.web.RequestHandler):
    def get(self):
        global pause_length
        pause_length = float(self.request.path.split('/')[2]) / 1000.0
        logger.debug("PAUSE_LENGTH set to: %s seconds" % pause_length)
        # global interrupt_flag
        # interrupt_flag.set()
        # interrupt_flag.clear()


class ButtonHandler(tornado.web.RequestHandler):
    def get(self):
        global pattern
        pattern = self.request.path.split('/')[1].split('_')[1]
        logger.debug("PATTERN set to: %s" % pattern)
        global button_click_flag
        button_click_flag.set()
        button_click_flag.clear()


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


class LED():
    def __init__(self, pin, tone, color):
        self.pin = pin
        self.tone = tone
        self.color = color
        GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)

    def turn_on(self, shine_length=None):
        GPIO.output(self.pin, 1)
        wiringpi.softToneWrite(tone_pin, self.tone)
        requests.post(new_message_url,{'body': '%s_1' % self.color})
        logger.debug('%s_1' % self.color)
    
    def turn_off(self, post=True, tone=False):
        GPIO.output(self.pin, 0)
        if tone:
            wiringpi.softToneWrite(tone_pin, self.tone)
        else:
            wiringpi.softToneWrite(tone_pin, 0)
        if post:
            requests.post(new_message_url,{'body': '%s_0' % self.color})
        logger.debug('%s_0' % self.color)

    def blink(self, length_seconds):
        self.turn_on()
        time.sleep(length_seconds)
        self.turn_off()


class LEDArray():
    def __init__(self, pins, tones, colors):
        self.leds = []
        self.n_led = len(pins)
        for pin, tone, color in zip(pins, tones, colors):
            self.leds.append(LED(pin, tone, color))
    
    def clear(self):
        for led in self.leds:
            led.turn_off(post=False)
        requests.post(new_message_url,{'body': 'clear'})
    
    def light_pattern_1(self, pause_length):
        for led in self.leds:
            led.turn_on()
            time.sleep(pause_length)
            led.turn_off()
    
    def light_pattern_2(self, pause_length):
        for led in self.leds:
            led.turn_on()
            time.sleep(pause_length)
        for led in self.leds:
            led.turn_off(tone=True)
            time.sleep(pause_length)

    def light_pattern_3(self, pause_length):
        for led in self.leds:
            led.turn_on()
            time.sleep(pause_length)
        for led in self.leds[::-1]:
            led.turn_off(tone=True)
            time.sleep(pause_length)
    
    def play_song(self, notes, pause_length):
        for tone, length in notes:
            self.leds[tone].blink(length * pause_length)
    
    def shine(self, pattern, pause_length, tone_pin):
        # the sound has to be defined here to work properly as shine is launched in a separate thread
        wiringpi.softToneCreate(tone_pin)
        if pattern == "1":
            self.light_pattern_1(pause_length)
        elif pattern == "2":
            self.light_pattern_2(pause_length)
        elif pattern == "3":
            self.light_pattern_3(pause_length)
        elif pattern == "4":
            self.play_song(ovcaci_ctveraci_notes, pause_length)
        elif pattern == "5":
            self.play_song(bezi_liska_k_taboru_notes, pause_length)
        else:
            time.sleep(pause_length)


"""
def rpi_client_old(interrupt_flag):
    GPIO.setmode(GPIO.BCM)
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(resistor_pin, GPIO.IN)
    i = 0
    while True:
        wiringpi.softToneWrite(tone_pin, 0)
        if GPIO.input(resistor_pin) == GPIO.HIGH:
            GPIO.wait_for_edge(resistor_pin, GPIO.FALLING)
        GPIO.output(pins[i], 1)
        GPIO.output(pins[i - 1], 0)
        wiringpi.softToneWrite(tone_pin, tones[i])
        requests.post(new_message_url,{'body': led_colors[i]})
        i = (i + 1) % len(led_colors)
        sleep_start = time.time()
        # if slider was changed, reset waiting and wait for the new pause_length amount of seconds
        # if slider wasn't changed within pause_length seconds, False is returned and while loop is stopped
        while interrupt_flag.wait(pause_length):
            pass

        logger.debug("slept for %s seconds." % round(time.time() - sleep_start, 3))
    GPIO.cleanup
"""


def main():
    parse_command_line()
    app = tornado.web.Application(
        [
            (r"/", MainHandler),
            (r"/slider/.*", SliderHandler),
            (r"/pattern.*", ButtonHandler),
            (r"/a/message/new", MessageNewHandler),
            (r"/a/message/updates", MessageUpdatesHandler),
        ],
        template_path=os.path.join(os.path.dirname(__file__), "templates"),
        static_path=os.path.join(os.path.dirname(__file__), "static"),
        debug=options.debug,
    )
    app.listen(options.port)

    rpi_thread.start()

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        print("exiting")
        GPIO.cleanup


if __name__ == "__main__":
    main()
