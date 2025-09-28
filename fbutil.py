# Tiny subset of FBUtil used by roboeyes.py, implemented with PIL draw calls.
class FBUtil:
    def __init__(self, fb):
        self.fb = fb   # expects PILFrameBuffer
        self.draw = fb.draw

    def fill_rrect(self, x, y, w, h, r, color):
        x, y, w, h, r = int(x), int(y), int(w), int(h), int(r)
        # Pillow's rounded_rectangle includes stroke; we only need fill.
        self.draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), r, fill=self.fb._c(color))

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, color):
        self.draw.polygon([(int(x0), int(y0)), (int(x1), int(y1)), (int(x2), int(y2))],
                          fill=self.fb._c(color))
