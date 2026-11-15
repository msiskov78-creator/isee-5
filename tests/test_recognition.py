"""Проверяем геометрию четырёх поз, запись и защиту от повторов без видеокамеры."""

import unittest
from actions.action_executor import GestureGate
from gesture_control.gesture_detector import GestureDetector, feature_distance, normalize_landmarks
from gesture_control.gesture_recorder import GestureRecorder
from hand_tracking.hand_detector import describe_hand


def pose(key):
    points = [[.5, .8, 0.] for _ in range(21)]
    extended = {"open_palm": {5, 9, 13, 17}, "two_fingers": {5, 9}, "custom": {5}}.get(key, set())
    for base, x in zip((5, 9, 13, 17), (.38, .47, .56, .65)):
        points[base] = [x, .60, 0.]
        points[base + 1] = [x, .43, 0.]
        points[base + 2] = [x, .34 if base in extended else .50, 0.]
        points[base + 3] = [x, .25 if base in extended else .58, 0.]
    points[1] = [.39, .72, 0.]
    if key == "thumbs_up":
        points[2:5] = [[.30, .60, 0.], [.28, .43, 0.], [.26, .25, 0.]]
    elif key in {"open_palm", "custom"}:
        points[2:5] = [[.32, .64, 0.], [.24, .58, 0.], [.16, .52, 0.]]
    else:
        points[2:5] = [[.30, .66, 0.], [.38, .58, 0.], [.47, .63, 0.]]
    return describe_hand(points, "right")


class RecognitionTests(unittest.TestCase):
    def test_moderate_similarity_does_not_block_recording(self):
        template = normalize_landmarks(pose("custom")["landmarks"])
        detector = GestureDetector([{"id": "one", "name": "Первая поза", "gesture_data": {"template": template}}])
        self.assertIsNotNone(detector.find_similar({"template": [v + .01 for v in template]}))
        self.assertIsNone(detector.find_similar({"template": [v + .10 for v in template]}))

    def test_four_standard_poses_and_mirrored_hand(self):
        detector = GestureDetector()
        for key in ("thumbs_up", "fist", "two_fingers", "open_palm"):
            with self.subTest(key=key):
                hand = pose(key)
                self.assertEqual(detector.detect(hand)["key"], key)
                mirrored = describe_hand([[1-x,y,z] for x,y,z in hand["landmarks"]], "left")
                self.assertEqual(detector.detect(mirrored)["key"], key)

    def test_quality_hints_and_two_hand_rejection(self):
        points = pose("open_palm")["landmarks"]
        near = describe_hand([[.5+(x-.5)*.15,.5+(y-.5)*.15,z] for x,y,z in points])
        self.assertIn("ближе", near["hint"])
        cropped = describe_hand([[x-.2,y,z] for x,y,z in points])
        self.assertIn("всю кисть", cropped["hint"])
        large = describe_hand([[.05+(x-.16)/(.65-.16)*.9, .5+(y-.5)*.7,z] for x,y,z in points])
        self.assertIn("дальше", large["hint"])
        two = describe_hand(points, count=2)
        self.assertFalse(two["ready"])
        self.assertIsNone(GestureDetector().detect(two)["key"])

    def test_normalization_and_recording_custom_pose(self):
        hand = pose("custom")
        original = normalize_landmarks(hand["landmarks"])
        transformed = [[1.7*y+.2,-1.7*x+.4,z*1.7] for x,y,z in hand["landmarks"]]
        self.assertLess(feature_distance(original, normalize_landmarks(transformed)), 1e-8)
        recorder = GestureRecorder()
        recorder.start()
        for _ in range(39):
            recorder.add_sample(hand)
        self.assertFalse(recorder.complete)
        recorder.add_sample(hand)
        data = recorder.gesture_data()
        self.assertEqual(len(data["samples"]), 40)
        self.assertIsNone(GestureDetector().find_similar(data))
        detector = GestureDetector([{"id":"sample", "key":"custom_sample", "name":"Мой жест", "gesture_data":data}])
        self.assertEqual(detector.detect(hand)["key"], "custom_sample")
        self.assertEqual(detector.find_similar(data)["name"], "Мой жест")
        recorder.start()
        for _ in range(40):
            recorder.add_sample(pose("open_palm"))
        self.assertEqual(GestureDetector().find_similar(recorder.gesture_data())["key"], "open_palm")

    def test_recording_drops_interrupted_samples(self):
        recorder = GestureRecorder()
        recorder.start()
        for _ in range(20):
            recorder.add_sample(pose("custom"))
        self.assertGreater(recorder.progress, 0)
        recorder.add_sample({"found":False,"hint":"Рука не обнаружена"})
        self.assertEqual(recorder.progress, 0)

    def test_cooldown_release_and_frame_gap(self):
        gate = GestureGate()
        settings = {"hold_time":.5,"cooldown":1.,"sensitivity":.7}
        triggers = []
        for index in range(41):
            if gate.update("fist",.95,settings,index*.05):
                triggers.append(index*.05)
        self.assertEqual(triggers, [.5])
        # Короткая потеря уверенности не считается сменой позы.
        for index in range(41,51):
            self.assertFalse(gate.update("fist",.4,settings,index*.05))
        for index in range(51,61):
            gate.update(None,0,settings,index*.05)
        for index in range(61,76):
            if gate.update("fist",.95,settings,index*.05):
                triggers.append(index*.05)
        self.assertEqual(len(triggers),2)
        gate.reset()
        gate.update("fist",.95,settings,1)
        self.assertFalse(gate.update("fist",.95,settings,10))
        # Cooldown сохраняется и при переходе к другой позе.
        gate.reset()
        settings["hold_time"] = .1
        for index in range(3):
            gate.update("fist",.95,settings,index*.05)
        for index in range(3,21):
            self.assertFalse(gate.update("thumbs_up",.95,settings,index*.05))


if __name__ == "__main__":
    unittest.main()
