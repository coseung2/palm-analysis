"""Small independent four-channel baseline. No third-party checkpoint is reused."""
import torch
from torch import nn
from torch.nn import functional as F

ARCHITECTURE = 'palm-four-line-unet-v1'


def block(inputs, outputs):
    return nn.Sequential(
        nn.Conv2d(inputs, outputs, 3, padding=1, bias=False),
        nn.GroupNorm(4, outputs), nn.ReLU(inplace=True),
        nn.Conv2d(outputs, outputs, 3, padding=1, bias=False),
        nn.GroupNorm(4, outputs), nn.ReLU(inplace=True),
    )


class FourLineUNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoders = nn.ModuleList([block(3, 16), block(16, 32), block(32, 64)])
        self.center = block(64, 128)
        self.decoders = nn.ModuleList([block(192, 64), block(96, 32), block(48, 16)])
        self.output = nn.Conv2d(16, 4, 1)

    def forward(self, image):
        skips = []
        for encoder in self.encoders:
            image = encoder(image)
            skips.append(image)
            image = F.max_pool2d(image, 2)
        image = self.center(image)
        for decoder, skip in zip(self.decoders, reversed(skips), strict=True):
            image = F.interpolate(image, size=skip.shape[-2:], mode='bilinear', align_corners=False)
            image = decoder(torch.cat((skip, image), dim=1))
        return self.output(image)


def masked_loss(logits, targets, known):
    # Unknown is not a negative example. Known absent lines still contribute BCE.
    weights = known.to(logits.dtype)
    count = weights.sum().clamp_min(1)
    bce = F.binary_cross_entropy_with_logits(logits, targets, reduction='none').mean((-2, -1))
    probabilities = logits.sigmoid()
    intersection = (probabilities * targets).sum((-2, -1))
    dice = 1 - (2 * intersection + 1) / (probabilities.sum((-2, -1))
                                       + targets.sum((-2, -1)) + 1)
    return ((bce + dice) * weights).sum() / count
