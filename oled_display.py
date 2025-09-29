# oled_display.py
import os
import threading
import logging
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_OLED import OLED_1in51

logging.basicConfig(level=logging.DEBUG)


class OLEDDisplay:
    def __init__(self):
        self.disp = OLED_1in51.OLED_1in51()
        self.disp.Init()

        # Lock ensures only one thread writes to OLED at a time
        self._io_lock = threading.Lock()

        # Cache common fonts once (so we don’t reload every frame)
        font_path = os.path.join('./lib/waveshare_OLED', 'Font.ttc')
        self.font_cache = {}
        for size in (14, 22, 25, 32):
            try:
                self.font_cache[size] = ImageFont.truetype(font_path, size)
            except Exception:
                self.font_cache[size] = ImageFont.load_default()

    def display_status(self, time_str, x, y, font_size=22):
        """
        Draw a quick status string (usually the timer) at coordinates.
        """
        image = Image.new('1', (self.disp.width, self.disp.height), "WHITE")
        draw = ImageDraw.Draw(image)
        font = self.font_cache.get(font_size, ImageFont.load_default())
        draw.text((x, y), f"{time_str}", font=font, fill=0)
        image = image.rotate(180)

        with self._io_lock:  # serialize SPI transfers
            self.disp.ShowImage(self.disp.getbuffer(image))

    def display_image(self, image: Image.Image):
        """
        Push a prepared PIL image to the OLED.
        Makes a copy so the source can keep being modified without tearing.
        """
        if image.mode != '1':
            img = image.convert('1').copy()
        else:
            img = image.copy()

        img = img.rotate(180)

        with self._io_lock:
            self.disp.ShowImage(self.disp.getbuffer(img))

    @property
    def width(self):
        return self.disp.width

    @property
    def height(self):
        return self.disp.height
