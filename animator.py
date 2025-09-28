# animator.py
import math
import os
import random
import threading
import time
from enum import Enum, auto
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


class FocusMode(Enum):
    FOCUSED = auto()
    WARNING = auto()
    DISTRACTED = auto()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class EyeRenderer:
    """
    Emoji-like eyes with true closing blink and square-ish pupils.
    Mono convention:
      1 (white) = sclera/background/text
      0 (black) = pupils/eyelids/outline/eyebrows
    """

    def __init__(self, w: int, h: int,
                 font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None):
        self.w, self.h = w, h

        # Fonts
        self.font = font or ImageFont.load_default()
        self.warn_font = warn_font or self.font

        # --- Text metrics: baseline-safe reserve using ascent/descent ---
        def metrics(f):
            try:
                a, d = f.getmetrics()
                return int(a), int(d)
            except Exception:
                size = getattr(f, "size", 12)
                return int(size), 2

        a_timer, d_timer = metrics(self.font)
        a_warn, d_warn = metrics(self.warn_font)
        self.text_block_h = max(a_timer + d_timer, a_warn + d_warn)

        self.timer_margin = 4          # gap between eyes area and timer strip
        self.baseline_pad = 1          # distance from bottom edge to text baseline
        self.baseline_extra_drop = 1   # nudge baseline DOWN slightly (moves text lower)

        self.bottom_reserve = self.text_block_h + self.timer_margin + self.baseline_pad

        # --- Eye geometry (oval, spaced) ---
        self.eye_w = int(w * 0.28)
        self.eye_h = int(h * 0.46)
        self.eye_spacing = int(w * 0.12)

        avail_h = max(1, h - self.bottom_reserve)
        self.cxL = w // 2 - self.eye_w // 2 - self.eye_spacing // 2
        self.cxR = w // 2 + self.eye_w // 2 + self.eye_spacing // 2
        # Slightly below the available center so eyes aren’t too close to top
        self.cy = int(avail_h * 0.56)

        # Pupil size (square-ish) & motion constraints
        # Use near-square sizes; on small OLEDs this reads as square.
        self.pupil_rx = max(2, int(self.eye_w * 0.10))  # half-width
        self.pupil_ry = max(2, int(self.pupil_rx * 0.95))  # half-height ~square

        # Blink state
        self.lid_frac = 1.0      # 1=open .. 0=closed
        self.lid_target = 1.0
        self.next_blink_t = time.time() + random.uniform(2.5, 5.0)
        self.blinking = False
        self.blink_end_t = 0.0

        # Smooth pupil motion: target-chasing with LPF + gentle LFO + rare micro-saccade
        self._dx = 0.0
        self._dy = 0.0
        self._tx = 0.0
        self._ty = 0.0
        self._next_target_t = time.time() + random.uniform(1.2, 2.0)  # longer dwell
        self._sdx = 0.0
        self._sdy = 0.0
        self._sacc_end_t = 0.0
        self._next_sacc_t = time.time() + random.uniform(2.0, 4.0)
        self._phase = 0.0

    # ---------- geometry helpers ----------

    def _eye_rect(self, cx, cy, a, b):
        return (int(cx - a), int(cy - b), int(cx + a), int(cy + b))

    def _clamp_to_ellipse(self, cx, cy, a, b, x, y, rx, ry):
        """
        Clamp (x,y) so a pupil with radii (rx,ry) remains within ellipse (cx,cy,a,b).
        We shrink the ellipse by (rx,ry) then clamp point into it.
        """
        ax = max(1e-6, a - rx)
        by = max(1e-6, b - ry)
        nx = (x - cx) / ax
        ny = (y - cy) / by
        r2 = nx * nx + ny * ny
        if r2 <= 1.0:
            return x, y
        k = 1.0 / math.sqrt(r2)
        return cx + nx * k * ax, cy + ny * k * by

    # ---------- drawing ----------

    def _outline_ellipse(self, draw, box, width=2):
        x0, y0, x1, y1 = box
        for k in range(-width // 2, width // 2 + 1):
            draw.ellipse((x0 - k, y0 - k, x1 + k, y1 + k), outline=0, fill=None)

    def _draw_closed_lid(self, draw, cx, a):
        """Draw a thick eyelid line when the eye is fully closed."""
        y = int(self.cy)
        draw.line((int(cx - a), y, int(cx + a), y), fill=0, width=3)

    def _draw_eye(self, draw: ImageDraw.ImageDraw, cx, cy, a, b,
                  pupil_off: Tuple[float, float],
                  angry=False, raised=False, lid_frac: float = 1.0):
        """
        Draw one eye with true blink deformation:
          - When lid_frac=1: full ellipse (outline + white fill), pupil inside.
          - When lid_frac→0: vertical radius collapses; at near-zero, draw a lid line.
        """
        # Current blinked vertical radius
        b_now = max(0, int(round(b * lid_frac)))

        if b_now <= 0:
            # Fully closed: draw eyelid line only (no sclera/pupil)
            self._draw_closed_lid(draw, cx, a)
        else:
            # Outline + sclera
            box = self._eye_rect(cx, cy, a, b_now)
            self._outline_ellipse(draw, box, width=2)
            draw.ellipse(box, outline=0, fill=1)

            # Pupil (square-ish): clamp center to inside of current ellipse
            px = cx + pupil_off[0]
            py = cy + pupil_off[1]
            px, py = self._clamp_to_ellipse(cx, cy, a, b_now, px, py, self.pupil_rx, self.pupil_ry)

            # Draw as a rectangle for squarer look
            draw.rectangle((int(px - self.pupil_rx), int(py - self.pupil_ry),
                            int(px + self.pupil_rx), int(py + self.pupil_ry)), fill=0)

        # Eyebrows (only when at-risk — controlled by caller)
        if angry or raised:
            # Position brow a bit above current eye top (or above lid line)
            top_y = int(cy - b_now) if b_now > 0 else int(cy) - 2
            x0 = int(cx - a)
            x1 = int(cx + a)
            mid = (x0 + x1) // 2
            by = top_y - 3

            if angry:
                # inward slant (angry)
                draw.line((x0 + 2, by + 6, mid, by), width=2, fill=0)
                draw.line((mid, by, x1 - 2, by + 6), width=2, fill=0)
            if raised:
                # raised/flat
                draw.line((x0 + 2, by + 1, x1 - 2, by + 2), width=2, fill=0)

    # ---------- animation updates ----------

    def _update_blink(self, mode: FocusMode):
        t = time.time()
        if mode == FocusMode.FOCUSED:
            interval, dur = (2.5, 5.0), 0.18
        elif mode == FocusMode.WARNING:
            interval, dur = (1.8, 3.2), 0.22
        else:  # DISTRACTED (not tied to angry; that’s keyed by timer blink)
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
                # Strong closure at mid-blink; allow fully closed (≈0)
                closeness = 1 - abs((frac * 2) - 1)  # 0->1->0 over blink
                self.lid_target = clamp(1.0 - 1.00 * closeness, 0.0, 1.0)

        # Ease toward target (smooth open/close)
        k = 0.4
        self.lid_frac = (1 - k) * self.lid_frac + k * self.lid_target

    def _update_pupil_motion(self, cx, cy, a, b, dt):
        """
        Smooth square-ish pupil motion:
          - Random target inside ellipse every 1.2–2.0s
          - Subtle LFO
          - Tiny, rare micro-saccades
          - Low-pass to remove twitch
        """
        now = time.time()
        self._phase += dt

        # Choose new target occasionally
        if now >= self._next_target_t:
            theta = random.uniform(0, 2 * math.pi)
            r = math.sqrt(random.uniform(0.0, 1.0))  # more central bias
            tx = (a - self.pupil_rx) * r * math.cos(theta) * 0.9
            ty = (b - self.pupil_ry) * r * math.sin(theta) * 0.9
            self._tx, self._ty = tx, ty
            self._next_target_t = now + random.uniform(1.2, 2.0)

        # Tiny, brief micro-saccades
        if now >= self._next_sacc_t:
            self._sdx = random.uniform(-0.5, 0.5)
            self._sdy = random.uniform(-0.5, 0.5)
            self._sacc_end_t = now + 0.05
            self._next_sacc_t = now + random.uniform(2.0, 4.0)
        elif now >= self._sacc_end_t:
            self._sdx = 0.0
            self._sdy = 0.0

        # Gentle LFO
        lfo_x = math.sin(self._phase * 0.6) * (a - self.pupil_rx) * 0.05
        lfo_y = math.sin(self._phase * 0.9) * (b - self.pupil_ry) * 0.04

        target_x = self._tx + self._sdx + lfo_x
        target_y = self._ty + self._sdy + lfo_y

        # Low-pass filter (smoother, less twitch)
        alpha = 0.2
        self._dx = (1 - alpha) * self._dx + alpha * target_x
        self._dy = (1 - alpha) * self._dy + alpha * target_y

        # Clamp to ellipse (accounting for pupil size)
        px, py = self._clamp_to_ellipse(cx, cy, a, b, cx + self._dx, cy + self._dy,
                                        self.pupil_rx, self.pupil_ry)
        return px - cx, py - cy

    # ---------- frame render ----------

    def render(self,
               mode: FocusMode,
               canvas: Image.Image,
               timer_text: Optional[str],
               at_risk_blink_on: bool,
               dt: float):
        draw = ImageDraw.Draw(canvas)

        # Background: white; change to 0 if you want mostly-off OLED
        draw.rectangle((0, 0, self.w, self.h), fill=1)

        # Eye radii (half sizes)
        a = self.eye_w // 2
        b = self.eye_h // 2

        # Animate blink + pupils
        self._update_blink(mode)
        offL = self._update_pupil_motion(self.cxL, self.cy, a, b, dt)
        offR = self._update_pupil_motion(self.cxR, self.cy, a, b, dt)

        # Eyebrows only when the TIMER is blinking (at-risk)
        angry_left = bool(at_risk_blink_on)
        raised_right = bool(at_risk_blink_on)

        # Draw eyes
        self._draw_eye(draw, self.cxL, self.cy, a, b, offL,
                       angry=angry_left, raised=False, lid_frac=self.lid_frac)
        self._draw_eye(draw, self.cxR, self.cy, a, b, offR,
                       angry=False, raised=raised_right, lid_frac=self.lid_frac)

        # Bottom text: timer or "DISTRACTED"
        if at_risk_blink_on:
            txt = "DISTRACTED"
            f = self.warn_font
        else:
            txt = timer_text or ""
            f = self.font

        if txt:
            # Width
            if hasattr(draw, "textbbox"):
                tb = draw.textbbox((0, 0), txt, font=f)
                tw = tb[2] - tb[0]
                th = tb[3] - tb[1]
            else:
                tw = draw.textlength(txt, font=f)
                th = getattr(f, "size", 12)

            # Baseline placement (downward nudge away from camera view)
            try:
                ascent, descent = f.getmetrics()
            except Exception:
                ascent, descent = getattr(f, "size", 12), 2

            x = (self.w - int(tw)) // 2
            baseline_y = self.h - descent - self.baseline_pad + self.baseline_extra_drop
            y = int(baseline_y - ascent)

            # If it would clip, lift it just enough
            if y + th > self.h:
                y = self.h - th
            if y < 0:
                y = 0

            draw.text((x, y), txt, fill=0, font=f)


class EyeAnimator(threading.Thread):
    """
    Animator thread:
      - Receives state + timer updates from FocusTimerThread.
      - Renders at ~fps and pushes frames to the OLED via display_image(img).
    oled_display must expose: .width, .height, .display_image(PIL.Image)
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

        # Timer 26 px by default
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

            img = Image.new('1', (self.oled.width, self.oled.height), 1)
            self.eye.render(mode, img, timer_text, blink_on, dt)

            try:
                self.oled.display_image(img)
            except Exception:
                pass

            time.sleep(max(0.0, ft - (time.time() - t0)))

    def stop(self):
        self.running = False
