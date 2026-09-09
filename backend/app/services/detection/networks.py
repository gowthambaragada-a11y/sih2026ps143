"""PyTorch segmentation networks: U-Net (primary) and a lightweight SegFormer-style
model for comparison.  Implemented from scratch with no external segmentation
dependencies so the system is fully reproducible and offline-runnable.

Class convention (index -> label):
    0 sea, 1 oil, 2 look-alike, 3 ship, 4 land
Binary mode collapses to: 0 non-oil, 1 oil.
"""
from __future__ import annotations

from typing import Optional, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Common building blocks
# ---------------------------------------------------------------------------
class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int, mid: Optional[int] = None, dropout: float = 0.0):
        super().__init__()
        mid = mid or cin
        self.net = nn.Sequential(
            nn.Conv2d(cin, mid, 3, padding=1, bias=False),
            nn.BatchNorm2d(mid),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid, cout, 3, padding=1, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(inplace=True),
        )
        if dropout > 0:
            self.net.append(nn.Dropout2d(dropout))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class _DoubleConv(nn.Module):
    def __init__(self, cin, cout):
        super().__init__()
        self.conv = ConvBlock(cin, cout)

    def forward(self, x):
        return self.conv(x)


# ---------------------------------------------------------------------------
# U-Net
# ---------------------------------------------------------------------------
class UNet(nn.Module):
    """Encoder-decoder with skip connections, suitable for oil-slick segmentation.

    n_channels: input SAR bands (1 = VV, 2 = VV/VH).
    n_classes: output classes.
    """

    def __init__(self, n_channels: int = 2, n_classes: int = 5, base: int = 32):
        super().__init__()
        self.n_channels = n_channels
        self.n_classes = n_classes

        self.inc = _DoubleConv(n_channels, base)
        self.down1 = _Down(base, base * 2)
        self.down2 = _Down(base * 2, base * 4)
        self.down3 = _Down(base * 4, base * 8)
        self.down4 = _Down(base * 8, base * 8)

        self.up1 = _Up(in_up=base * 8, in_skip=base * 8, cout=base * 4)
        self.up2 = _Up(in_up=base * 4, in_skip=base * 4, cout=base * 2)
        self.up3 = _Up(in_up=base * 2, in_skip=base * 2, cout=base)
        self.up4 = _Up(in_up=base, in_skip=base, cout=base)

        self.outc = nn.Conv2d(base, n_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)
        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        return self.outc(x)


class _Down(nn.Module):
    def __init__(self, cin, cout):
        super().__init__()
        self.mp = nn.MaxPool2d(2)
        self.conv = ConvBlock(cin, cout)

    def forward(self, x):
        return self.conv(self.mp(x))


class _Up(nn.Module):
    def __init__(self, in_up, in_skip, cout):
        super().__init__()
        self.up = nn.ConvTranspose2d(in_up, in_up // 2, 2, stride=2)
        self.conv = ConvBlock(in_up // 2 + in_skip, cout)

    def forward(self, x1, x2):
        x1 = self.up(x1)
        # crop x2 to match x1 if needed
        diffy = x2.size()[2] - x1.size()[2]
        diffx = x2.size()[3] - x1.size()[3]
        x1 = F.pad(x1, [diffx // 2, diffx - diffx // 2, diffy // 2, diffy - diffy // 2])
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)


# ---------------------------------------------------------------------------
# Lightweight SegFormer-style model (for comparison)
# ---------------------------------------------------------------------------
class OverlapPatchEmbed(nn.Module):
    """Non-overlapping / overlapping patch embedding, mobile net style."""

    def __init__(self, cin, cout, stride, patch_size=7, norm="ln"):
        super().__init__()
        self.proj = nn.Conv2d(cin, cout, kernel_size=patch_size, stride=stride,
                              padding=patch_size // 2)
        self.norm = nn.LayerNorm(cout, eps=1e-6)

    def forward(self, x):
        x = self.proj(x)          # (B,C,H,W)
        b, c, h, w = x.shape
        x = x.flatten(2).transpose(1, 2)   # (B, H*W, C)
        x = self.norm(x)
        x = x.transpose(1, 2).reshape(b, c, h, w)
        return x


class MobileBlock(nn.Module):
    """Depthwise-separable conv block (leading)SFR block."""

    def __init__(self, dim, expansion=4):
        super().__init__()
        mid = dim * expansion
        self.dwconv = nn.Conv2d(dim, dim, 3, padding=1, groups=dim, bias=False)
        self.norm = nn.BatchNorm2d(dim)
        self.pw1 = nn.Conv2d(dim, mid, 1, bias=False)
        self.pw2 = nn.Conv2d(mid, dim, 1, bias=False)
        self.act = nn.GELU()

    def forward(self, x):
        out = self.dwconv(x)
        out = self.norm(out)
        out = self.act(out)
        out = self.pw1(out)
        out = self.act(out)
        out = self.pw2(out)
        return out + x


class SegFormerLight(nn.Module):
    """A compact SegFormer-style hierarchical transformer used for comparison.

    Provides a mix of local conv + lightweight attention stages.  Kept small for
    CPU/limited-GPU training.
    """

    def __init__(self, n_channels: int = 2, n_classes: int = 5, embed_dims=(24, 48, 96, 192)):
        super().__init__()
        d0, d1, d2, d3 = embed_dims
        self.embed0 = OverlapPatchEmbed(n_channels, d0, stride=2, patch_size=7)
        self.embed1 = OverlapPatchEmbed(d0, d1, stride=2, patch_size=3)
        self.embed2 = OverlapPatchEmbed(d1, d2, stride=2, patch_size=3)
        self.embed3 = OverlapPatchEmbed(d2, d3, stride=2, patch_size=3)

        self.block0 = nn.Sequential(*[MobileBlock(d0) for _ in range(1)])
        self.block1 = nn.Sequential(*[MobileBlock(d1) for _ in range(1)])
        self.block2 = nn.Sequential(*[MobileBlock(d2) for _ in range(1)])
        self.block3 = nn.Sequential(*[MobileBlock(d3) for _ in range(1)])

        self.decode_head = nn.ModuleList([
            _SegHeadLayer(d0, d0),
            _SegHeadLayer(d1, d0),
            _SegHeadLayer(d2, d0),
            _SegHeadLayer(d3, d0),
        ])
        self.final = nn.Conv2d(d0 * 4, d0, 1)
        self.out = nn.Conv2d(d0, n_classes, 1)

    def forward(self, x):
        outs = []
        e0 = self.block0(self.embed0(x))
        e1 = self.block1(self.embed1(e0))
        e2 = self.block2(self.embed2(e1))
        e3 = self.block3(self.embed3(e2))

        size = e0.shape[-2:]
        layers = []
        for feat, head in zip([e0, e1, e2, e3], self.decode_head):
            layers.append(F.interpolate(head(feat), size=size, mode="bilinear", align_corners=False))
        fused = torch.cat(layers, dim=1)
        fused = self.out(self.final(fused))
        return fused


class _SegHeadLayer(nn.Module):
    def __init__(self, cin, cout):
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, 1)
        self.norm = nn.BatchNorm2d(cout)
        self.act = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.act(self.norm(self.conv(x)))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def build_segmentation_model(kind: str, n_channels: int, n_classes: int, **kw) -> nn.Module:
    kind = (kind or "unet").lower()
    if kind == "segformer":
        return SegFormerLight(n_channels=n_channels, n_classes=n_classes, **kw)
    return UNet(n_channels=n_channels, n_classes=n_classes, **kw)
