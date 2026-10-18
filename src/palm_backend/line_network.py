"""Checkpoint-compatible U-Net for the optional personal palm-line experiment.

Adapted from yeonsumia/palmistry code/model.py at
17610c3f031ee312d3352116eefff9b833e9cafb, which attributes
milesial/Pytorch-UNet. See third_party/palmistry/NOTICE.md for provenance.
"""
import torch
from torch import nn
from torch.nn import functional as F


class DoubleConv(nn.Module):
    def __init__(self, inputs, outputs, middle=None):
        super().__init__()
        middle = middle or outputs
        self.double_conv = nn.Sequential(
            nn.Conv2d(inputs, middle, 3, padding=1, bias=False), nn.BatchNorm2d(middle), nn.ReLU(inplace=True),
            nn.Conv2d(middle, outputs, 3, padding=1, bias=False), nn.BatchNorm2d(outputs), nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.double_conv(x)


class Down(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        self.maxpool_conv = nn.Sequential(nn.MaxPool2d(2), DoubleConv(inputs, outputs))

    def forward(self, x):
        return self.maxpool_conv(x)


class Up(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv = DoubleConv(inputs, outputs, inputs // 2)

    def forward(self, x, skip):
        x = self.up(x)
        dy, dx = skip.size(2) - x.size(2), skip.size(3) - x.size(3)
        x = F.pad(x, [dx // 2, dx - dx // 2, dy // 2, dy - dy // 2])
        return self.conv(torch.cat([skip, x], dim=1))


class OutConv(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        self.conv = nn.Conv2d(inputs, outputs, 1)

    def forward(self, x):
        return self.conv(x)


class ContextFusion(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.context_modeling = nn.Sequential(nn.Conv2d(channels, channels, 1), nn.Softmax2d())
        self.context_transform1 = nn.Sequential(nn.Conv2d(channels, channels, 1), nn.ReLU(inplace=True), nn.Conv2d(channels, channels, 1), nn.Sigmoid())
        self.context_transform2 = nn.Sequential(nn.Conv2d(channels, channels, 1), nn.ReLU(inplace=True), nn.Conv2d(channels, channels, 1))

    def forward(self, x):
        x = F.max_pool2d(x, 2)
        context = self.context_modeling(x) * x
        return self.context_transform1(context) * x + self.context_transform2(context)


class LineUNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.inc = DoubleConv(3, 64)
        self.down1, self.down2, self.down3 = Down(64, 128), Down(128, 256), Down(256, 512)
        self.cfm = ContextFusion(512)
        self.up1, self.up2 = Up(1024, 256), Up(512, 128)
        self.up3, self.up4 = Up(256, 64), Up(128, 64)
        self.outc = OutConv(64, 1)

    def forward(self, x):
        a = self.inc(x)
        b = self.down1(a)
        c = self.down2(b)
        d = self.down3(c)
        return self.outc(self.up4(self.up3(self.up2(self.up1(self.cfm(d), d), c), b), a))
