import os
import threading
import time
from typing import Optional
from PIL import ImageDraw, ImageFont

import mp_time_shim  # patches time.ticks_* for the MicroPython-style timing

from roboeyes import RoboEyes, DEFAULT, ANGRY
from pil_framebuffer import PILFrameBuffer, RegionFrameBuffer


class FocusMode:
    FOCUSED = 1
    WARNING = 2   # timer blinking (at-risk)
    DISTRACTED = 3


class RoboEyeAnimator(threading.Thread):
    """
    Eyes constrained to the TOP HALF of a 128x64 display (with margins),
    timer text centered in the BOTTOM HALF. Angry eyelids only when blinking.
    """
    def __init__(self, oled_display, fps: int = 25,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None,
                 # Layout knobs tuned for 128x64 transparent OLED:
                 margin_x: int = 8,         # left/right inset for the eyes region
                 margin_top: int = 3,       # top inset for the eyes region
                 gap_mid: int = 2           # small gap between halves
                 ):
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
            # Use your font if available, otherwise fall back
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 24)  # slightly smaller for 64px tall screen
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font
        self.warn_font = warn_font or self.timer_font

        # Master framebuffer
        W, H = self.oled.width, self.oled.height  # expected 128x64
        self.master_fb = PILFrameBuffer(W, H)

        # --- Top-half region for eyes ---
        half_h = H // 2
        eyes_w_raw = W - 2 * margin_x
        eyes_h_raw = half_h - margin_top - gap_mid

        # Hard minimums to avoid negative ranges inside RoboEyes (random constraints)
        # and to allow two eyes + spacing to fit:
        MIN_EYE_W = 22      # single eye width
        MIN_EYE_H = 18      # single eye height
        MIN_SPACE = 8       # space between eyes
        MIN_REGION_W = 2 * MIN_EYE_W + MIN_SPACE + 2   # +2 for safety
        MIN_REGION_H = max(MIN_EYE_H + 4, 24)

        eyes_w = max(eyes_w_raw, MIN_REGION_W)
        eyes_h = max(eyes_h_raw, MIN_REGION_H)

        eyes_x = max(0, margin_x)
        eyes_y = max(0, margin_top)

        # Clamp if we went beyond the screen (shouldn’t happen on 128x64 with chosen mins)
        if eyes_x + eyes_w > W:
            eyes_w = W - eyes_x
        if eyes_y + eyes_h > half_h:  # stay in top half
            eyes_h = half_h - eyes_y

        self.eyes_region = RegionFrameBuffer(self.master_fb, eyes_x, eyes_y, eyes_w, eyes_h)

        # --- on_show: draw timer (bottom half) and push to OLED ---
        def on_show(_ro):
            img = self.master_fb.image

            # Timer/distracted text
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

                lower_y0 = half_h + gap_mid
                # Center in lower half, fully visible
                y = lower_y0 + max(0, (H - lower_y0 - th) // 2)
                x = max(0, (W - tw) // 2)
                d.text((x, y), txt, fill=0, font=fnt)  # black ink on white

            self.oled.display_image(img)

        # Create RoboEyes inside the top-half region
        self.eyes = RoboEyes(self.eyes_region, self.eyes_region.width, self.eyes_region.height,
                             frame_rate=self.fps, on_show=on_show)

        # --- Make the eyes smaller (safe for 128x64 top half) ---
        # Two eyes (L/R) each ~24x20 with ~12px spacing fits comfortably.
        EYE_W = 24
        EYE_H = 20
        EYE_R = 6    # corner radius
        EYE_SPACE = 12

        # If region is tight, scale down a little more to guarantee positivity
        total_min_w = 2 * EYE_W + EYE_SPACE
        if self.eyes_region.width < total_min_w:
            scale = self.eyes_region.width / float(total_min_w)
            EYE_W = max(18, int(EYE_W * scale))
            EYE_H = max(16, int(EYE_H * scale))
            EYE_SPACE = max(8, int(EYE_SPACE * scale))

        self.eyes.eyes_width(EYE_W, EYE_W)
        self.eyes.eyes_height(EYE_H, EYE_H)
        self.eyes.eyes_radius(EYE_R, EYE_R)
        self.eyes.eyes_spacing(EYE_SPACE)

        # Behavior defaults
        self.eyes.set_auto_blinker(True, interval=2, variation=3)
        self.eyes.set_idle_mode(True, interval=1, variation=2)
        self._apply_mood()  # consistent with initial state

    # --- External API expected by your app ---
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
        # Eyelids angry only while blinking (warning)
        self._apply_mood()

    # --- Mood/animation rules ---
    def _apply_mood(self):
        with self._lock:
            focused = (self.mode == FocusMode.FOCUSED)
            warning = (self.mode == FocusMode.WARNING)
            distracted = (self.mode == FocusMode.DISTRACTED)

            # Baseline calm
            self.eyes.mood = DEFAULT
            self.eyes.vert_flicker(False)
            self.eyes.horiz_flicker(False)

            if focused:
                self.eyes.set_idle_mode(True, interval=1, variation=2)
            elif warning:
                # ONLY show angry eyelids when timer is blinking
                if self.timer_blink_on:
                    self.eyes.mood = ANGRY
                self.eyes.set_idle_mode(True, interval=1, variation=2)
                self.eyes.horiz_flicker(True, amplitude=2)  # subtle shake
            elif distracted:
                self.eyes.set_idle_mode(False)
                self.eyes.horiz_flicker(True, amplitude=3)  # stronger motion, no angry lids

    # --- Thread loop ---
    def run(self):
        self.running = True
        frame_dt = 1.0 / float(self.fps)
        self.eyes.open()

        while self.running:
            start = time.perf_counter()

            # Clear full frame to white *each* cycle to avoid ghosting
            self.master_fb.fill(0)  # 0=>white via mapper

            # Update eyes (draws into region) then on_show adds timer + pushes
            self.eyes.update()

            # Frame limiter
            elapsed = time.perf_counter() - start
            sleep_for = frame_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self):
        self.running = False
