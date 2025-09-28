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


def lerp(a, b, t):
    return a + (b - a) * t


class EyeRenderer:
    """
    Emoji-like 👀 eyes + timer strip at the bottom.
    - True blink: eye ellipse collapses vertically (outline closes).
    - Pupils move smoothly within the eye ellipse interior.
    - Eyebrows appear only when timer is blinking (at-risk).
    Mono color convention:
      - 1 (white): sclera, background, text
      - 0 (black): pupils, eyelids/outline, eyebrows
    """

    def __init__(self, w: int, h: int,
                 font: Optional[ImageFont.ImageFont] = None,
                 warn_font: Optional[ImageFont.ImageFont] = None):
        self.w, self.h = w, h

        # --- Fonts ---
        self.font = font or ImageFont.load_default()
        self.warn_font = warn_font or self.font

        # Use ascent/descent so text baseline never clips
        def get_metrics(fnt) -> Tuple[int, int]:
            try:
                a, d = fnt.getmetrics()
                return int(a), int(d)
            except Exception:
                size = getattr(fnt, "size", 12)
                return int(size), 2

        a_timer, d_timer = get_metrics(self.font)
        a_warn, d_warn = get_metrics(self.warn_font)

        self.baseline_pad = 2
        self.timer_margin = 4
        self.text_block_h = max(a_timer + d_timer, a_warn + d_warn)
        self.bottom_reserve = self.text_block_h + self.baseline_pad + self.timer_margin

        # --- Eye geometry (emoji-oval) ---
        self.eye_w = int(w * 0.28)
        self.eye_h = int(h * 0.46)
        self.eye_spacing = int(w * 0.12)

        avail_h = max(1, h - self.bottom_reserve)
        self.cxL = w // 2 - self.eye_w // 2 - self.eye_spacing // 2
        self.cxR = w // 2 + self.eye_w // 2 + self.eye_spacing // 2
        self.cy = int(avail_h * 0.56)  # balanced vertical position

        # Pupil size & travel limits
        self.pupil_rx = max(2, int(self.eye_w * 0.10))
        self.pupil_ry = max(2, int(self.eye_h * 0.14))

        # Eyelid/blink state
        self.lid_frac = 1.0     # 1=open .. 0=closed
        self.lid_target = 1.0
        self.next_blink_t = time.time() + random.uniform(2.5, 5.0)
        self.blinking = False
        self.blink_end_t = 0.0

        # Pupil motion: smooth target-chasing with LPF
        self._dx = 0.0
        self._dy = 0.0
        self._tx = 0.0
        self._ty = 0.0
        self._t_next = time.time() + random.uniform(0.8, 1.6)

        # Small micro-saccades
        self._sdx = 0.0
        self._sdy = 0.0
        self._sacc_end_t = 0.0
        self._next_sacc_t = time.time() + random.uniform(2.0, 4.0)

        # Phase accumulator
        self.t = 0.0

    # ----------------- helpers -----------------

    def _eye_rect(self, cx, cy, a, b):
        """Return bounding box of ellipse centered at (cx,cy) with radii (a,b)."""
        return (int(cx - a), int(cy - b), int(cx + a), int(cy + b))

    def _ellipse_contains(self, cx, cy, a, b, x, y, rx, ry):
        """
        Check if a pupil centered at (x,y) with radii (rx,ry) fits fully
        inside the eye ellipse centered at (cx,cy) with radii (a,b).
        """
        # Effective available radii after accounting for pupil size
        ax = max(1e-6, a - rx)
        by = max(1e-6, b - ry)
        nx = (x - cx) / ax
        ny = (y - cy) / by
        return (nx * nx + ny * ny) <= 1.0

    def _clamp_to_ellipse(self, cx, cy, a, b, x, y, rx, ry):
        """Clamp (x,y) so the pupil fits inside the ellipse."""
        ax = max(1e-6, a - rx)
        by = max(1e-6, b - ry)
        nx = (x - cx) / ax
        ny = (y - cy) / by
        r2 = nx * nx + ny * ny
        if r2 <= 1.0:
            return x, y
        k = 1.0 / math.sqrt(r2)
        nx *= k
        ny *= k
        return cx + nx * ax, cy + ny * by

    # ----------------- drawing -----------------

    def _draw_ellipse_outline(self, draw, box, width=2):
        """Thicker outline by overdraw (cheap, looks crisp on mono)."""
        x0, y0, x1, y1 = box
        for k in range(-width // 2, width // 2 + 1):
            draw.ellipse((x0 - k, y0 - k, x1 + k, y1 + k), outline=0, fill=None)

    def _draw_eye(self, draw: ImageDraw.ImageDraw, cx, cy, a, b,
                  pupil_off: Tuple[float, float], angry=False, raised=False,
                  lid_frac: float = 1.0):
        """
        Draw one eye:
          - base ellipse (outline + sclera)
          - pupil inside ellipse
          - blink: ellipse vertically collapsed by lid_frac
          - eyebrows when angry/raised
        """
        # --- Blink deformation: collapse vertical radius by lid_frac ---
        b_now = max(1, int(round(b * lid_frac)))
        # Outline closes because we draw a new ellipse at reduced height
        box = self._eye_rect(cx, cy, a, b_now)
        self._draw_ellipse_outline(draw, box, width=2)
        draw.ellipse(box, outline=0, fill=1)  # sclera

        # --- Pupil position (clamped to ellipse interior) ---
        px = cx + pupil_off[0]
        py = cy + pupil_off[1]
        px, py = self._clamp_to_ellipse(cx, cy, a, b_now, px, py, self.pupil_rx, self.pupil_ry)
        draw.ellipse((int(px - self.pupil_rx), int(py - self.pupil_ry),
                      int(px + self.pupil_rx), int(py + self.pupil_ry)), fill=0)

        # --- Eyebrows (only when at-risk) ---
        if angry or raised:
            # eyebrow baseline slightly above top of current ellipse
            by = box[1] - 3
            x0, y0, x1, y1 = box
            mid = (x0 + x1) // 2

            # "mad" (inward slant) on one eye, "raised/flat" on the other
            if angry:
                # inward slant
                draw.line((x0 + 2, by + 6, mid, by), width=2, fill=0)
                draw.line((mid, by, x1 - 2, by + 6), width=2, fill=0)
            if raised:
                # gentle raised/flat brow
                draw.line((x0 + 2, by + 2, x1 - 2, by + 1), width=2, fill=0)

    # ----------------- animation states -----------------

    def _update_blink(self, mode: FocusMode):
        t = time.time()
        if mode == FocusMode.FOCUSED:
            interval, dur = (2.5, 5.0), 0.18
        elif mode == FocusMode.WARNING:
            interval, dur = (1.8, 3.2), 0.22
        else:
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
                # Close strongly near mid-blink
                closeness = 1 - abs((frac * 2) - 1)  # 0->1->0
                self.lid_target = clamp(1.0 - 0.95 * closeness, 0.05, 1.0)

        # ease toward target
        k = 0.35
        self.lid_frac = (1 - k) * self.lid_frac + k * self.lid_target

    def _update_pupil_targets(self, cx, cy, a, b, dt):
        """
        Smooth pupil motion:
          - choose a random target inside ellipse every 0.8-1.6s
          - low-pass filter toward the target (with optional micro-saccades)
        """
        now = time.time()
        self.t += dt

        # choose new target occasionally
        if now >= self._t_next:
            # pick a random point inside ellipse (with uniform-ish distribution)
            theta = random.uniform(0, 2 * math.pi)
            r = math.sqrt(random.uniform(0.0, 1.0))  # bias toward center
            # Work in normalized ellipse coords then scale
            tx = cx + (a - self.pupil_rx) * r * math.cos(theta) * 0.85
            ty = cy + (b - self.pupil_ry) * r * math.sin(theta) * 0.85
            self._tx, self._ty = tx - cx, ty - cy
            self._t_next = now + random.uniform(0.8, 1.6)

        # micro-saccades (tiny, brief)
        if now >= self._next_sacc_t:
            self._sdx = random.uniform(-0.6, 0.6)
            self._sdy = random.uniform(-0.6, 0.6)
            self._sacc_end_t = now + 0.05
            self._next_sacc_t = now + random.uniform(2.0, 4.0)
        elif now >= self._sacc_end_t:
            self._sdx = 0.0
            self._sdy = 0.0

        # base LFO wander (very subtle)
        lfo_x = math.sin(self.t * 0.6) * (a - self.pupil_rx) * 0.06
        lfo_y = math.sin(self.t * 0.9) * (b - self.pupil_ry) * 0.05

        # target + extras
        target_x = self._tx + self._sdx + lfo_x
        target_y = self._ty + self._sdy + lfo_y

        # low-pass filter (smooth)
        alpha = 0.25
        self._dx = (1 - alpha) * self._dx + alpha * target_x
        self._dy = (1 - alpha) * self._dy + alpha * target_y

        # clamp to ellipse interior
        px, py = self._clamp_to_ellipse(cx, cy, a, b, cx + self._dx, cy + self._dy,
                                        self.pupil_rx, self.pupil_ry)
        return px - cx, py - cy

    # ----------------- frame render -----------------

    def render(self,
               mode: FocusMode,
               canvas: Image.Image,
               timer_text: Optional[str],
               at_risk_blink_on: bool,
               dt: float):
        draw = ImageDraw.Draw(canvas)

        # Background full white (you can switch to 0 for mostly-off OLED)
        draw.rectangle((0, 0, self.w, self.h), fill=1)

        # Current eye radii (half width/height)
        a = self.eye_w // 2
        b = self.eye_h // 2

        # Update eyelids and pupil offsets
        self._update_blink(mode)
        dxL, dyL = self._update_pupil_targets(self.cxL, self.cy, a, b, dt)
        dxR, dyR = self._update_pupil_targets(self.cxR, self.cy, a, b, dt)

        # Eyebrows only when timer is blinking (at-risk)
        angry_now = bool(at_risk_blink_on)
        # To get "mad + raised" together: left = mad (inward slant), right = raised
        left_angry = angry_now
        right_raised = angry_now

        # Draw eyes (blink deform via lid_frac)
        self._draw_eye(draw, self.cxL, self.cy, a, b, (dxL, dyL),
                       angry=left_angry, raised=False, lid_frac=self.lid_frac)
        self._draw_eye(draw, self.cxR, self.cy, a, b, (dxR, dyR),
                       angry=False, raised=right_raised, lid_frac=self.lid_frac)

        # --- Bottom text: timer or "DISTRACTED" ---
        if at_risk_blink_on:
            txt = "DISTRACTED"
            f = self.warn_font
        else:
            txt = timer_text or ""
            f = self.font

        if txt:
            # width via textbbox/textlength
            if hasattr(draw, "textbbox"):
                tb = draw.textbbox((0, 0), txt, font=f)
                tw = tb[2] - tb[0]
            else:
                tw = draw.textlength(txt, font=f)

            try:
                ascent, descent = f.getmetrics()
            except Exception:
                ascent, descent = getattr(f, "size", 12), 2

            x = (self.w - int(tw)) // 2
            baseline_y = self.h - descent - self.baseline_pad
            y = int(baseline_y - ascent)
            if y < 0:
                y = 0
            draw.text((x, y), txt, fill=0, font=f)


class EyeAnimator(threading.Thread):
    """
    Animator thread:
      - Receives state + timer updates from FocusTimerThread.
      - Renders at ~fps and pushes frames to the OLED via display_image(img).
    Expectation: oled exposes .width, .height, .display_image(PIL.Image).
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

        # Fonts: 26px timer, same for warning unless provided
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

            elapsed = time.time() - t0
            time.sleep(max(0.0, ft - elapsed))

    def stop(self):
        self.running = False
