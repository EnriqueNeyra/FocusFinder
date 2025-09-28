import os
import threading
import time
from typing import Optional
from PIL import ImageDraw, ImageFont

import mp_time_shim  # patches time.ticks_* for the MicroPython lib

from roboeyes import RoboEyes, DEFAULT, ANGRY
from pil_framebuffer import PILFrameBuffer, RegionFrameBuffer


class FocusMode:
    FOCUSED = 1
    WARNING = 2   # timer blinking (at-risk)
    DISTRACTED = 3


class RoboEyeAnimator(threading.Thread):
    def __init__(self, oled_display, fps: int = 30,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None,
                 margin_x: int = 8, margin_top: int = 4, margin_between_halves: int = 2):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = int(fps)
        self.mode = FocusMode.FOCUSED
        self.timer_text = ""
        self.timer_blink_on = False
        self.running = False
        self._lock = threading.Lock()

        # Fonts
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 26)
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font
        self.warn_font = warn_font or self.timer_font

        # Master framebuffer covering the whole display
        self.master_fb = PILFrameBuffer(self.oled.width, self.oled.height)

        # Constrain eyes to the TOP HALF (with horizontal margins)
        half_h = self.oled.height // 2
        eyes_w = self.oled.width - 2 * margin_x
        eyes_h = half_h - margin_top - margin_between_halves
        eyes_x = margin_x
        eyes_y = margin_top
        self.eyes_region = RegionFrameBuffer(self.master_fb, eyes_x, eyes_y, eyes_w, eyes_h)

        # on_show draws timer then pushes to OLED
        def on_show(_ro):
            img = self.master_fb.image  # contains both eyes (in region) + timer text

            # Draw timer in LOWER HALF, centered and fully visible
            txt = None
            fnt = self.timer_font
            if self.timer_blink_on:
                txt = "DISTRACTED"
                fnt = self.warn_font
            elif self.timer_text:
                txt = self.timer_text

            if txt:
                d = ImageDraw.Draw(img)
                if hasattr(d, "textbbox"):
                    tb = d.textbbox((0, 0), txt, font=fnt)
                    tw = tb[2] - tb[0]
                    th = tb[3] - tb[1]
                else:
                    tw = int(d.textlength(txt, font=fnt))
                    th = getattr(fnt, "size", 12)

                lower_y0 = half_h + margin_between_halves
                # Place vertically so it’s centered in the lower half and never goes off-screen
                y = lower_y0 + max(0, (self.oled.height - lower_y0 - th) // 2)
                x = max(0, (self.oled.width - tw) // 2)
                d.text((x, y), txt, fill=0, font=fnt)  # 0=black (visible)

            # Push to OLED (PIL '1' image)
            self.oled.display_image(img)

        # Create RoboEyes that draws *inside* the top-half region
        self.eyes = RoboEyes(self.eyes_region, self.eyes_region.width, self.eyes_region.height,
                             frame_rate=self.fps, on_show=on_show)

        # Defaults
        self.eyes.set_auto_blinker(True, interval=2, variation=3)
        self.eyes.set_idle_mode(True, interval=1, variation=2)
        self._apply_mood()  # ensure initial mood consistent

    # External API expected by your app
    def set_state(self, focused: bool, warning: bool = False):
        with self._lock:
            if focused:
                self.mode = FocusMode.FOCUSED
            elif warning:
                self.mode = FocusMode.WARNING
            else:
                self.mode = FocusMode.DISTRACTED
        self._apply_mood()

    def set_timer(self, text: str, blink_on: bool):
        with self._lock:
            self.timer_text = text or ""
            self.timer_blink_on = bool(blink_on)
        # Mood rule: ANGRY eyelids only when timer is blinking (at-risk)
        self._apply_mood()

    # Mood/animation rules centralized here
    def _apply_mood(self):
        with self._lock:
            focused = (self.mode == FocusMode.FOCUSED)
            warning = (self.mode == FocusMode.WARNING)
            distracted = (self.mode == FocusMode.DISTRACTED)

            # Reset to calm baseline
            self.eyes.mood = DEFAULT
            self.eyes.vert_flicker(False)
            self.eyes.horiz_flicker(False)

            if focused:
                self.eyes.set_idle_mode(True, interval=1, variation=2)
            elif warning:
                # Only here do we use ANGRY (eyelids) — when timer is blinking
                if self.timer_blink_on:
                    self.eyes.mood = ANGRY
                self.eyes.set_idle_mode(True, interval=1, variation=2)
                # Small shake to signal risk without being harsh
                self.eyes.horiz_flicker(True, amplitude=2)
            elif distracted:
                # No angry lids here; make motion a bit more erratic but without eyelids
                self.eyes.set_idle_mode(False)
                self.eyes.horiz_flicker(True, amplitude=3)

    def run(self):
        self.running = True
        frame_dt = 1.0 / float(self.fps)
        last = time.perf_counter()
        self.eyes.open()
        while self.running:
            start = time.perf_counter()

            # Clear full frame to white each cycle (prevents ghosting across regions)
            self.master_fb.fill(0)   # 0 here means "white" via our mapper

            # Update + draw eyes (into top region) then on_show() adds timer + pushes
            self.eyes.update()

            # Simple framelimiter
            elapsed = time.perf_counter() - start
            sleep_for = frame_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            last = start

    def stop(self):
        self.running = False
