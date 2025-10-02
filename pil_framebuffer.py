from PIL import Image, ImageDraw

class PILFrameBuffer:
    """
    1-bit framebuffer backed by Pillow.
    Convention: draw with color=1 for foreground (eyes/ink), which we map to black.
                color=0 is background, which we map to white.
    """
    def __init__(self, width, height):
        self.width  = int(width)
        self.height = int(height)
        # Initialize with 0 (black) for consistent 1-bit image handling
        self.image  = Image.new("1", (self.width, self.height), 0)
        self.draw   = ImageDraw.Draw(self.image)

    def _c(self, v):
        # RoboEyes uses 0/1, where 1 means “ink”. Map 1->0 (black), 0->1 (white).
        return 0 if v == 1 else 1

    def fill(self, color):
        # Reliable and efficient rectangle fill
        self.draw.rectangle((0, 0, self.width - 1, self.height - 1), fill=self._c(color))

    def pixel(self, x, y, color):
        self.draw.point((int(x), int(y)), fill=self._c(color))

    def fill_rect(self, x, y, w, h, color):
        x, y, w, h = int(x), int(y), int(w), int(h)
        # Inclusive rect
        self.draw.rectangle((x, y, x + w - 1, y + h - 1), fill=self._c(color))

    # --- optimized snapshot for minimal allocations ---
    def snapshot(self):
        return self.image.copy()



class RegionFrameBuffer:
    """
    Sub-framebuffer that draws into a rectangular region of a parent PILFrameBuffer.
    All coordinates are local to this region. Drawing is clipped so we never write
    outside the region (avoids edge artifacts).
    """
    def __init__(self, parent_fb: PILFrameBuffer, x0: int, y0: int, width: int, height: int):
        self.parent = parent_fb
        self.x0 = int(x0); self.y0 = int(y0)
        self.width = int(width); self.height = int(height)
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
        # Inclusive fill of the region box
        self.draw.rectangle(
            (self.x0, self.y0, self.x0 + self.width - 1, self.y0 + self.height - 1),
            fill=self._c(color)
        )

    def pixel(self, x, y, color):
        X = self.x0 + int(x); Y = self.y0 + int(y)
        if 0 <= x < self.width and 0 <= y < self.height:
            self.draw.point((X, Y), fill=self._c(color))

    def fill_rect(self, x, y, w, h, color):
        r = self._clip_rect(x, y, w, h)
        if r:
            self.draw.rectangle(r, fill=self._c(color))
