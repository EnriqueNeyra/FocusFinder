# roboeyes_animator.py
import os
import threading
import time
import random
from typing import Optional
from PIL import ImageDraw, ImageFont

import mp_time_shim  # patches time.ticks_* for the MicroPython-style timing

from roboeyes import RoboEyes, DEFAULT, ANGRY, HAPPY, TIRED
from pil_framebuffer import PILFrameBuffer, RegionFrameBuffer


class FocusMode:
    FOCUSED = 1        # counting up (non-zero)
    WARNING = 2        # timer is blinking ("at risk")
    DISTRACTED = 3     # timer reset or not counting


class RoboEyeAnimator(threading.Thread):
    """
    Drives RoboEyes in the top half of the OLED and draws timer / warning in the bottom half.
    Uses a snapshot + cached overlay when pushing to OLED to avoid tearing and reduce CPU.
    """
    def __init__(self,
                 oled_display,
                 fps: int = 20,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None,
                 # Layout knobs for 128x64:
                 margin_x: int = 1,         # minimal margins -> maximize horizontal roam
                 margin_top: int = 2,       # tiny top inset so eyes can use nearly all vertical space
                 gap_mid: int = 0):         # no gap to the midline; eyes fill the entire top half
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = int(fps)
        self.mode = FocusMode.DISTRACTED
        self.timer_text = ""
        self.prev_timer_text = ""
        self.timer_blink_on = False
        self.running = False
        self._lock = threading.Lock()

        now = time.perf_counter()
        self._startup_until = now + 2.5     # HAPPY + slight vertical flicker at boot
        self._seen_first_timer = False      # don't trigger SAD on the very first 00:00
        self._happy_until = 0.0
        self._next_happy_check = now + random.uniform(2.0, 3.5)  # moderate frequency
        self._sad_until = 0.0
        self._warning_shake_on_until = 0.0
        self._next_warning_burst = now + 0.9

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

        # --- Eyes region: fill the entire top half (max vertical space above timer) ---
        half_h = H // 2
        eyes_x = margin_x
        eyes_y = margin_top
        eyes_w = W - 2 * margin_x
        eyes_h = half_h - eyes_y - gap_mid  # gap_mid=0 => reaches the midline

        # Minimums to avoid negative ranges inside RoboEyes
        MIN_EYE_W, MIN_EYE_H, MIN_SPACE = 20, 16, 4
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

        # --- Cached overlay for the lower half to avoid per-frame text work ---
        self._overlay_key = None
        self._overlay_img = None  # full-size image; only lower half used

        def _build_overlay(key_text: str, blink_on: bool):
            # Create a fresh white canvas and draw only the lower half text
            ov = self.master_fb.image.copy()
            d = ImageDraw.Draw(ov)
            lower_y0 = half_h
            # Clear lower half
            d.rectangle((0, lower_y0, W - 1, H - 1), fill=1)

            txt = None
            fnt = self.timer_font
            if blink_on:
                txt = "DISTRACTED"
                fnt = self.warn_font
            elif key_text:
                txt = key_text

            # Thin-space around colon (visual spacing without shifting glyphs too far)
            if txt and (not blink_on) and (":" in txt):
                txt = txt.replace(":", "\u2009:\u2009")

            if txt:
                if hasattr(d, "textbbox"):
                    tb = d.textbbox((0, 0), txt, font=fnt)
                    tw = tb[2] - tb[0]
                    th = tb[3] - tb[1]
                else:
                    tw = int(d.textlength(txt, font=fnt))
                    th = getattr(fnt, "size", 12)
                y = lower_y0 + 3
                x = max(0, (W - tw) // 2)
                d.text((x, y), txt, fill=0, font=fnt)
            return ov

        # --- on_show: compose a snapshot + cached overlay and push atomically ---
        def on_show(_ro):
            # 1) Snapshot the current frame so OLED sees an immutable image
            snap = self.master_fb.image.copy()

            # 2) Rebuild overlay only if timer text/blink state changed
            key = (self.timer_text, self.timer_blink_on)
            if key != self._overlay_key:
                self._overlay_img = _build_overlay(self.timer_text, self.timer_blink_on)
                self._overlay_key = key

            # 3) Paste only the lower half overlay onto the snapshot
            if self._overlay_img is not None:
                lower_box = (0, half_h, W, H)
                snap.paste(self._overlay_img.crop(lower_box), lower_box)

            # 4) Temporary 'sweat drop' during SAD window — draw on the snapshot only
            now2 = time.perf_counter()
            if now2 < self._sad_until:
                d2 = ImageDraw.Draw(snap)
                ex = self.eyes_region.x0 + int(self.eyes_region.width * 0.75)
                ey = self.eyes_region.y0 + int(self.eyes_region.height * 0.15)
                r = 3
                d2.ellipse((ex - r, ey - r, ex + r, ey + r), fill=0)
                d2.polygon([(ex, ey - r - 2), (ex - 2, ey - 1), (ex + 2, ey - 1)], fill=0)

            # 5) Push the immutable snapshot
            self.oled.display_image(snap)

        # Create RoboEyes in the top-half region
        self.eyes = RoboEyes(self.eyes_region, self.eyes_region.width, self.eyes_region.height,
                             frame_rate=self.fps, on_show=on_show)

        # --- Eye geometry: slightly smaller spacing, moderate rounding ---
        EYE_W, EYE_H, EYE_R, EYE_SPACE = 20, 18, 5, 4  # R=5 (less rounded), SPACE=4
        self.eyes.eyes_width(EYE_W, EYE_W)
        self.eyes.eyes_height(EYE_H, EYE_H)
        self.eyes.eyes_radius(EYE_R, EYE_R)
        self.eyes.eyes_spacing(EYE_SPACE)

        # Behaviors
        # Blinks less often overall (~6–14 s)
        self.eyes.set_auto_blinker(True, interval=6, variation=8)
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

    # --- Mood / animation logic ---
    def _apply_mood(self, initial: bool = False):
        with self._lock:
            now = time.perf_counter()
            focused = (self.mode == FocusMode.FOCUSED)
            warning = (self.mode == FocusMode.WARNING)
            distracted = (self.mode == FocusMode.DISTRACTED)

            # Start with current mood so blinks don't snap back to DEFAULT
            # current = self.eyes.get_mood()

            # Boot: brief HAPPY flicker regardless of state
            if initial:
                self.eyes.set_mood(HAPPY)
                return
            if now < self._startup_until:
                self.eyes.set_mood(HAPPY)
                return

            # Focused: neutral DEFAULT with occasional HAPPY bursts
            if focused:
                if now >= self._next_happy_check:
                    self._next_happy_check = now + random.uniform(3.0, 6.0)
                    if random.random() < 0.20:
                        self._happy_until = now + 0.6
                if now < self._happy_until:
                    self.eyes.set_mood(HAPPY)
                else:
                    self.eyes.set_mood(DEFAULT)
                return

            # Warning: only when timer is actually blinking
            if warning and self.timer_blink_on:
                # Short angry flicker bursts (no forced nudge)
                if now >= self._next_warning_burst:
                    self._warning_shake_on_until = now + 0.25
                    self._next_warning_burst = now + 1.0
                if now < self._warning_shake_on_until:
                    self.eyes.set_mood(ANGRY, shake=True)
                else:
                    self.eyes.set_mood(ANGRY, shake=False)
                return

            # Distracted (or warning without blink): calm TIRED unless in SAD window
            if now < self._sad_until:
                self.eyes.set_mood(TIRED)  # could be rendered with a sweat drop in on_show
            else:
                self.eyes.set_mood(TIRED)

    # --- Thread loop ---
    def run(self):
        self.running = True
        frame_dt = 1.0 / max(1, self.fps)

        # Clear whole screen once at start
        self.master_fb.fill(0)  # white background

        while self.running:
            start = time.perf_counter()

            # Re-assert mood each frame so blinks never revert it
            self._apply_mood()

            # Draw eyes; on_show overlays timer and pushes once
            self.eyes.update()

            # Frame limiter
            elapsed = time.perf_counter() - start
            sleep_for = frame_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self):
        self.running = False
