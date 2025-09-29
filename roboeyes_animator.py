import os
import threading
import time
import random
from typing import Optional
from PIL import ImageDraw, ImageFont

import mp_time_shim  # patches time.ticks_* for the MicroPython-style timing

# Import moods + directions so we can occasionally nudge to right-edge positions
from roboeyes import RoboEyes, DEFAULT, ANGRY, HAPPY, TIRED, E, NE, SE
from pil_framebuffer import PILFrameBuffer, RegionFrameBuffer


class FocusMode:
    FOCUSED = 1        # counting up (non-zero)
    WARNING = 2        # grace period / at-risk (your app sets this)
    DISTRACTED = 3     # idle at 00:00 (not focused)


class RoboEyeAnimator(threading.Thread):
    """
    128x64 transparent OLED:
      - Eyes constrained to TOP HALF (slightly lower than before), smaller spacing, more-rounded corners.
      - Timer font 25, placed higher in the lower half.
      - Startup: HAPPY + subtle vertical flicker (~2.5s), no SAD.
      - Blinks less frequent.
      - Random 3s HAPPY bursts while focused.
      - Grace period preserved: 'DISTRACTED'/ANGRY only when blink_on=True.
      - Mood is reasserted each frame so blinks never revert to DEFAULT.
      - Occasional right-edge nudges so eyes visibly use the whole right side.
    """
    def __init__(self, oled_display, fps: int = 30,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None,
                 # Layout knobs tuned for 128x64:
                 margin_x: int = 2,         # minimal margins -> more right-edge reach
                 margin_top: int = 6,       # slightly lower than before
                 gap_mid: int = 1):         # tiny gap between halves
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
        now = time.perf_counter()
        self._startup_until = now + 2.5     # HAPPY + slight v-flicker at boot
        self._seen_first_timer = False      # don't trigger SAD on first "00:00"
        self._happy_until = 0.0
        self._next_happy_check = now + random.uniform(2.5, 4.0)  # first check soon
        self._sad_until = 0.0
        self._warning_shake_on_until = 0.0
        self._next_warning_burst = now + 0.9
        self._next_edge_bias_check = now + random.uniform(5.0, 8.0)  # occasional extreme-right nudges

        # Fonts
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 25)  # requested size
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font

        if warn_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.warn_font = ImageFont.truetype(font_path, 14)  # compact 'DISTRACTED'
            except Exception:
                self.warn_font = ImageFont.load_default()
        else:
            self.warn_font = warn_font

        # Master framebuffer
        W, H = self.oled.width, self.oled.height  # 128x64 expected
        self.master_fb = PILFrameBuffer(W, H)

        # --- Top-half region for eyes (slightly lower; nearly full width) ---
        half_h = H // 2
        eyes_x = margin_x
        eyes_y = margin_top
        eyes_w = W - 2 * margin_x
        eyes_h = half_h - eyes_y - gap_mid
        # Minimums to avoid negative ranges in RoboEyes
        MIN_EYE_W, MIN_EYE_H, MIN_SPACE = 20, 16, 6
        MIN_REGION_W = 2 * MIN_EYE_W + MIN_SPACE + 2
        MIN_REGION_H = max(MIN_EYE_H + 4, 24)
        eyes_w = max(eyes_w, MIN_REGION_W)
        eyes_h = max(eyes_h, MIN_REGION_H)
        # Clamp inside top half
        if eyes_x + eyes_w > W:
            eyes_w = W - eyes_x
        if eyes_y + eyes_h > half_h:
            eyes_h = half_h - eyes_y

        self.eyes_region = RegionFrameBuffer(self.master_fb, eyes_x, eyes_y, eyes_w, eyes_h)

        # --- on_show: draw timer in bottom half and push once ---
        def on_show(_ro):
            img = self.master_fb.image
            d = ImageDraw.Draw(img)

            # Clear lower half (inclusive) each frame
            lower_y0 = half_h + gap_mid
            d.rectangle((0, lower_y0, W - 1, H - 1), fill=1)  # white

            # "DISTRACTED" ONLY when blinking is active -> preserves grace period
            txt = None
            fnt = self.timer_font
            if self.timer_blink_on:
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
                # Place high in the lower half (slightly higher per your request)
                y = lower_y0  # top line of lower half
                x = max(0, (W - tw) // 2)
                d.text((x, y), txt, fill=0, font=fnt)

            # Sweat drop only during explicit SAD window
            now2 = time.perf_counter()
            if now2 < self._sad_until:
                ex = self.eyes_region.x0 + int(self.eyes_region.width * 0.75)
                ey = self.eyes_region.y0 + int(self.eyes_region.height * 0.15)
                r = 3
                d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=0)
                d.polygon([(ex, ey - r - 2), (ex - 2, ey - 1), (ex + 2, ey - 1)], fill=0)

            self.oled.display_image(img)

        # Create RoboEyes in the top-half region
        self.eyes = RoboEyes(self.eyes_region, self.eyes_region.width, self.eyes_region.height,
                             frame_rate=self.fps, on_show=on_show)

        # --- Eye geometry: a touch smaller, more rounded, smaller spacing ---
        EYE_W, EYE_H, EYE_R, EYE_SPACE = 20, 18, 8, 6  # more rounded corners (R=8), SPACE=6
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

        # Behaviors
        # Blinks less often overall (5–12 s)
        self.eyes.set_auto_blinker(True, interval=5, variation=7)
        self.eyes.set_idle_mode(True, interval=1, variation=2)

        self._apply_mood(initial=True)

    # --- External API ---
    def set_state(self, focused: bool, warning: bool = False):
        with self._lock:
            if focused:
                self.mode = FocusMode.FOCUSED
            elif warning:
                self.mode = FocusMode.WARNING
            else:
                self.mode = FocusMode.DISTRACTED
        # Re-assert mood immediately
        self._apply_mood()

    def set_timer(self, text: str, blink_on: bool):
        with self._lock:
            prev = self.timer_text
            self.prev_timer_text = prev
            self.timer_text = text or ""
            self.timer_blink_on = bool(blink_on)

            # On first-ever "00:00", do NOT trigger SAD (boot condition)
            if not self._seen_first_timer:
                self._seen_first_timer = True
            else:
                # Detect reset to 00:00 while not focused -> 3s SAD
                if self.timer_text == "00:00" and self.prev_timer_text != "00:00":
                    if self.mode in (FocusMode.DISTRACTED, FocusMode.WARNING):
                        self._sad_until = time.perf_counter() + 3.0

        self._apply_mood()

    # --- Mood / animation logic (called on state/timer changes AND each frame) ---
    def _apply_mood(self, initial: bool = False):
        with self._lock:
            now = time.perf_counter()
            focused = (self.mode == FocusMode.FOCUSED)
            warning = (self.mode == FocusMode.WARNING)
            distracted = (self.mode == FocusMode.DISTRACTED)

            # Start with whatever we currently have to avoid stomping moods on blink
            desired_mood = self.eyes.mood

            # Startup: force HAPPY + light vertical flicker for ~2.5s
            if now < self._startup_until:
                desired_mood = HAPPY
                self.eyes.vert_flicker(True, amplitude=1)
                self.eyes.horiz_flicker(False)
                self.eyes.set_idle_mode(True, interval=1, variation=2)
            else:
                # Stop startup flicker if it was on
                self.eyes.vert_flicker(False)

                if focused:
                    # Idle roam
                    self.eyes.set_idle_mode(True, interval=1, variation=2)
                    # Random HAPPY bursts ~3s, less often (3–6s checks, 30% chance)
                    if now >= self._next_happy_check and now >= self._happy_until:
                        if random.random() < 0.30:
                            self._happy_until = now + 3.0
                        self._next_happy_check = now + random.uniform(3.0, 6.0)
                    if now < self._happy_until:
                        desired_mood = HAPPY
                    else:
                        desired_mood = DEFAULT

                elif warning:
                    # Grace period: calm unless timer is actually blinking
                    self.eyes.set_idle_mode(True, interval=1, variation=2)
                    if self.timer_blink_on:
                        desired_mood = ANGRY
                        # Intermittent short shake during blink period only
                        if now >= self._next_warning_burst:
                            self._warning_shake_on_until = now + 0.12
                            self._next_warning_burst = now + 0.8 + random.uniform(0.0, 0.4)
                        self.eyes.horiz_flicker(now < self._warning_shake_on_until, amplitude=2)
                    else:
                        self.eyes.horiz_flicker(False)
                        desired_mood = DEFAULT

                elif distracted:
                    # Calm idle
                    self.eyes.set_idle_mode(True, interval=1, variation=2)
                    desired_mood = DEFAULT

                # Temporary SAD (TIRED) overlay if active
                if now < self._sad_until:
                    desired_mood = TIRED

                # Occasional nudge toward right edge so the eyes visibly use all space
                if now >= self._next_edge_bias_check and not warning:
                    # Pick one of the right-side targets
                    self.eyes.set_position(random.choice([E, NE, SE]))
                    self._next_edge_bias_check = now + random.uniform(6.0, 10.0)

            # Only change if different to avoid unnecessary toggling
            if self.eyes.mood != desired_mood:
                self.eyes.mood = desired_mood

    # --- Thread loop ---
    def run(self):
        self.running = True
        frame_dt = 1.0 / float(self.fps)
        self.eyes.open()

        while self.running:
            start = time.perf_counter()

            # Clear full frame + eyes region to prevent afterimages
            self.master_fb.fill(0)      # 0 => white via mapper
            self.eyes_region.fill(0)

            # Re-assert mood each frame so blinks do NOT revert it
            self._apply_mood()

            # Draw eyes; on_show overlays timer and pushes once
            self.eyes.update()

            # Simple frame limiter
            elapsed = time.perf_counter() - start
            sleep_for = frame_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self):
        self.running = False
