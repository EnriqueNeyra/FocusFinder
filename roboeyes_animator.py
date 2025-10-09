# roboeyes_animator.py
import os
import threading
import time
import random
from typing import Optional
from PIL import ImageDraw, ImageFont

import mp_time_shim  # patches time.ticks_* for the MicroPython-style timing

from roboeyes import RoboEyes, DEFAULT, ANGRY, HAPPY, TIRED, CURIOUS
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
      - Blinks less frequent overall (≈ every 6-14 s).
      - Eyes fill the entire top half; timer (size 25) sits at the top of the lower half.
    """
    
    # Configuration constants
    EYES_HEIGHT_RATIO = 0.6  # 60% of screen for eyes
    STARTUP_DURATION = 2.5
    SAD_DURATION = 3.0
    HAPPY_DURATION = 3.0
    HAPPY_PROBABILITY = 0.45
    AT_RISK_TIMEOUT = 3.0
    FLICKER_DURATION = 0.25
    FLICKER_INTERVAL_BASE = 0.6
    MOOD_UPDATE_INTERVAL = 0.05  # 20 times per second max
    
    # Eye dimension constants
    DEFAULT_EYE_W, DEFAULT_EYE_H, DEFAULT_EYE_R, DEFAULT_EYE_SPACE = 20, 18, 5, 4
    MIN_EYE_W, MIN_EYE_H, MIN_SPACE = 20, 16, 4
    SCALED_MIN_EYE_W, SCALED_MIN_EYE_H, SCALED_MIN_SPACE = 16, 14, 4
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
        
        # State tracking for optimizations
        self._last_timer_state = None
        self._last_mood_state = None
        self._last_display_time = 0

        # Timed behaviors
        now = time.perf_counter()
        self._startup_until = now + self.STARTUP_DURATION
        self._seen_first_timer = False
        self._happy_until = 0.0
        self._next_happy_check = now + random.uniform(2.0, 3.5)
        self._sad_until = 0.0
        self._warning_shake_on_until = 0.0
        self._next_warning_burst = now + 0.9

        # At-risk period state
        self._at_risk_period = False
        self._last_blink_time = 0.0

        # Fonts
        self.timer_font = self._load_font(timer_font, 25)
        self.warn_font = self._load_font(warn_font, 14)

        # Master framebuffer
        W, H = self.oled.width, self.oled.height
        self.master_fb = PILFrameBuffer(W, H)

        # Eyes region calculation
        eyes_area_height = int(H * self.EYES_HEIGHT_RATIO)
        timer_area_y = eyes_area_height
        eyes_x, eyes_y = margin_x, margin_top
        eyes_w = W - 2 * margin_x
        eyes_h = eyes_area_height - eyes_y - gap_mid

        # Apply minimum size constraints
        min_region_w = 2 * self.MIN_EYE_W + self.MIN_SPACE + 2
        min_region_h = max(self.MIN_EYE_H + 4, 24)
        eyes_w = max(min(eyes_w, W - eyes_x), min_region_w)
        eyes_h = max(min(eyes_h, eyes_area_height - eyes_y), min_region_h)

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

            # Timer area starts at 60% of screen height
            d.rectangle((0, timer_area_y, W - 1, H - 1), fill=1)

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
                tw = self._get_text_width(d, txt, fnt)
                y = timer_area_y - 2
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

        # Configure eye dimensions with scaling if needed
        eye_w, eye_h, eye_space = self._calculate_eye_dimensions()
        self.eyes.eyes_width(eye_w, eye_w)
        self.eyes.eyes_height(eye_h, eye_h)
        self.eyes.eyes_radius(self.DEFAULT_EYE_R, self.DEFAULT_EYE_R)
        self.eyes.eyes_spacing(eye_space)

        self.eyes.set_auto_blinker(True, interval=6, variation=8)
        self.eyes.set_idle_mode(True, interval=1, variation=2)

        self._apply_mood(initial=True)

    # --- External API ---
    def set_state(self, focused: bool, warning: bool = False):
        with self._lock:
            if focused:
                self.mode = FocusMode.FOCUSED
                # Clear at-risk state only when becoming focused
                self._at_risk_period = False
                self._warning_shake_on_until = 0.0
                self.eyes.horiz_flicker(False)
            elif warning:
                self.mode = FocusMode.WARNING
                # Do NOT clear at-risk state - WARNING mode is used during at-risk periods
            else:
                self.mode = FocusMode.DISTRACTED
                # Do NOT clear at-risk state - DISTRACTED mode is used during at-risk periods
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

            # Update at-risk state and timer display
            self._update_at_risk_state(blink_on, text, prev)
            self.timer_blink_on = blink_on

            if not self._seen_first_timer:
                self._seen_first_timer = True
            elif (self.timer_text == "00:00" and self.prev_timer_text != "00:00" and 
                  self.mode in (FocusMode.DISTRACTED, FocusMode.WARNING)):
                self._sad_until = time.perf_counter() + self.SAD_DURATION

        self._apply_mood()

    # --- Mood / animation logic ---
    def _apply_mood(self, initial: bool = False):
        with self._lock:
            now = time.perf_counter()
            focused = (self.mode == FocusMode.FOCUSED)
            warning = (self.mode == FocusMode.WARNING)
            distracted = (self.mode == FocusMode.DISTRACTED)

            # Create state tuple for efficient comparison
            current_mood_state = (focused, warning, distracted, self._at_risk_period,
                                now < self._startup_until, now < self._happy_until, now < self._sad_until,
                                int(now * 5))  # 200ms update frequency
            
            # Skip update only if nothing has changed AND we're not in at-risk period
            if not initial and current_mood_state == self._last_mood_state and not self._at_risk_period:
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
                        if random.random() < self.HAPPY_PROBABILITY:
                            self._happy_until = now + self.HAPPY_DURATION
                        self._next_happy_check = now + random.uniform(2.0, 3.5)
                    desired_mood = HAPPY if now < self._happy_until else DEFAULT

                elif warning or distracted:
                    if self._at_risk_period:
                        desired_mood = ANGRY
                        self._apply_angry_flicker(now)
                        self.eyes.set_idle_mode(True, interval=1, variation=2)
                    else:
                        self.eyes.horiz_flicker(False)
                        if warning:
                            desired_mood = DEFAULT
                            self.eyes.set_idle_mode(True, interval=1, variation=2)
                        else:  # distracted
                            desired_mood = CURIOUS
                            self.eyes.set_idle_mode(True, interval=1, variation=1)

                # Override mood if in sad state, but ensure clean transition afterward
                if now < self._sad_until:
                    desired_mood = TIRED
                elif now >= self._sad_until and self._sad_until > 0.0:
                    # Just finished being sad - clear any lingering at-risk state
                    if self._at_risk_period and not self.timer_blink_on:
                        # Only clear if we're not actively blinking
                        current_time = time.perf_counter()
                        if current_time - self._last_blink_time > 1.0:  # 1 second grace period
                            self._at_risk_period = False
                            self._warning_shake_on_until = 0.0

            if self.eyes.mood != desired_mood:
                self.eyes.mood = desired_mood

    # --- Thread loop ---
    def run(self):
        self.running = True
        frame_dt = 1.0 / self.fps
        self.eyes.open()
        
        self._last_display_time = time.perf_counter()
        last_mood_time = 0

        while self.running:
            frame_start = time.perf_counter()
            
            # Clear buffers
            self.master_fb.fill(0)
            self.eyes_region.fill(0)

            # Update mood at reduced frequency
            if frame_start - last_mood_time >= self.MOOD_UPDATE_INTERVAL:
                self._apply_mood()
                last_mood_time = frame_start
            
            self.eyes.update()

            # Frame timing
            sleep_time = frame_dt - (time.perf_counter() - frame_start)
            if sleep_time > 0.001:
                time.sleep(sleep_time)

    def stop(self):
        self.running = False
    
    # --- Helper methods ---
    def _load_font(self, font: Optional[ImageFont.ImageFont], size: int) -> ImageFont.ImageFont:
        """Load a font with fallback to default."""
        if font is not None:
            return font
        try:
            font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
            return ImageFont.truetype(font_path, size)
        except Exception:
            return ImageFont.load_default()
    
    def _get_text_width(self, draw: ImageDraw.Draw, text: str, font: ImageFont.ImageFont) -> int:
        """Calculate text width using the most appropriate method."""
        if hasattr(draw, "textbbox"):
            tb = draw.textbbox((0, 0), text, font=font)
            return tb[2] - tb[0]
        return int(draw.textlength(text, font=font))
    
    def _calculate_eye_dimensions(self) -> tuple[int, int, int]:
        """Calculate eye dimensions with scaling if needed."""
        total_min_w = 2 * self.DEFAULT_EYE_W + self.DEFAULT_EYE_SPACE
        if self.eyes_region.width >= total_min_w:
            return self.DEFAULT_EYE_W, self.DEFAULT_EYE_H, self.DEFAULT_EYE_SPACE
        
        scale = self.eyes_region.width / total_min_w
        return (
            max(self.SCALED_MIN_EYE_W, int(self.DEFAULT_EYE_W * scale)),
            max(self.SCALED_MIN_EYE_H, int(self.DEFAULT_EYE_H * scale)),
            max(self.SCALED_MIN_SPACE, int(self.DEFAULT_EYE_SPACE * scale))
        )
    
    def _update_at_risk_state(self, blink_on: bool, text: str, prev_text: str):
        """Update at-risk period state based on blinking and timer changes."""
        now_time = time.perf_counter()
        
        # Once we start blinking, we're at risk until timer resets or we switch modes
        if blink_on:
            self._at_risk_period = True
            self._last_blink_time = now_time
        
        # Timer reset to 00:00 - completely clear at-risk state and flicker
        if text == "00:00" and prev_text != "00:00":
            self._at_risk_period = False
            self._warning_shake_on_until = 0.0
            self._next_warning_burst = now_time + 0.9
    
    def _apply_angry_flicker(self, now: float):
        """Apply angry flicker animation during at-risk periods."""
        if self._at_risk_period:
            if now >= self._next_warning_burst:
                self._warning_shake_on_until = now + self.FLICKER_DURATION
                self._next_warning_burst = now + self.FLICKER_INTERVAL_BASE + random.uniform(0.0, 0.3)
            self.eyes.horiz_flicker(now < self._warning_shake_on_until, amplitude=2)
        else:
            # Ensure flicker is turned off when not at risk
            self.eyes.horiz_flicker(False)
            self._warning_shake_on_until = 0.0
