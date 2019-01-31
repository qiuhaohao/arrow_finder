import cv2
from PIL import Image
from picamera import PiCamera
from picamera.array import PiRGBArray
import numpy as np
import math

MIN_AREA = 3000

NUM_POINTS = 7

ARROW_UP = "ARROW_UP"
ARROW_DOWN = "ARROW_DOWN"
ARROW_LEFT = "ARROW_LEFT"
ARROW_RIGHT = "ARROW_RIGHT"

class ArrowFinder:
    """docstring for ArrowFinder"""
    def __init__(
            self, 
            resolution=(1920,1080), 
            min_area = 3000, 
            color_threshold={
                'lower': 160,
                'upper': 255
            },
            max_aspect_ratio=1.3, 
            radian_epsilon=math.pi/9,
            threshold_rad=1.1775
        ):

        self.camera = PiCamera()
        self.camera.resolution = resolution
        self.min_area = min_area
        self.color_threshold = color_threshold
        self.max_aspect_ratio = max_aspect_ratio
        self.radian_epsilon = radian_epsilon
        self.threshold_rad = threshold_rad

    def _find_rad(self, v1, v2):
        return math.acos(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

    def _is_around_square(self, box):
        long, short = max(box[2], box[3]), min(box[2], box[3])
        return (long / short) < self.max_aspect_ratio

    def _is_nearly_equal(self, n, m):
        return m - self.radian_epsilon < n and m + self.radian_epsilon > n

    def _points_to_rads(self, cont):
        n = len(cont)
        rads = []
        for i in range(n):
            prev = cont[(i-1)%n]
            cur = cont[i]
            nex = cont[(i+1)%n]
            
            prev_to_cur = cur - prev
            nex_to_cur = cur - nex
            
            rad = self._find_rad(prev_to_cur, nex_to_cur)
            rads.append(rad)
        return rads

    def _find_arrowhead_indice(self, rads):
        def nearly_pi_over_4(rad):
            return self._is_nearly_equal(rad, math.pi/4)
        def nearly_pi_over_2(rad):
            return self._is_nearly_equal(rad, math.pi/2)
        n = len(rads)
        qualified_index = []
        for i in range(n):
            prev = rads[(i-1)%n]
            cur = rads[i]
            nex = rads[(i+1)%n]
            
            if nearly_pi_over_4(prev) and nearly_pi_over_4(nex) and nearly_pi_over_2(cur): 
                qualified_index.append(i)
            elif (prev < self.threshold_rad + nex < self.threshold_rad + cur > self.threshold_rad) > 1:
                return

        if len(qualified_index) == 1:
            return qualified_index[0]
        else:
            return

    def _create_mask(self, im):
        mask = np.zeros(im.shape[:2], dtype=np.uint8)
        mask += cv2.inRange(
            im,
            self.color_threshold["lower"],
            self.color_threshold["upper"],
        )
        mask = cv2.blur(mask, (3, 3))
        return mask

    def _find_centroid(self, cont):
        M = cv2.moments(cont)
        cx = int(M['m10']/M['m00'])
        cy = int(M['m01']/M['m00'])
        return np.array([cx, cy], dtype=np.int32)

    def _find_arrowhead(self, cont):
        rads = self._points_to_rads(cont)
        arrow_head_index = self._find_arrowhead_indice(rads)
        
        if arrow_head_index is None:
            return
        arrow_head = cont[arrow_head_index]
        return arrow_head

    def _find_arrow_vec(self, cont):
        arrowhead = self._find_arrowhead(cont)
        if arrowhead is None:
            return
        centroid = self._find_centroid(cont)
        return arrowhead - centroid

    def _find_unit_arrow_vec(self, cont):
        arrow_vec = self._find_arrow_vec(cont)
        if arrow_vec is None:
            return
        return arrow_vec / np.linalg.norm(arrow_vec)

    def _find_arrow_direction(self, cont):
        unit_vec = self._find_unit_arrow_vec(cont)
        if unit_vec is None:
            return
        x, y = unit_vec[0], unit_vec[1]
        if x >= y and x <= -y:
            return ARROW_UP
        elif x < y and x > -y:
            return ARROW_DOWN
        elif x < y and x <= -y:
            return ARROW_LEFT
        else:
            return ARROW_RIGHT

    def _find_arrows(self, im):
        mask = self._create_mask(im)
        contours = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[1]
        contours_big = [
            c for c in contours
            if cv2.contourArea(c) >= MIN_AREA
        ]
        
        contours_big_approx = [
            cv2.approxPolyDP(c, 15, closed=True).squeeze()
            for c in contours_big
        ]
        contours_arrowlike = [
            c for c in contours_big_approx
            if len(c) == NUM_POINTS
        ]
        arrows = [
            {
                "dir": self._find_arrow_direction(c),
                "box": cv2.boundingRect(c)
            }
            for c in contours_arrowlike
        ]
        return [
            a for a in arrows
            if a['dir'] and self._is_around_square(a['box'])
        ]

    def _capture(self, color=True, gray=True):
        output = PiRGBArray(self.camera)
        self.camera.capture(output,'bgr')
        frame = output.array
        result = {}
        if color:
            result['color'] = frame
        if gray:
            result['gray'] = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return result

    def _draw(self, arrows, frame):
        for arrow in arrows:
            x = arrow['box'][0]
            y = arrow['box'][1]
            w = arrow['box'][2]
            h = arrow['box'][3]
            direction = arrow['dir']
            cv2.rectangle(frame, (x,y), (x+w, y+h), (255,0,0), 2)
            cv2.putText(frame, direction, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255))
        return frame

    def getArrows(self, withImage=False):
        ims = self._capture(color=withImage)
        gray = ims['gray']
        arrows = self._find_arrows(gray)
        result = { 'arrows': arrows }
        if withImage:
            color = ims['color']
            result['image'] = self._draw(arrows, color)
        return result


def _main():
    # Capture video from webcam 
    af = ArrowFinder()
    n = 0
    # Run the infinite loop
    while True:
        result = af.getArrows(withImage=False)
        arrows = result['arrows']
        print(arrows)
        # image = result['image']
        # # Save image
        # im = Image.fromarray(image)
        # im.save('pics/{}.jpg'.format(n))
        n += 1

if __name__ == "__main__":
    _main()