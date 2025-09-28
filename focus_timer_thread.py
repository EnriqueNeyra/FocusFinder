# focus_timer_thread.py
import threading
import time

class FocusTimerThread(threading.Thread):
    def __init__(self, focus_state, animator, reset_threshold=10, refocus_threshold=3):
        super().__init__(daemon=True)
        self.focus_state = focus_state
        self.animator = animator
        self.reset_threshold = reset_threshold
        self.refocus_threshold = refocus_threshold

        self.elapsed = 0
        self.active = False
        self.last_focus_state = False
        self.last_state_change = time.time()

    def run(self):
        next_tick = time.time()
        blink_phase = True  # 1 Hz toggle when at-risk

        while True:
            now = time.time()
            is_focused = self.focus_state.get()

            # edge-detect state changes
            if is_focused != self.last_focus_state:
                self.last_focus_state = is_focused
                self.last_state_change = now

            duration = now - self.last_state_change

            # start counting after a short refocus hold
            if is_focused and not self.active and duration >= self.refocus_threshold:
                self.active = True

            # reset when distracted too long
            if not is_focused and self.active and duration >= self.reset_threshold:
                self.elapsed = 0
                self.active = False

            if self.active:
                self.elapsed += 1

            # animator state: focused / warning / distracted
            warning = (not is_focused) and self.active and duration < self.reset_threshold
            self.animator.set_state(focused=is_focused and self.active, warning=warning)

            # timer text + blink when at-risk (>=2s distracted but not reset)
            at_risk = (not is_focused) and self.active and duration >= 2
            if at_risk:
                blink_phase = not blink_phase  # flip each second
            timer_text = f"{self.elapsed // 60:02}:{self.elapsed % 60:02}"
            # blink_on=True hides text on this frame inside the animator
            self.animator.set_timer(timer_text, blink_on=at_risk and blink_phase)

            # tick every second
            next_tick += 1
            time.sleep(max(0, next_tick - time.time()))
