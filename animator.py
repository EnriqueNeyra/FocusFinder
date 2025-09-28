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

    Color convention for mono:
      - White (1): sclera, background, text
      - Black (0): pupils, eyelids, outlines
    """

    def __init__(self, w: int, h: int, font: Optional[ImageFont.ImageFont] = None, warn_font: Optional[ImageFont.ImageFont] = None):
        self.w, self.h = w, h

        # Fonts
        self.font = font or ImageFont.load_default()
        self.warn_font = warn_font or self.font

        # --- Reserve a bottom strip tall enough for either "00:00" or "DISTRACTED" ---
        def text_size(fnt, txt):
            if hasattr(fnt, "getbbox"):
                b = fnt.getbbox(txt)
                return (b[2] - b[0], b[3] - b[1])
            return (0, getattr(fnt, "size", 12))  # fallback height

        _, timer_h = text_size(self.font, "00:00")
        _, warn_h = text_size(self.warn_font, "DISTRACTED")
        self.timer_margin = 4             # gap between eyes area and timer strip
        self.baseline_pad = 3             # pixels above bottom edge for baseline safety
        self.bottom_reserve = max(timer_h, warn_h) + self.timer_margin + self.baseline_pad

        # === Eye geometry: emoji-oval with comfortable spacing ===
        self.eye_w = int(w * 0.28)
        self.eye_h = int(h * 0.46)
        self.eye_spacing = int(w * 0.12)

        # Place eyes in the AVAILABLE area (excluding the reserved bottom strip)
        avail_h = max(1, h - self.bottom_reserve)
        self.cxL = w // 2 - self.eye_w // 2 - self.eye_spacing // 2
        self.cxR = w // 2 + self.eye_w // 2 + self.eye_spacing // 2
        # Slightly below the vertical center of the available area so they aren't too close to the top
        self.cy = int(avail_h * 0.58)

        # Pupil size + travel limits
        self.pupil_rx = max(2, int(self.eye_w * 0.10))
        self.pupil_ry = max(2, int(self.eye_h * 0.14))
        self.pupil_lim_x = int(self.eye_w * 0.25)
        self.pupil_lim_y = int(self.eye_h * 0.20)

        # Eyelids / blinking
        self.lid_frac = 1.0
        self.lid_target = 1.0
        self.next_blink_t = time.time() + random.uniform(2.5, 5.0)
        self.blinking = False
        self.blink_end_t = 0.0

        # Autonomous motion (subtle)
        self.t = 0.0
        self.sdx = 0.0
        self.sdy = 0.0
        self.next_sacc_t = time.time() + random.uniform(2.0, 4.0)
        self.sacc_end_t = 0.0
        self._dx = 0.0
        self._dy = 0.0

    def _eye_rect(self, cx, cy):
        return (cx - self.eye_w // 2, cy - self.eye_h // 2,
                cx + self.eye_w // 2, cy + self.eye_h // 2)

    def _draw_eye(self, draw: ImageDraw.ImageDraw, cx, cy, off, angry=False, skeptical=False):
        x0, y0, x1, y1 = self._eye_rect(cx, cy)

        # 3px(ish) outline for emoji look
        for k in (-1, 0, 1):
            draw.ellipse((x0 - k, y0 - k, x1 + k, y1 + k), outline=0, fill=None)

        # Sclera
        draw.ellipse((x0, y0, x1, y1), outline=0, fill=1)

        # Pupil
        px = clamp(cx + off[0], x0 + self.pupil_rx, x1 - self.pupil_rx)
        py = clamp(cy + off[1], y0 + self.pupil_ry, y1 - self.pupil_ry)
        draw.ellipse((px - self.pupil_rx, py - self.pupil_ry,
                      px + self.pupil_rx, py + self.pupil_ry), fill=0)

        # Eyelids (black to actually cover)
        if self.lid_frac < 1.0:
            open_h = int(self.eye_h * self.lid_frac)
            lid_top = (self.eye_h - open_h) // 2
            lid_bot = self.eye_h - open_h - lid_top
            draw.rectangle((x0, y0, x1, y0 + lid_top), fill=0)      # top
            draw.rectangle((x0, y1 - lid_bot, x1, y1), fill=0)      # bottom

        # Brows
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
        else:  # DISTRACTED (note: angry is now tied to blink flag, not this mode directly)
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
                closeness = 1 - abs((frac * 2) - 1)  # 0->1->0
                self.lid_target = clamp(1.0 - 0.95 * closeness, 0.05, 1.0)

        # Ease lid toward target
        k = 0.35
        self.lid_frac = (1 - k) * self.lid_frac + k * self.lid_target

    def _update_autonomous_motion(self, mode: FocusMode, dt: float):
        # Subtle movement
        self.t += dt
        lfo_x = math.sin(self.t * 0.7) * self.pupil_lim_x * 0.12
        lfo_y = math.sin(self.t * 1.0) * self.pupil_lim_y * 0.10

        now = time.time()
        if now >= self.next_sacc_t:
            self.sdx = random.randint(-1, 1)
            self.sdy = random.randint(-1, 1)
            self.sacc_end_t = now + 0.05
            self.next_sacc_t = now + random.uniform(2.0, 4.0)
        elif now >= self.sacc_end_t:
            self.sdx = 0.0
            self.sdy = 0.0

        # Light shake for warning/distracted
        if mode == FocusMode.FOCUSED:
            shake_x = shake_y = 0.0
            self.lid_target = max(self.lid_target, 0.95)
        elif mode == FocusMode.WARNING:
            amp = 0.6
            shake_x = math.sin(self.t * 6.0) * amp
            shake_y = math.cos(self.t * 6.0) * amp
            self.lid_target = min(self.lid_target, 0.75)
        else:
            amp = 1.0  # toned down; "angry" now keyed by blink, not mode
            shake_x = math.sin(self.t * 10.0) * amp
            shake_y = math.cos(self.t * 10.0) * amp
            self.lid_target = min(self.lid_target, 0.60)

        target_x = lfo_x + self.sdx + shake_x
        target_y = lfo_y + self.sdy + shake_y

        # LPF for smoothness
        alpha = 0.35
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

        # Full white background (consistent look). For darker background, set fill=0.
        draw.rectangle((0, 0, self.w, self.h), fill=1)

        # Updates
        self._update_blink(mode)
        dx_f, dy_f = self._update_autonomous_motion(mode, dt)
        dx, dy = int(round(dx_f)), int(round(dy_f))

        # Angry eyes ONLY when timer is blinking (user at-risk)
        angry_now = bool(timer_blink_on)
        skeptical_now = (mode == FocusMode.WARNING) and not angry_now

        # Eyes (placed within available area above the timer strip)
        self._draw_eye(draw, self.cxL, self.cy, (dx, dy),
                       angry=angry_now,
                       skeptical=skeptical_now)
        self._draw_eye(draw, self.cxR, self.cy, (dx, dy),
                       angry=angry_now,
                       skeptical=skeptical_now)

        # --- Timer / Warning strip at bottom ---
        # Compute a safe baseline above bottom edge
        # We'll center text horizontally in the full width
        if timer_blink_on:
            # Show "DISTRACTED" when timer is blinking off
            txt = "DISTRACTED"
            f = self.warn_font
        else:
            txt = timer_text or ""
            f = self.font

        if txt:
            if hasattr(f, "getbbox"):
                bbox = f.getbbox(txt)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            else:
                tw = draw.textlength(txt, font=f)
                th = getattr(f, "size", 12)

            x = (self.w - int(tw)) // 2
            y = self.h - int(th) - self.baseline_pad  # ensure not clipped
            draw.text((x, y), txt, fill=0, font=f)


class EyeAnimator(threading.Thread):
    """
    Renders eyes + timer at ~N FPS on a separate thread.
    Expectation: 'oled_display' exposes .width, .height, .display_image(PIL.Image).
    """

    def __init__(self, oled_display, fps: int = 20,
                 timer_font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = fps
        self.mode = FocusMode.FOCUSED
        self.timer_text = None
        self.timer_blink_on = False
        self.running = False

        # Timer font at 26 px (as requested); warn font can be the same or bold if you have one.
        if timer_font is None:
            try:
                font_path = os.path.join("./lib/waveshare_OLED", "Font.ttc")
                self.timer_font = ImageFont.truetype(font_path, 26)
            except Exception:
                self.timer_font = ImageFont.load_default()
        else:
            self.timer_font = timer_font

        self.warn_font = warn_font or self.timer_font

        self.eye = EyeRenderer(self.oled.width, self.oled.height,
                               font=self.timer_font, warn_font=self.warn_font)
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

            # Create frame (white background for now)
            img = Image.new('1', (self.oled.width, self.oled.height), 1)
            EyeRenderer.render(self.eye, mode, img, timer_text, blink_on, dt)

            try:
                self.oled.display_image(img)
            except Exception:
                # Avoid crashing on transient I/O errors
                pass

            elapsed = time.time() - t0
            time.sleep(max(0.0, ft - elapsed))

    def stop(self):
        self.running = False
