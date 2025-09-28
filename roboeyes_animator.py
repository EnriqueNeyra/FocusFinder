import os
import threading
import time
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

# Patch time.ticks_* for CPython
import mp_time_shim  # noqa: F401

# Import MicroPython RoboEyes (your uploaded file)
from roboeyes import RoboEyes, DEFAULT, ANGRY

from pil_framebuffer import PILFrameBuffer

class FocusMode:
    FOCUSED = 1
    WARNING = 2
    DISTRACTED = 3

class RoboEyeAnimator(threading.Thread):
    """
    Drop-in replacement for your EyeAnimator:
      - set_state(focused, warning)
      - set_timer(text, blink_on)
      - pushes PIL frames via oled.display_image(img)
    """
    def __init__(self, oled_display, fps: int = 20,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = fps
        self.mode = FocusMode.FOCUSED
        self.timer_text = ""
        self.timer_blink_on = False
        self.running = False
        self._lock = threading.Lock()

        # Fonts (keep your existing size / placement feel)
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 26)
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font
        self.warn_font = warn_font or self.timer_font

        # Build a framebuffer RoboEyes can draw into
        self.fb = PILFrameBuffer(self.oled.width, self.oled.height)

        # Callback: when RoboEyes has drawn a frame, we’ll optionally add text
        def on_show(_ro):
            # _ro.fb.image is our PIL Image (mode '1') with white BG and black eyes
            img = _ro.fb.image

            # Draw timer / "DISTRACTED" AFTER eyes so it sits on top
            txt = None
            fnt = self.timer_font
            if self.timer_blink_on:
                txt = "DISTRACTED"
                fnt = self.warn_font
            elif self.timer_text:
                txt = self.timer_text

            if txt:
                d = ImageDraw.Draw(img)
                # Measure and place near the bottom, slightly lower so it clears camera
                if hasattr(d, "textbbox"):
                    tb = d.textbbox((0, 0), txt, font=fnt)
                    tw = tb[2] - tb[0]
                    th = tb[3] - tb[1]
                else:
                    tw = d.textlength(txt, font=fnt)
                    th = getattr(fnt, "size", 12)

                x = (self.oled.width - int(tw)) // 2
                # Nudge downward a touch to avoid your camera behind the colon
                y = self.oled.height - th - 2
                if y < 0: y = 0
                d.text((x, y), txt, fill=0, font=fnt)  # 0=black on white

            # Push to OLED
            self.oled.display_image(img)

        # Create the RoboEyes engine
        self.eyes = RoboEyes(self.fb, self.oled.width, self.oled.height,
                             frame_rate=fps, on_show=on_show)

        # Gentle defaults (open eyes + idle roam + natural blink)
        self.eyes.set_auto_blinker(True, interval=2, variation=3)
        self.eyes.set_idle_mode(True, interval=1, variation=2)

    # External API (kept identical)
    def set_state(self, focused: bool, warning: bool = False):
        with self._lock:
            if focused:
                self.mode = FocusMode.FOCUSED
            elif warning:
                self.mode = FocusMode.WARNING
            else:
                self.mode = FocusMode.DISTRACTED

        # Map to RoboEyes moods/animations
        if focused:
            self.eyes.mood = DEFAULT
            self.eyes.vert_flicker(False)
            self.eyes.horiz_flicker(False)
            self.eyes.set_idle_mode(True, interval=1, variation=2)
        elif warning:
            # At-risk: brows come down via "angry" eyelids and slight tremble
            self.eyes.mood = ANGRY
            self.eyes.vert_flicker(False)
            self.eyes.horiz_flicker(True, amplitude=2)
            self.eyes.set_idle_mode(True, interval=1, variation=2)
        else:
            # Fully distracted: stronger shake to feel urgent
            self.eyes.mood = ANGRY
            self.eyes.horiz_flicker(True, amplitude=4)
            self.eyes.vert_flicker(False)
            self.eyes.set_idle_mode(False)

    def set_timer(self, text: str, blink_on: bool):
        with self._lock:
            self.timer_text = text or ""
            self.timer_blink_on = bool(blink_on)

    def run(self):
        self.running = True
        ft = 1.0 / float(self.fps)
        last = time.time()
        # Start with eyes open
        self.eyes.open()
        while self.running:
            t0 = time.time()
            _dt = t0 - last
            last = t0

            # Advance RoboEyes animations and draw a frame
            self.eyes.update()

            # Maintain ~fps schedule
            elapsed = time.time() - t0
            delay = ft - elapsed
            if delay > 0:
                time.sleep(delay)

    def stop(self):
        self.running = False
