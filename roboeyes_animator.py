import os
import threading
import time
from typing import Optional
from PIL import ImageDraw, ImageFont, Image

import mp_time_shim  # patches time.ticks_* for the MicroPython-style timing

from roboeyes import RoboEyes, DEFAULT, ANGRY, HAPPY, TIRED
from pil_framebuffer import PILFrameBuffer, RegionFrameBuffer


class FocusMode:
    FOCUSED = 1        # counting up (non-zero)
    WARNING = 2        # timer blinking "DISTRACTED"
    DISTRACTED = 3     # idle at 00:00 (not focused)


class RoboEyeAnimator(threading.Thread):
    """
    Eyes constrained to the TOP HALF of a 128x64 display (with margins).
    Timer text in the BOTTOM HALF, placed high to avoid being too low.
    Behaviors:
      - Focused: default mood + more frequent periodic HAPPY flashes.
      - Warning (blinking): always ANGRY; intermittent short shake bursts only.
      - Distracted (00:00 idle): calm; if reset detected, show SAD ~3s (with sweat).
    Performance:
      - Double-buffered: draw eyes to offscreen, overlay text on a copy, push once.
      - Full-frame clear each loop to kill afterimages & edge pixels.
    """
    def __init__(self, oled_display, fps: int = 30,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None,
                 # Layout knobs tuned for 128x64 transparent OLED:
                 margin_x: int = 8,         # left/right inset for the eyes region
                 margin_top: int = 4,       # top inset for the eyes region
                 gap_mid: int = 2           # small gap between halves
                 ):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = int(fps)
        self.mode = FocusMode.DISTRACTED
        self.timer_text = ""
        self.prev_timer_text = ""
        self.timer_blink_on = False
        self.running = False
        self._lock = threading.Lock()

        # Timed behaviors
        self._happy_until = 0.0
        self._next_happy_check = time.perf_counter() + 1.5  # first check soon
        self._sad_until = 0.0
        self._warning_shake_on_until = 0.0
        self._next_warning_burst = 0.0

        # Fonts
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 22)
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font

        if warn_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.warn_font = ImageFont.truetype(font_path, 14)  # smaller "DISTRACTED"
            except Exception:
                self.warn_font = ImageFont.load_default()
        else:
            self.warn_font = warn_font

        # Master framebuffer
        W, H = self.oled.width, self.oled.height  # expected 128x64
        self.master_fb = PILFrameBuffer(W, H)

        # --- Top-half region for eyes ---
        half_h = H // 2
        eyes_w_raw = W - 2 * margin_x
        eyes_h_raw = half_h - margin_top - gap_mid

        # Hard minimums to avoid negative ranges inside RoboEyes
        MIN_EYE_W = 20
        MIN_EYE_H = 16
        MIN_SPACE = 8
        MIN_REGION_W = 2 * MIN_EYE_W + MIN_SPACE + 2
        MIN_REGION_H = max(MIN_EYE_H + 4, 24)

        eyes_w = max(eyes_w_raw, MIN_REGION_W)
        eyes_h = max(eyes_h_raw, MIN_REGION_H)

        eyes_x = max(0, margin_x)
        eyes_y = max(0, margin_top)

        # Clamp within top half
        if eyes_x + eyes_w > W:
            eyes_w = W - eyes_x
        if eyes_y + eyes_h > half_h:
            eyes_h = half_h - eyes_y

        self.eyes_region = RegionFrameBuffer(self.master_fb, eyes_x, eyes_y, eyes_w, eyes_h)

        # --- on_show: compose text onto a COPY (double-buffer), then push ---
        def on_show(_ro):
            # Copy the fully drawn eyes buffer to avoid tearing during OLED write
            frame = self.master_fb.snapshot()
            d = ImageDraw.Draw(frame)

            # Clear LOWER half each frame (on the copy) to avoid afterimages
            lower_y0 = half_h + gap_mid
            d.rectangle((0, lower_y0, W - 1, H - 1), fill=1)  # white

            # Render timer/distracted text higher in lower half
            txt = None
            fnt = self.timer_font
            if self.mode == FocusMode.WARNING:
                # While in WARNING, always show DISTRACTED (smaller font)
                txt = "DISTRACTED"
                fnt = self.warn_font
            elif self.timer_text:
                txt = self.timer_text

            if txt:
                if hasattr(d, "textbbox"):
                    tb = d.textbbox((0, 0), txt, font=fnt)
                    tw = tb[2] - tb[0]
                    th = tb[3] - tb[1]
                else:
                    tw = int(d.textlength(txt, font=fnt))
                    th = getattr(fnt, "size", 12)

                # Place near the top of lower half to avoid being too low
                y = lower_y0 + 1
                x = max(0, (W - tw) // 2)
                d.text((x, y), txt, fill=0, font=fnt)

            # Optional: draw sweat drop during SAD period (~3s after reset)
            now = time.perf_counter()
            if now < self._sad_until:
                ex = self.eyes_region.x0 + int(self.eyes_region.width * 0.75)
                ey = self.eyes_region.y0 + int(self.eyes_region.height * 0.15)
                r = 3
                d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=0)
                d.polygon([(ex, ey - r - 2), (ex - 2, ey - 1), (ex + 2, ey - 1)], fill=0)

            # Single atomic push to the OLED
            self.oled.display_image(frame)

        # Create RoboEyes inside the top-half region
        self.eyes = RoboEyes(self.eyes_region, self.eyes_region.width, self.eyes_region.height,
                             frame_rate=self.fps, on_show=on_show)

        # --- Eye geometry: smaller than default for 128x64 ---
        EYE_W = 22
        EYE_H = 18
        EYE_R = 6
        EYE_SPACE = 10

        total_min_w = 2 * EYE_W + EYE_SPACE
        if self.eyes_region.width < total_min_w:
            scale = self.eyes_region.width / float(total_min_w)
            EYE_W = max(16, int(EYE_W * scale))
            EYE_H = max(14, int(EYE_H * scale))
            EYE_SPACE = max(6, int(EYE_SPACE * scale))

        self.eyes.eyes_width(EYE_W, EYE_W)
        self.eyes.eyes_height(EYE_H, EYE_H)
        self.eyes.eyes_radius(EYE_R, EYE_R)
        self.eyes.eyes_spacing(EYE_SPACE)

        # Behavior defaults
        self.eyes.set_auto_blinker(True, interval=2, variation=3)
        self.eyes.set_idle_mode(True, interval=1, variation=2)

        # Initialize intermittent warning burst schedule
        now = time.perf_counter()
        self._next_warning_burst = now + 0.7

        self._apply_mood(initial=True)

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
            prev = self.timer_text
            self.prev_timer_text = prev
            self.timer_text = text or ""
            self.timer_blink_on = bool(blink_on)

            # Detect auto-reset to 00:00 while NOT focused: trigger 3s SAD
            if self.timer_text == "00:00" and self.prev_timer_text != "00:00":
                if self.mode in (FocusMode.DISTRACTED, FocusMode.WARNING):
                    self._sad_until = time.perf_counter() + 3.0

        self._apply_mood()

    # --- Mood/animation rules ---
    def _apply_mood(self, initial: bool=False):
        with self._lock:
            focused = (self.mode == FocusMode.FOCUSED)
            warning = (self.mode == FocusMode.WARNING)
            distracted = (self.mode == FocusMode.DISTRACTED)
            now = time.perf_counter()

            # Base calm
            self.eyes.mood = DEFAULT
            self.eyes.vert_flicker(False)
            self.eyes.horiz_flicker(False)

            # Focused: idle roam; frequent HAPPY flashes (~60% chance every 2–3s)
            if focused:
                self.eyes.set_idle_mode(True, interval=1, variation=2)
                if now >= self._next_happy_check and now >= self._happy_until:
                    # 60% chance
                    if (int(now * 997) % 10) < 6:
                        self._happy_until = now + 0.9
                    # next check 2–3s later
                    self._next_happy_check = now + 2.0 + ((int(now * 1237) % 1000) / 1000.0)
                if now < self._happy_until:
                    self.eyes.mood = HAPPY

            # Warning: ALWAYS angry while blinking cycle is active; intermittent short shake
            elif warning:
                self.eyes.mood = ANGRY  # keep angry for entire WARNING period
                self.eyes.set_idle_mode(True, interval=1, variation=2)
                if now >= self._next_warning_burst:
                    self._warning_shake_on_until = now + 0.12
                    self._next_warning_burst = now + 0.8 + ((int(now * 1009) % 400) / 1000.0)
                self.eyes.horiz_flicker(now < self._warning_shake_on_until, amplitude=2)

            # Distracted: calm; allow idle roam (no angry, no shake)
            elif distracted:
                self.eyes.set_idle_mode(True, interval=1, variation=2)

            # Temporary SAD overlay after reset
            if now < self._sad_until:
                self.eyes.mood = TIRED  # closest to "sad" mood

    # --- Thread loop ---
    def run(self):
        self.running = True
        frame_dt = 1.0 / float(self.fps)
        self.eyes.open()

        while self.running:
            start = time.perf_counter()

            # Full-frame clear to kill afterimages & stray edge pixels
            self.master_fb.fill(0)  # 0 => white via mapper

            # Clear eyes region (redundant but cheap; guarantees clean top-half)
            self.eyes_region.fill(0)

            # Update eyes (draws into top region); on_show overlays timer on a COPY and pushes
            self.eyes.update()

            # Frame limiter
            elapsed = time.perf_counter() - start
            sleep_for = frame_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self):
        self.running = False
