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
    WARNING = 2        # grace/at-risk period (your app sets this)
    DISTRACTED = 3     # idle at 00:00 (not focused)


class RoboEyeAnimator(threading.Thread):
    """
    128x64 transparent OLED eyes + timer.

    Key behavior guarantees in this version:
      - WARNING: ANGRY + horizontal flicker persists for the *entire* blink window.
      - No forced right-edge nudges (natural roaming only).
      - Startup: HAPPY + subtle vertical flicker for ~2.5 s (no SAD at boot).
      - FOCUSED: random HAPPY bursts (~3 s), moderate frequency.
      - Blinks less frequent overall (≈ every 6–14 s).
      - Eyes fill the entire top half; timer (size 25) sits at the top of the lower half.
    """
    def __init__(self, oled_display, fps: int = 20,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None,
                 # Layout knobs for 128x64:
                 margin_x: int = 1,
                 margin_top: int = 2,
                 gap_mid: int = 0):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = int(fps)
        self.mode = FocusMode.DISTRACTED
        self.timer_text = ""
        self.prev_timer_text = ""
        self.timer_blink_on = False
        self.running = False
        self._lock = threading.Lock()
        
        # Performance optimizations - simplified and more efficient
        self._display_dirty = True
        self._last_timer_state = None  # Track timer changes more efficiently
        self._last_mood_state = None   # Track mood changes more efficiently
        self._frame_count = 0
        self._last_display_time = 0

        # Timed behaviors
        now = time.perf_counter()
        self._startup_until = now + 2.5
        self._seen_first_timer = False
        self._happy_until = 0.0
        self._next_happy_check = now + random.uniform(2.0, 3.5)
        self._sad_until = 0.0
        self._warning_shake_on_until = 0.0
        self._next_warning_burst = now + 0.9

        # Track angry persistence during blink period
        self._angry_active = False
        self._distracted_blinking = False

        # Fonts
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 25)
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font

        if warn_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.warn_font = ImageFont.truetype(font_path, 14)
            except Exception:
                self.warn_font = ImageFont.load_default()
        else:
            self.warn_font = warn_font

        # Master framebuffer
        W, H = self.oled.width, self.oled.height
        self.master_fb = PILFrameBuffer(W, H)

        # Eyes region
        half_h = H // 2
        eyes_x = margin_x
        eyes_y = margin_top
        eyes_w = W - 2 * margin_x
        eyes_h = half_h - eyes_y - gap_mid

        MIN_EYE_W, MIN_EYE_H, MIN_SPACE = 20, 16, 4
        MIN_REGION_W = 2 * MIN_EYE_W + MIN_SPACE + 2
        MIN_REGION_H = max(MIN_EYE_H + 4, 24)
        eyes_w = max(eyes_w, MIN_REGION_W)
        eyes_h = max(eyes_h, MIN_REGION_H)

        if eyes_x + eyes_w > W:
            eyes_w = W - eyes_x
        if eyes_y + eyes_h > half_h:
            eyes_h = half_h - eyes_y

        self.eyes_region = RegionFrameBuffer(self.master_fb, eyes_x, eyes_y, eyes_w, eyes_h)

        # --- on_show: optimized callback with minimal allocations ---
        def on_show(_ro):
            # Rate limit display updates to prevent overwhelming the Pi Zero 2W
            current_time = time.perf_counter()
            min_frame_time = 1.0 / self.fps
            
            if current_time - self._last_display_time < min_frame_time:
                return  # Skip this frame to maintain target FPS
            
            self._last_display_time = current_time
            
            # Work directly with master framebuffer to avoid copies
            img = self.master_fb.image
            d = ImageDraw.Draw(img)

            lower_y0 = half_h
            d.rectangle((0, lower_y0, W - 1, H - 1), fill=1)

            txt = None
            fnt = self.timer_font
            if self.timer_blink_on:
                txt = "DISTRACTED"
                fnt = self.warn_font
            elif self.timer_text:
                txt = self.timer_text

            if txt and not self.timer_blink_on and ":" in txt:
                txt = txt.replace(":", "\u2009:\u2009")

            if txt:
                if hasattr(d, "textbbox"):
                    tb = d.textbbox((0, 0), txt, font=fnt)
                    tw = tb[2] - tb[0]
                else:
                    tw = int(d.textlength(txt, font=fnt))
                y = lower_y0 + 3
                x = max(0, (W - tw) // 2)
                d.text((x, y), txt, fill=0, font=fnt)

            now2 = time.perf_counter()
            if now2 < self._sad_until:
                ex = self.eyes_region.x0 + int(self.eyes_region.width * 0.75)
                ey = self.eyes_region.y0 + int(self.eyes_region.height * 0.15)
                r = 3
                d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=0)
                d.polygon([(ex, ey - r - 2), (ex - 2, ey - 1), (ex + 2, ey - 1)], fill=0)

            # Send image directly to display (no double buffering needed with rate limiting)
            self.oled.display_image(img)

        self.eyes = RoboEyes(self.eyes_region, self.eyes_region.width, self.eyes_region.height,
                             frame_rate=self.fps, on_show=on_show)

        EYE_W, EYE_H, EYE_R, EYE_SPACE = 20, 18, 5, 4
        total_min_w = 2 * EYE_W + EYE_SPACE
        if self.eyes_region.width < total_min_w:
            scale = self.eyes_region.width / float(total_min_w)
            EYE_W = max(16, int(EYE_W * scale))
            EYE_H = max(14, int(EYE_H * scale))
            EYE_SPACE = max(4, int(EYE_SPACE * scale))

        self.eyes.eyes_width(EYE_W, EYE_W)
        self.eyes.eyes_height(EYE_H, EYE_H)
        self.eyes.eyes_radius(EYE_R, EYE_R)
        self.eyes.eyes_spacing(EYE_SPACE)

        self.eyes.set_auto_blinker(True, interval=6, variation=8)
        self.eyes.set_idle_mode(True, interval=1, variation=2)

        self._apply_mood(initial=True)

    # --- External API ---
    def set_state(self, focused: bool, warning: bool = False):
        with self._lock:
            prev_mode = self.mode
            if focused:
                self.mode = FocusMode.FOCUSED
            elif warning:
                self.mode = FocusMode.WARNING
            else:
                self.mode = FocusMode.DISTRACTED
            
            # Reset distracted blinking state when leaving distracted mode
            if prev_mode == FocusMode.DISTRACTED and self.mode != FocusMode.DISTRACTED:
                self._distracted_blinking = False
                self._angry_active = False
        self._apply_mood()

    def set_timer(self, text: str, blink_on: bool):
        with self._lock:
            prev = self.timer_text
            text = text or ""
            blink_on = bool(blink_on)
            
            # Create state tuple for efficient comparison
            current_state = (text, blink_on)
            if current_state == self._last_timer_state:
                return  # No change, skip update
                
            self._last_timer_state = current_state
            self.prev_timer_text = prev
            self.timer_text = text

            # Detect start/stop of blinking for angry persistence
            if blink_on and not self.timer_blink_on:
                # Always set angry active when blinking starts (could be warning or distracted)
                self._angry_active = True
                # Track distracted blinking specifically for consistent angry behavior
                if self.mode == FocusMode.DISTRACTED or self.mode == FocusMode.WARNING:
                    self._distracted_blinking = True
            elif not blink_on and self.timer_blink_on:
                self._distracted_blinking = False
                self._angry_active = False  # stop angry

            self.timer_blink_on = blink_on

            if not self._seen_first_timer:
                self._seen_first_timer = True
            else:
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

            # Create state tuple for efficient comparison
            current_mood_state = (focused, warning, distracted, self._angry_active, 
                                now < self._startup_until, now < self._happy_until, now < self._sad_until)
            
            if not initial and current_mood_state == self._last_mood_state:
                return  # No mood change, skip expensive operations
            
            self._last_mood_state = current_mood_state
            desired_mood = self.eyes.mood

            if now < self._startup_until:
                desired_mood = HAPPY
                self.eyes.vert_flicker(True, amplitude=1)
                self.eyes.horiz_flicker(False)
                self.eyes.set_idle_mode(True, interval=1, variation=2)

            else:
                self.eyes.vert_flicker(False)

                if focused:
                    self.eyes.set_idle_mode(True, interval=1, variation=2)
                    # Ensure flicker is turned off when returning to focused state
                    self.eyes.horiz_flicker(False)
                    if now >= self._next_happy_check and now >= self._happy_until:
                        if random.random() < 0.45:
                            self._happy_until = now + 3.0
                        self._next_happy_check = now + random.uniform(2.0, 3.5)
                    desired_mood = HAPPY if now < self._happy_until else DEFAULT

                elif warning:
                    self.eyes.set_idle_mode(True, interval=1, variation=2)
                    if self._angry_active:
                        desired_mood = ANGRY
                        if now >= self._next_warning_burst:
                            self._warning_shake_on_until = now + 0.12
                            self._next_warning_burst = now + 0.8 + random.uniform(0.0, 0.4)
                        self.eyes.horiz_flicker(now < self._warning_shake_on_until, amplitude=2)
                    else:
                        self.eyes.horiz_flicker(False)
                        desired_mood = DEFAULT

                elif distracted:
                    self.eyes.set_idle_mode(True, interval=1, variation=2)
                    # Use _angry_active to determine angry mood, similar to warning state
                    if self._angry_active:
                        desired_mood = ANGRY
                        if now >= self._next_warning_burst:
                            self._warning_shake_on_until = now + 0.12
                            self._next_warning_burst = now + 0.8 + random.uniform(0.0, 0.4)
                        self.eyes.horiz_flicker(now < self._warning_shake_on_until, amplitude=2)
                    else:
                        self.eyes.horiz_flicker(False)
                        desired_mood = DEFAULT

                if now < self._sad_until:
                    desired_mood = TIRED

            if self.eyes.mood != desired_mood:
                self.eyes.mood = desired_mood

    # --- Thread loop ---
    def run(self):
        self.running = True
        frame_dt = 1.0 / float(self.fps)
        self.eyes.open()
        
        # Initialize timing
        self._last_display_time = time.perf_counter()
        mood_update_interval = 0.05  # Update mood 20 times per second max
        last_mood_time = 0

        while self.running:
            frame_start = time.perf_counter()
            
            # Clear buffers - only when we actually need to update
            self.master_fb.fill(0)
            self.eyes_region.fill(0)

            # Update mood less frequently to reduce CPU load
            if frame_start - last_mood_time >= mood_update_interval:
                self._apply_mood()
                last_mood_time = frame_start
            
            # Update eyes animation
            self.eyes.update()

            # Precise frame timing with minimal sleep overhead
            frame_time = time.perf_counter() - frame_start
            sleep_time = frame_dt - frame_time
            if sleep_time > 0.001:  # Only sleep if significant time left
                time.sleep(sleep_time)

    def stop(self):
        self.running = False
