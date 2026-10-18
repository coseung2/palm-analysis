"""Student model definition — see ../plan.md, Phase 2.

Same SMP UNet family as the teacher (mit_b5), swapped for the much smaller
mit_b0 encoder so distillation is a one-line encoder-name change and export
targets stay within WASM/WebGPU budget.
"""

from __future__ import annotations

import segmentation_models_pytorch as smp

NUM_CLASSES = 4
IN_CHANNELS = 3


def build_student_model(
    encoder_name: str = "mit_b0",
    encoder_weights: str | None = "imagenet",
    in_channels: int = IN_CHANNELS,
    classes: int = NUM_CLASSES,
) -> smp.Unet:
    return smp.Unet(
        encoder_name=encoder_name,
        encoder_weights=encoder_weights,
        in_channels=in_channels,
        classes=classes,
    )
