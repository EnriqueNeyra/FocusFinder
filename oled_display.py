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
        
        # Performance optimizations
        self._display_buffer = None  # Reusable buffer to reduce allocations
        self._last_image_hash = None  # Track changes to prevent redundant updates

        # Cache common fonts once (so we don't reload every frame)
        font_path = os.path.join('./lib/waveshare_OLED', 'Font.ttc')
        self.font_cache = {}
        for size in (14, 22, 25, 32):
            try:
                self.font_cache[size] = ImageFont.truetype(font_path, size)
            except Exception:
                self.font_cache[size] = ImageFont.load_default()


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
        Optimized display method with redundancy checks and buffer reuse.
        """
        # Quick hash check to avoid redundant updates
        try:
            img_bytes = image.tobytes()
            img_hash = hash(img_bytes)
            if img_hash == self._last_image_hash:
                return  # Skip identical frames
            self._last_image_hash = img_hash
        except:
            # Fallback if hashing fails
            pass
        
        # Optimize image conversion and rotation
        if image.mode != '1':
            if self._display_buffer is None:
                self._display_buffer = image.convert('1')
            else:
                # Reuse existing buffer to avoid allocations
                self._display_buffer.paste(image.convert('1'))
            img = self._display_buffer
        else:
            img = image

        # Rotate in place if possible to save memory
        img = img.rotate(180)

        with self._io_lock:
            self.disp.ShowImage(self.disp.getbuffer(img))

    @property
    def width(self):
        return self.disp.width

    @property
    def height(self):
        return self.disp.height
