import sys
import os
import logging    
import time
import traceback
from lib.waveshare_OLED import OLED_1in51
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.DEBUG)

class OLEDDisplay:

    def __init__(self):
        self.disp = OLED_1in51.OLED_1in51()
        self.disp.Init()
        self.font_cache = {
            32: ImageFont.truetype(os.path.join('./lib/waveshare_OLED', 'Font.ttc'), 32),
            22: ImageFont.truetype(os.path.join('./lib/waveshare_OLED', 'Font.ttc'), 22),
            }

    def display_status(self, time_str, x, y, font_size):
        image = Image.new('1', (self.disp.width, self.disp.height), "WHITE")
        draw = ImageDraw.Draw(image)
        draw.text((x, y), f"{time_str}", font = self.font_cache[font_size], fill = 0)
        image = image.rotate(180)
        self.disp.ShowImage(self.disp.getbuffer(image))

    # NEW: push a prepared PIL image ('1' or 'L') to the OLED
    def display_image(self, image: Image.Image):
        if image.mode != '1':
            image = image.convert('1')
        image = image.rotate(180)
        self.disp.ShowImage(self.disp.getbuffer(image))

    # NEW: let other modules query the panel size
    @property
    def width(self):
        return self.disp.width

    @property
    def height(self):
        return self.disp.height
