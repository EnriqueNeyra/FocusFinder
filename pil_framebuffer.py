from PIL import Image, ImageDraw

class PILFrameBuffer:
    def __init__(self, width, height):
        self.width  = int(width)
        self.height = int(height)
        self.image  = Image.new("1", (self.width, self.height), 1)  # white
        self.draw   = ImageDraw.Draw(self.image)

    def _c(self, v):
        return 0 if v == 1 else 1  # 1=FG->black, 0=BG->white

    def fill(self, color):
        self.draw.rectangle((0, 0, self.width, self.height), fill=self._c(color))

    def pixel(self, x, y, color):
        self.draw.point((int(x), int(y)), fill=self._c(color))

    def fill_rect(self, x, y, w, h, color):
        x, y, w, h = int(x), int(y), int(w), int(h)
        self.draw.rectangle((x, y, x + w - 1, y + h - 1), fill=self._c(color))


class RegionFrameBuffer:
    """
    A sub-framebuffer that draws into a rectangular region of a parent PILFrameBuffer.
    All coords are local to (x0, y0, x0+width, y0+height).
    """
    def __init__(self, parent_fb: PILFrameBuffer, x0: int, y0: int, width: int, height: int):
        self.parent = parent_fb
        self.x0 = int(x0); self.y0 = int(y0)
        self.width = int(width); self.height = int(height)
        # We draw straight onto the parent's image, but clamp to our region
        self.image = parent_fb.image
        self.draw = parent_fb.draw

    def _c(self, v):
        return self.parent._c(v)

    def _clip_rect(self, x, y, w, h):
        x1 = max(self.x0 + int(x), self.x0)
        y1 = max(self.y0 + int(y), self.y0)
        x2 = min(self.x0 + int(x) + int(w) - 1, self.x0 + self.width - 1)
        y2 = min(self.y0 + int(y) + int(h) - 1, self.y0 + self.height - 1)
        if x2 < x1 or y2 < y1:
            return None
        return (x1, y1, x2, y2)

    def fill(self, color):
        self.draw.rectangle((self.x0, self.y0, self.x0 + self.width - 1, self.y0 + self.height - 1),
                            fill=self._c(color))

    def pixel(self, x, y, color):
        X = self.x0 + int(x); Y = self.y0 + int(y)
        if 0 <= x < self.width and 0 <= y < self.height:
            self.draw.point((X, Y), fill=self._c(color))

    def fill_rect(self, x, y, w, h, color):
        r = self._clip_rect(x, y, w, h)
        if r:
            self.draw.rectangle(r, fill=self._c(color))
