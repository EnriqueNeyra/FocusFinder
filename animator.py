# animator.py
import math
import os
import random
import threading
import time
from enum import Enum, auto
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


class FocusMode(Enum):
    FOCUSED = auto()
    WARNING = auto()
    DISTRACTED = auto()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class EyeRenderer:
    """
    Renders emoji-like eyes + optional timer onto a PIL '1' canvas.

    Notes on color:
      - We use "white" (1) for eye sclera and "black" (0) for pupils & eyelids.
      - If your OLED polarity is reversed, swap the fills (0 <-> 1).
    """

    def __init__(self, w: int, h: int, font: Optional[ImageFont.ImageFont] = None):
        self.w, self.h = w, h

        # --- Determine timer text height to reserve space at bottom ---
        self.font = font or ImageFont.load_default()
        if hasattr(self.font, "getbbox"):
            bbox = self.font.getbbox("00:00")
            self.timer_h = (bbox[3] - bbox[1]) or getattr(self.font, "size", 12)
        else:
            self.timer_h = getattr(self.font, "size", 12)
        self.timer_margin = 3  # pixels between eyes area and timer
        self.bottom_reserve = self.timer_h + self.timer_margin

        # === Geometry: smaller & oval (emoji-like), with a touch more spacing ===
        self.eye_w = int(w * 0.28)    # narrower than before
        self.eye_h = int(h * 0.46)    # shorter -> oval
        self.eye_spacing = int(w * 0.12)

        # Center eyes in the AVAILABLE area (exclude timer strip at bottom)
        avail_h = max(1, h - self.bottom_reserve)
        self.cxL = w // 2 - self.eye_w // 2 - self.eye_spacing // 2
        self.cxR = w // 2 + self.eye_w // 2 + self.eye_spacing // 2
        self.cy = (avail_h // 2) - 2  # nudge up slightly for aesthetics

        # Pupil sizing & limits within eye
        self.pupil_rx = max(2, int(self.eye_w * 0.10))
        self.pupil_ry = max(2, int(self.eye_h * 0.14))
        self.pupil_lim_x = int(self.eye_w * 0.25)
        self.pupil_lim_y = int(self.eye_h * 0.20)

        # Eyelids open fraction (1=open, 0=closed)
        self.lid_frac = 1.0
        self.lid_target = 1.0
        self.next_blink_t = time.time() + random.uniform(2.5, 5.0)
        self.blinking = False
        self.blink_end_t = 0.0

        # Autonomous pupil motion (time + micro-saccades)
        self.t = 0.0
        self.sdx = 0.0
        self.sdy = 0.0
        self.next_sacc_t = time.time() + random.uniform(2.0, 4.0)
        self.sacc_end_t = 0.0
        self._dx = 0.0  # filtered offsets
        self._dy = 0.0

    def _eye_rect(self, cx, cy):
        return (cx - self.eye_w // 2, cy - self.eye_h // 2,
                cx + self.eye_w // 2, cy + self.eye_h // 2)

    def _draw_eye(self, draw: ImageDraw.ImageDraw, cx, cy, off, angry=False, skeptical=False):
        x0, y0, x1, y1 = self._eye_rect(cx, cy)

        # Thicker outline to sell the emoji look (poor-man's 3px outline)
        for k in (-1, 0, 1):
            draw.ellipse((x0 - k, y0 - k, x1 + k, y1 + k), outline=0, fill=None)

        # White sclera
        draw.ellipse((x0, y0, x1, y1), outline=0, fill=1)

        # Pupil (black)
        px = clamp(cx + off[0], x0 + self.pupil_rx, x1 - self.pupil_rx)
        py = clamp(cy + off[1], y0 + self.pupil_ry, y1 - self.pupil_ry)
        draw.ellipse((px - self.pupil_rx, py - self.pupil_ry,
                      px + self.pupil_rx, py + self.pupil_ry), fill=0)

        # Eyelids: use black (0) so they actually cover/close the eye
        if self.lid_frac < 1.0:
            open_h = int(self.eye_h * self.lid_frac)
            lid_top = (self.eye_h - open_h) // 2
            lid_bot = self.eye_h - open_h - lid_top
            # Top lid
            draw.rectangle((x0, y0, x1, y0 + lid_top), fill=0)
            # Bottom lid
            draw.rectangle((x0, y1 - lid_bot, x1, y1), fill=0)

        # Brows for emotion
        if angry:
            by = y0 - 2
            draw.line((x0 + 2, by + 6, x0 + self.eye_w // 2, by), width=2, fill=0)
            draw.line((x0 + self.eye_w // 2, by, x1 - 2, by + 6), width=2, fill=0)
        elif skeptical:
            byL = y0 + 4
            byR = y0 - 2
            if cx < self.w // 2:
                draw.line((x0 + 2, byL, x1 - 2, byL), width=2, fill=0)
            else:
                draw.line((x0 + 2, byR, x1 - 2, byR), width=2, fill=0)

    def _update_blink(self, mode):
        t = time.time()
        if mode == FocusMode.FOCUSED:
            interval, dur = (2.5, 5.0), 0.18
        elif mode == FocusMode.WARNING:
            interval, dur = (1.8, 3.2), 0.22
        else:  # DISTRACTED
            interval, dur = (2.0, 3.0), 0.12

        if not self.blinking and t >= self.next_blink_t:
            self.blinking = True
            self.blink_end_t = t + dur

        if self.blinking:
            frac = (self.blink_end_t - t) / dur
            if frac <= 0:
                self.blinking = False
                self.next_blink_t = time.time() + random.uniform(*interval)
                self.lid_target = 1.0
            else:
                # Close more aggressively so it's clearly visible
                closeness = 1 - abs((frac * 2) - 1)  # 0->1->0 over blink duration
                self.lid_target = clamp(1.0 - 0.95 * closeness, 0.05, 1.0)

        # Ease lid toward target
        k = 0.35
        self.lid_frac = (1 - k) * self.lid_frac + k * self.lid_target

    def _update_autonomous_motion(self, mode: FocusMode, dt: float):
        """
        Subtle, smooth wander (emoji-like), rare tiny saccades, and light shake when not focused.
        Uses float math + LPF; we round only at draw time.
        """
        self.t += dt

        # Smooth LFOs: small amplitudes for subtle movement
        lfo_x = math.sin(self.t * 0.7) * self.pupil_lim_x * 0.12
        lfo_y = math.sin(self.t * 1.0) * self.pupil_lim_y * 0.10

        # Tiny, rare micro-saccades
        now = time.time()
        if now >= self.next_sacc_t:
            self.sdx = random.randint(-1, 1)
            self.sdy = random.randint(-1, 1)
            self.sacc_end_t = now + 0.05
            self.next_sacc_t = now + random.uniform(2.0, 4.0)
        elif now >= self.sacc_end_t:
            self.sdx = 0.0
            self.sdy = 0.0

        # Mode-based shakes + eyelid targets
        if mode == FocusMode.FOCUSED:
            shake_x = shake_y = 0.0
            self.lid_target = max(self.lid_target, 0.95)
        elif mode == FocusMode.WARNING:
            amp = 0.6
            shake_x = math.sin(self.t * 6.0) * amp
            shake_y = math.cos(self.t * 6.0) * amp
            self.lid_target = min(self.lid_target, 0.75)
        else:
            amp = 1.2
            shake_x = math.sin(self.t * 10.0) * amp
            shake_y = math.cos(self.t * 10.0) * amp
            self.lid_target = min(self.lid_target, 0.55)

        target_x = lfo_x + self.sdx + shake_x
        target_y = lfo_y + self.sdy + shake_y

        # Low-pass filter for smoothness
        alpha = 0.35  # lower => smoother
        self._dx = (1.0 - alpha) * self._dx + alpha * target_x
        self._dy = (1.0 - alpha) * self._dy + alpha * target_y

        return self._dx, self._dy

    def render(self,
               mode: FocusMode,
               canvas: Image.Image,
               timer_text: Optional[str],
               timer_blink_on: bool,
               dt: float):
        draw = ImageDraw.Draw(canvas)

        # Background: white full frame (consistent with prior look).
        draw.rectangle((0, 0, self.w, self.h), fill=1)

        # Update eyelids & motion
        self._update_blink(mode)
        dx_f, dy_f = self._update_autonomous_motion(mode, dt)
        dx, dy = int(round(dx_f)), int(round(dy_f))

        # Draw eyes (already positioned above the reserved timer strip)
        self._draw_eye(draw, self.cxL, self.cy, (dx, dy),
                       angry=(mode == FocusMode.DISTRACTED),
                       skeptical=(mode == FocusMode.WARNING))
        self._draw_eye(draw, self.cxR, self.cy, (dx, dy),
                       angry=(mode == FocusMode.DISTRACTED),
                       skeptical=(mode == FocusMode.WARNING))

        # Timer text (hidden when blink_on=True)
        if timer_text and not timer_blink_on:
            f = self.font
            if hasattr(f, "getbbox"):
                bbox = f.getbbox(timer_text)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            else:
                tw = draw.textlength(timer_text, font=f)
                th = getattr(f, "size", 12)
            x = (self.w - int(tw)) // 2
            y = self.h - int(th) - 1  # sit just above the bottom edge
            draw.text((x, y), timer_text, fill=0, font=f)


class EyeAnimator(threading.Thread):
    """
    Runs in its own thread:
      - Renders eyes + timer at ~N FPS.
      - Receives state/timer updates from FocusTimerThread via setters.
      - Calls oled.display_image(img) each frame.

    Expectation: oled has .width, .height, and .display_image(PIL.Image).
    """

    def __init__(self, oled_display, fps: int = 20, timer_font: Optional[ImageFont.ImageFont] = None):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = fps
        self.mode = FocusMode.FOCUSED
        self.timer_text = None
        self.timer_blink_on = False
        self.running = False

        # Timer font = 26 px as requested
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 26)
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font

        self.eye = EyeRenderer(self.oled.width, self.oled.height, font=self.timer_font)
        self._lock = threading.Lock()

    # External API
    def set_state(self, focused: bool, warning: bool = False):
        with self._lock:
            if focused:
                self.mode = FocusMode.FOCUSED
            elif warning:
                self.mode = FocusMode.WARNING
            else:
                self.mode = FocusMode.DISTRACTED

    def set_timer(self, text: str, blink_on: bool):
        with self._lock:
            self.timer_text = text
            self.timer_blink_on = blink_on

    # Thread loop
    def run(self):
        self.running = True
        ft = 1.0 / float(self.fps)
        last = time.time()

        while self.running:
            t0 = time.time()
            dt = t0 - last
            last = t0

            with self._lock:
                mode = self.mode
                timer_text = self.timer_text
                blink_on = self.timer_blink_on

            img = Image.new('1', (self.oled.width, self.oled.height), 1)
            self.eye.render(mode, img, timer_text, blink_on, dt)

            try:
                self.oled.display_image(img)
            except Exception:
                # Avoid crashing the animator on transient I/O errors
                pass

            elapsed = time.time() - t0
            time.sleep(max(0.0, ft - elapsed))

    def stop(self):
        self.running = False
