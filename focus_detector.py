import cv2
import numpy as np
from picamera2 import Picamera2
import time

class FocusDetector:
    def __init__(self, cascade_path=None):
        if cascade_path is None:
            cascade_path = "./model_files/haarcascade_frontalface_alt2.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        
        # Optional: Load eye cascade for additional validation
        self.eye_cascade = cv2.CascadeClassifier("./model_files/haarcascade_eye.xml")

    def is_face_frontal(self, face_roi, face_x, face_y):
        """Check if face is roughly frontal by detecting both eyes"""
        eyes = self.eye_cascade.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=3)
        
        # Convert eye coordinates from face ROI to full image coordinates
        global_eyes = []
        for (ex, ey, ew, eh) in eyes:
            global_ex = face_x + ex + ew//2  # Center of eye
            global_ey = face_y + ey + eh//2  # Center of eye
            global_eyes.append((global_ex, global_ey))
        
        # Frontal faces should have 2 visible eyes
        return len(eyes) >= 2, global_eyes

    def is_focused(self, frame_gray):
        faces = self.face_cascade.detectMultiScale(
            frame_gray, 
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(50, 50),
        )
        
        # Filter faces to only include frontal ones
        frontal_faces = []
        all_eyes = []
        
        for (x, y, w, h) in faces:
            face_roi = frame_gray[y:y+h, x:x+w]
            is_frontal, eyes = self.is_face_frontal(face_roi, x, y)
            if is_frontal:
                frontal_faces.append((x, y, w, h))
                all_eyes.extend(eyes)
        
        return len(frontal_faces) > 0, frontal_faces, all_eyes