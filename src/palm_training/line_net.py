"""Canonical-palm line segmenter: SMP U-Net (MiT-B0 encoder), one sigmoid channel per line."""


def build_line_net(channels, pretrained=True):
    import segmentation_models_pytorch as smp

    return smp.Unet('mit_b0', encoder_weights='imagenet' if pretrained else None,
                    in_channels=3, classes=channels)
