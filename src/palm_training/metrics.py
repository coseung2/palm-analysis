"""Held-out crease metrics, not confidence scores or palmistry validation."""
from PIL import Image, ImageFilter

from .data import LINES


class LineMetrics:
    def __init__(self, tolerance=2, absent_area_fraction=.001):
        self.tolerance = tolerance
        self.absent_area_fraction = absent_area_fraction
        self.rows = {name: dict(positives=0, negatives=0, false_positives=0,
                               dice_sum=0., centerline_f1_sum=0.) for name in LINES}

    def add(self, predicted, targets, known):
        import numpy as np
        from skimage.morphology import skeletonize

        predicted, targets = np.asarray(predicted, dtype=bool), np.asarray(targets, dtype=bool)
        if predicted.shape != targets.shape or predicted.ndim != 3 or predicted.shape[0] != 4:
            raise ValueError('Expected matching four-channel binary maps')
        for index, name in enumerate(LINES):
            if not known[index]:
                continue
            row = self.rows[name]
            prediction, target = predicted[index], targets[index]
            if not target.any():
                row['negatives'] += 1
                row['false_positives'] += int(prediction.mean() >= self.absent_area_fraction)
                continue
            row['positives'] += 1
            row['dice_sum'] += float(2 * (prediction & target).sum()
                                     / max(int(prediction.sum() + target.sum()), 1))
            prediction, target = skeletonize(prediction), skeletonize(target)

            def dilate(mask):
                image = Image.fromarray(mask.astype('uint8') * 255)
                return np.asarray(image.filter(ImageFilter.MaxFilter(2 * self.tolerance + 1))) > 0

            precision = (prediction & dilate(target)).sum() / max(int(prediction.sum()), 1)
            recall = (target & dilate(prediction)).sum() / max(int(target.sum()), 1)
            row['centerline_f1_sum'] += float(2 * precision * recall / max(precision + recall, 1e-12))

    def result(self):
        return {name: {
            'positives': row['positives'], 'negatives': row['negatives'],
            'dice': row['dice_sum'] / row['positives'] if row['positives'] else None,
            'centerline_f1': (row['centerline_f1_sum'] / row['positives']
                              if row['positives'] else None),
            'absent_false_positive_rate': (row['false_positives'] / row['negatives']
                                           if row['negatives'] else None),
        } for name, row in self.rows.items()}
