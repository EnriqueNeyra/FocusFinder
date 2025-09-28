from PIL import Image, ImageDraw

class PILFrameBuffer:
    """
    Very small 'framebuffer' that the RoboEyes library can draw into.
    Colors are flipped to match your current OLED convention:
      1 (FG) -> black pixel, 0 (BG) -> white pixel
    """
    def __init__(self, width, height):
        self.width  = int(width)
        self.height = int(height)
        self.image  = Image.new("1", (self.width, self.height), 1)  # white
        self.draw   = ImageDraw.Draw(self.image)

    def _c(self, v):  # map RoboEyes color (0/1) to PIL 0/1
        # RoboEyes: 0=BG, 1=FG; We want BG=white(1), FG=black(0)
        return 0 if v == 1 else 1

    def fill(self, color):
        self.draw.rectangle((0, 0, self.width, self.height), fill=self._c(color))

    def pixel(self, x, y, color):
        self.draw.point((int(x), int(y)), fill=self._c(color))

    def fill_rect(self, x, y, w, h, color):
        x, y, w, h = int(x), int(y), int(w), int(h)
        self.draw.rectangle((x, y, x + w - 1, y + h - 1), fill=self._c(color))
