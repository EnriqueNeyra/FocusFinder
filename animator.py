# animator.py (no external gaze; self-animated pupils)
import math, random, threading, time
from enum import Enum, auto
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

class FocusMode(Enum):
    FOCUSED = auto()
    WARNING = auto()
    DISTRACTED = auto()

def clamp(v, lo, hi): return max(lo, min(hi, v))

class EyeRenderer:
    def __init__(self, w: int, h: int, font: Optional[ImageFont.ImageFont]=None):
        self.w, self.h = w, h
        # geometry
        self.eye_w = int(w * 0.34); self.eye_h = int(h * 0.58)
        self.eye_spacing = int(w * 0.08)
        self.cxL = w//2 - self.eye_w//2 - self.eye_spacing//2
        self.cxR = w//2 + self.eye_w//2 + self.eye_spacing//2
        self.cy  = h//2 - 2
        self.pupil_rx = max(2, int(self.eye_w * 0.10))
        self.pupil_ry = max(2, int(self.eye_h * 0.14))
        self.pupil_lim_x = int(self.eye_w * 0.25)
        self.pupil_lim_y = int(self.eye_h * 0.20)

        # eyelids
        self.lid_frac = 1.0
        self.lid_target = 1.0
        self.next_blink_t = time.time() + random.uniform(2.5, 5.0)
        self.blinking = False; self.blink_end_t = 0.0

        # autonomous pupil motion
        self.t = 0.0
        self.sdx = 0; self.sdy = 0
        self.next_sacc_t = time.time() + random.uniform(1.6, 3.2)
        self.sacc_end_t = 0.0

        self.font = font

    def _eye_rect(self, cx, cy):
        return (cx - self.eye_w//2, cy - self.eye_h//2,
                cx + self.eye_w//2, cy + self.eye_h//2)

    def _draw_eye(self, draw: ImageDraw.ImageDraw, cx, cy, off, angry=False, skeptical=False):
        x0,y0,x1,y1 = self._eye_rect(cx, cy)
        draw.ellipse((x0, y0, x1, y1), outline=0, fill=1)        # white eye
        px = clamp(cx + off[0], x0 + self.pupil_rx, x1 - self.pupil_rx)
        py = clamp(cy + off[1], y0 + self.pupil_ry, y1 - self.pupil_ry)
        draw.ellipse((px - self.pupil_rx, py - self.pupil_ry,
                      px + self.pupil_rx, py + self.pupil_ry), fill=0)  # black pupil

        if self.lid_frac < 1.0:
            open_h = int(self.eye_h * self.lid_frac)
            lid_top = (self.eye_h - open_h)//2
            lid_bot = self.eye_h - open_h - lid_top
            draw.rectangle((x0, y0, x1, y0 + lid_top), fill=1)
            draw.rectangle((x0, y1 - lid_bot, x1, y1), fill=1)

        if angry:
            by = y0 - 2
            draw.line((x0+2, by+6, x0+self.eye_w//2, by), width=2, fill=0)
            draw.line((x0+self.eye_w//2, by, x1-2, by+6), width=2, fill=0)
        elif skeptical:
            byL = y0 + 4; byR = y0 - 2
            if cx < self.w//2:
                draw.line((x0+2, byL, x1-2, byL), width=2, fill=0)
            else:
                draw.line((x0+2, byR, x1-2, byR), width=2, fill=0)

    def _update_blink(self, mode: FocusMode):
        t = time.time()
        if mode == FocusMode.FOCUSED:   interval, dur = (2.5, 5.0), 0.18
        elif mode == FocusMode.WARNING: interval, dur = (1.6, 3.0), 0.22
        else:                           interval, dur = (2.0, 3.2), 0.10

        if not self.blinking and t >= self.next_blink_t:
            self.blinking, self.blink_end_t = True, t + dur

        if self.blinking:
            frac = (self.blink_end_t - t) / dur
            if frac <= 0:
                self.blinking = False
                self.next_blink_t = time.time() + random.uniform(*interval)
                self.lid_target = 1.0
            else:
                closeness = 1 - abs((frac*2)-1)  # 0->1->0
                self.lid_target = clamp(1.0 - 0.9*closeness, 0.05, 1.0)

        k = 0.35
        self.lid_frac = (1-k)*self.lid_frac + k*self.lid_target

    def _update_autonomous_motion(self, mode: FocusMode, dt: float):
        # Low-frequency wander + occasional saccades; add shake when not focused
        self.t += dt
        # LFO path (figure-8)
        lfo_x = math.sin(self.t * 0.9) * self.pupil_lim_x * 0.35
        lfo_y = math.sin(self.t * 1.3) * self.pupil_lim_y * 0.25

        # micro saccades
        now = time.time()
        if now >= self.next_sacc_t:
            self.sdx = random.randint(-2, 2); self.sdy = random.randint(-2, 2)
            self.sacc_end_t = now + 0.06
            self.next_sacc_t = now + random.uniform(1.6, 3.2)
        elif now >= self.sacc_end_t:
            self.sdx = 0; self.sdy = 0

        # mode shakes
        if mode == FocusMode.FOCUSED:
            shake_x, shake_y = 0, 0
            self.lid_target = max(self.lid_target, 0.95)
        elif mode == FocusMode.WARNING:
            amp = 1
            shake_x = int(math.sin(self.t * 6.0) * amp)
            shake_y = int(math.cos(self.t * 6.0) * amp)
            self.lid_target = min(self.lid_target, 0.7)
        else:
            amp = 2
            shake_x = int(math.sin(self.t * 10.0) * amp)
            shake_y = int(math.cos(self.t * 10.0) * amp)
            self.lid_target = min(self.lid_target, 0.5)

        dx = int(lfo_x) + self.sdx + shake_x
        dy = int(lfo_y) + self.sdy + shake_y
        return dx, dy

    def render(self, mode: FocusMode, canvas: Image.Image,
               timer_text: Optional[str], timer_blink_on: bool, dt: float):
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0,0,self.w,self.h), fill=1)  # white background on mono

        self._update_blink(mode)
        dx, dy = self._update_autonomous_motion(mode, dt)

        self._draw_eye(draw, self.cxL, self.cy, (dx, dy),
                       angry=(mode==FocusMode.DISTRACTED),
                       skeptical=(mode==FocusMode.WARNING))
        self._draw_eye(draw, self.cxR, self.cy, (dx, dy),
                       angry=(mode==FocusMode.DISTRACTED),
                       skeptical=(mode==FocusMode.WARNING))

        if timer_text and not timer_blink_on:
            f = self.font or ImageFont.load_default()
            # PIL’s default font lacks textlength size, so use getbbox fallback
            bbox = f.getbbox(timer_text)
            tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
            x = (self.w - tw) // 2
            y = self.h - th - 2
            draw.text((x, y), timer_text, fill=0, font=f)

class EyeAnimator(threading.Thread):
    def __init__(self, oled_display, fps: int = 20, timer_font: Optional[ImageFont.ImageFont]=None):
        super().__init__(daemon=True)
        self.oled = oled_display
        self.fps = fps
        self.mode = FocusMode.FOCUSED
        self.timer_text = None
        self.timer_blink_on = False
        self.running = False
        self.eye = EyeRenderer(self.oled.width, self.oled.height, font=timer_font)
        self._lock = threading.Lock()

    # keep same API the rest of your code calls, but ignore gaze entirely
    def set_state(self, focused: bool, warning: bool=False):
        with self._lock:
            self.mode = FocusMode.FOCUSED if focused else (FocusMode.WARNING if warning else FocusMode.DISTRACTED)

    def set_timer(self, text: str, blink_on: bool):
        with self._lock:
            self.timer_text = text
            self.timer_blink_on = blink_on

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
            time.sleep(max(0, ft - elapsed))

    def stop(self):
        self.running = False
