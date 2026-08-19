"""
ELIC Model - Efficient Learned Image Compression

PyTorch implementation based on:
"ELIC: Efficient Learned Image Compression with Unevenly Grouped
Space-Channel Contextual Adaptive Coding" (CVPR 2022)

Reference: https://github.com/Huairui/ELIC
"""

import math
import warnings
import torch
import torch.nn as nn
import torch.nn.functional as F

from compressai.ans import BufferedRansEncoder, RansDecoder
from compressai.entropy_models import EntropyBottleneck, GaussianConditional
from compressai.layers import (
    AttentionBlock,
    conv3x3,
    subpel_conv3x3,
)

# Quality to lambda mapping (matching CompressAI convention)
QUALITY_TO_LAMBDA = {
    1: 0.0018,
    2: 0.0035,
    3: 0.0067,
    4: 0.0130,
    5: 0.0250,
    6: 0.0483,
    7: 0.0932,
    8: 0.1800,
    9: 0.3600,
}

SCALES_MIN = 0.11
SCALES_MAX = 256
SCALES_LEVELS = 64


def get_scale_table(min_val=SCALES_MIN, max_val=SCALES_MAX, levels=SCALES_LEVELS):
    return torch.exp(torch.linspace(math.log(min_val), math.log(max_val), levels))


def conv(in_channels, out_channels, kernel_size=5, stride=2):
    return nn.Conv2d(
        in_channels,
        out_channels,
        kernel_size=kernel_size,
        stride=stride,
        padding=kernel_size // 2,
    )


def deconv(in_channels, out_channels, kernel_size=5, stride=2):
    return nn.ConvTranspose2d(
        in_channels,
        out_channels,
        kernel_size=kernel_size,
        stride=stride,
        output_padding=stride - 1,
        padding=kernel_size // 2,
    )


def quantize_ste(x):
    """Straight-through estimator quantization."""
    return (torch.round(x) - x).detach() + x


def update_registered_buffers(
    module,
    module_name,
    buffer_names,
    state_dict,
):
    """Update registered buffers from state dict."""
    for buffer_name in buffer_names:
        full_name = f"{module_name}.{buffer_name}"
        if full_name in state_dict:
            buffer = state_dict[full_name]
            if buffer.numel() > 0:
                getattr(module, buffer_name).resize_(buffer.size())


class ResidualBottleneckBlock(nn.Module):
    """
    Residual bottleneck block as used in ELIC.
    
    Structure: 1x1 conv (reduce) -> 3x3 conv -> 1x1 conv (expand) + residual
    """
    
    def __init__(self, in_channels: int, out_channels: int, reduction: int = 4):
        super().__init__()
        mid_channels = in_channels // reduction
        
        self.conv1 = nn.Conv2d(in_channels, mid_channels, 1, 1, 0)
        self.conv2 = nn.Conv2d(mid_channels, mid_channels, 3, 1, 1)
        self.conv3 = nn.Conv2d(mid_channels, out_channels, 1, 1, 0)
        self.relu = nn.GELU()
        
        # Skip connection with 1x1 conv if channels don't match
        self.skip = nn.Identity() if in_channels == out_channels else nn.Conv2d(in_channels, out_channels, 1)
    
    def forward(self, x):
        identity = self.skip(x)
        out = self.relu(self.conv1(x))
        out = self.relu(self.conv2(out))
        out = self.conv3(out)
        return out + identity


class Demultiplexer(nn.Module):
    """Split tensor into 4 checkerboard patterns."""
    
    def forward(self, x):
        B, C, H, W = x.shape
        y0 = x[:, :, 0::2, 0::2]  # Top-left
        y1 = x[:, :, 0::2, 1::2]  # Top-right
        y2 = x[:, :, 1::2, 0::2]  # Bottom-left
        y3 = x[:, :, 1::2, 1::2]  # Bottom-right
        return y0, y1, y2, y3


class Multiplexer(nn.Module):
    """Combine 4 checkerboard patterns into tensor."""
    
    def forward(self, y0, y1, y2, y3):
        B, C, H, W = y0.shape
        x = torch.zeros(B, C, H * 2, W * 2, device=y0.device, dtype=y0.dtype)
        x[:, :, 0::2, 0::2] = y0
        x[:, :, 0::2, 1::2] = y1
        x[:, :, 1::2, 0::2] = y2
        x[:, :, 1::2, 1::2] = y3
        return x


class ResBottleneckGroup(nn.Sequential):
    """Group of 3 residual bottleneck blocks."""
    
    def __init__(self, in_channels: int = 192, out_channels: int = 192):
        super().__init__(
            ResidualBottleneckBlock(in_channels, out_channels),
            ResidualBottleneckBlock(out_channels, out_channels),
            ResidualBottleneckBlock(out_channels, out_channels),
        )


class MultistageMaskedConv2d(nn.Conv2d):
    """Masked convolution for context modeling."""
    
    def __init__(self, in_channels, out_channels, kernel_size, padding, stride=1, mask_type='A'):
        super().__init__(in_channels, out_channels, kernel_size, stride=stride, padding=padding)
        self.mask_type = mask_type
        self.register_buffer('mask', torch.ones_like(self.weight))
        
        # Create masks for different stages
        _, _, kH, kW = self.weight.shape
        center_h, center_w = kH // 2, kW // 2
        
        if mask_type == 'A':
            # Mask all but top-left quadrant influence
            self.mask[:, :, center_h:, :] = 0
            self.mask[:, :, :center_h, center_w:] = 0
            if kH % 2 == 1:
                self.mask[:, :, center_h, center_w] = 0
        elif mask_type == 'B':
            # Mask bottom half
            self.mask[:, :, center_h + 1:, :] = 0
        elif mask_type == 'C':
            # Mask only future positions
            self.mask[:, :, center_h, center_w + 1:] = 0
            self.mask[:, :, center_h + 1:, :] = 0
    
    def forward(self, x):
        self.weight.data *= self.mask
        return super().forward(x)


class ELIC(nn.Module):
    """
    ELIC: Efficient Learned Image Compression.
    
    Uses uneven channel grouping and space-channel contextual adaptive coding
    to achieve state-of-the-art compression performance.
    
    Args:
        N: Number of channels in main transforms (default: 192)
        M: Number of channels in latent space (default: 320)
    """
    
    def __init__(self, N=192, M=320):
        super().__init__()
        self.N = N
        self.M = M
        
        # Encoder (Analysis transform)
        self.g_a = nn.Sequential(
            conv(3, N, stride=2),
            ResBottleneckGroup(N, N),
            conv(N, N, stride=2),
            ResBottleneckGroup(N, N),
            AttentionBlock(N),
            conv(N, N, stride=2),
            ResBottleneckGroup(N, N),
            conv(N, M, stride=2),
            AttentionBlock(M),
        )
        
        # Decoder (Synthesis transform)
        self.g_s = nn.Sequential(
            AttentionBlock(M),
            subpel_conv3x3(M, N, 2),
            ResBottleneckGroup(N, N),
            subpel_conv3x3(N, N, 2),
            AttentionBlock(N),
            ResBottleneckGroup(N, N),
            subpel_conv3x3(N, N, 2),
            ResBottleneckGroup(N, N),
            subpel_conv3x3(N, 3, 2),
        )
        
        # Hyper encoder
        self.h_a = nn.Sequential(
            conv3x3(M, M),
            nn.LeakyReLU(inplace=True),
            conv3x3(M, M),
            nn.LeakyReLU(inplace=True),
            conv3x3(M, M, stride=2),
            nn.LeakyReLU(inplace=True),
            conv3x3(M, M),
            nn.LeakyReLU(inplace=True),
            conv3x3(M, M, stride=2),
        )
        
        # Hyper decoder
        self.h_s = nn.Sequential(
            conv3x3(M, M),
            nn.LeakyReLU(inplace=True),
            subpel_conv3x3(M, M, 2),
            nn.LeakyReLU(inplace=True),
            conv3x3(M, M * 3 // 2),
            nn.LeakyReLU(inplace=True),
            subpel_conv3x3(M * 3 // 2, M * 3 // 2, 2),
            nn.LeakyReLU(inplace=True),
            conv3x3(M * 3 // 2, M * 2),
        )
        
        # Entropy models
        self.entropy_bottleneck = EntropyBottleneck(M)
        self.gaussian_conditional = GaussianConditional(None)
        
        # Slice configuration for uneven channel grouping
        self.num_slices_list = [16, 16, 32, 64, 192]
        self.slice_end_list = [16, 32, 64, 128]
        
        # Context prediction modules (3-stage masked convolutions)
        self.context_prediction_1 = nn.ModuleList([
            MultistageMaskedConv2d(ns, ns * 2, kernel_size=3, padding=1, mask_type='A')
            for ns in self.num_slices_list
        ])
        self.context_prediction_2 = nn.ModuleList([
            MultistageMaskedConv2d(ns, ns * 2, kernel_size=3, padding=1, mask_type='B')
            for ns in self.num_slices_list
        ])
        self.context_prediction_3 = nn.ModuleList([
            MultistageMaskedConv2d(ns, ns * 2, kernel_size=3, padding=1, mask_type='C')
            for ns in self.num_slices_list
        ])
        
        # Entropy parameter networks for each slice
        entropy_params_channels = [
            [M * 2 + 16 * 2 + 0, 16 * 32, 16 * 8, 16 * 2],
            [M * 2 + 16 * 2 + 16, 16 * 32, 16 * 8, 16 * 2],
            [M * 2 + 32 * 2 + 32, 32 * 16, 32 * 8, 32 * 2],
            [M * 2 + 64 * 2 + 64, 64 * 8, 64 * 4, 64 * 2],
            [M * 2 + 192 * 2 + 128, 192 * 4, 192 * 4, 192 * 2],
        ]
        
        self.entropy_parameters = nn.ModuleList([
            nn.Sequential(
                conv(ch[0], ch[1], 1, 1),
                nn.GELU(),
                conv(ch[1], ch[2], 1, 1),
                nn.GELU(),
                conv(ch[2], ch[3], 1, 1),
            )
            for ch in entropy_params_channels
        ])
        
        self.demux = Demultiplexer()
        self.mux = Multiplexer()
    
    def forward(self, x):
        """Forward pass for training."""
        y = self.g_a(x)
        z = self.h_a(y)
        z_hat, z_likelihoods = self.entropy_bottleneck(z)
        params = self.h_s(z_hat)
        
        y_hat, y_likelihoods = self._forward_slices(y, params, z_hat.device)
        x_hat = self.g_s(y_hat)
        
        return {
            "x_hat": x_hat,
            "likelihoods": {"y": y_likelihoods, "z": z_likelihoods},
        }
    
    def _forward_slices(self, y, params, device):
        """Process slices with context modeling."""
        b, c, h, w = params.size()
        y_slices = torch.tensor_split(y, self.slice_end_list, dim=1)
        y_hat_slices = []
        y_likelihoods = []
        
        for slice_idx, y_slice in enumerate(y_slices):
            support = torch.cat([params] + y_hat_slices, dim=1)
            ns = self.num_slices_list[slice_idx]
            
            # Stage 0: No context
            ctx_params = torch.zeros(b, ns * 2, h, w, device=device)
            gaussian_params = self.entropy_parameters[slice_idx](
                torch.cat([support, ctx_params], dim=1)
            )
            scales, means = gaussian_params.chunk(2, dim=1)
            y_hat_slice = quantize_ste(y_slice - means) + means
            
            # Stage 1-3: Add context progressively
            for stage, ctx_pred in enumerate([
                self.context_prediction_1[slice_idx],
                self.context_prediction_2[slice_idx],
                self.context_prediction_3[slice_idx],
            ]):
                ctx = ctx_pred(y_hat_slice)
                ctx_params = ctx_params + ctx
                gaussian_params = self.entropy_parameters[slice_idx](
                    torch.cat([support, ctx_params], dim=1)
                )
                scales, means = gaussian_params.chunk(2, dim=1)
                y_hat_slice = quantize_ste(y_slice - means) + means
            
            y_hat_slices.append(y_hat_slice)
            _, likelihood = self.gaussian_conditional(y_slice, scales, means=means)
            y_likelihoods.append(likelihood)
        
        y_hat = torch.cat(y_hat_slices, dim=1)
        y_likelihoods = torch.cat(y_likelihoods, dim=1)
        return y_hat, y_likelihoods
    
    def compress(self, x):
        """Compress image to bitstream."""
        y = self.g_a(x)
        z = self.h_a(y)
        
        z_strings = self.entropy_bottleneck.compress(z)
        z_hat = self.entropy_bottleneck.decompress(z_strings, z.size()[-2:])
        params = self.h_s(z_hat)
        
        b, c, h, w = params.size()
        y_slices = torch.tensor_split(y, self.slice_end_list, dim=1)
        
        encoder = BufferedRansEncoder()
        symbols_list = []
        indexes_list = []
        y_hat_slices = []
        
        cdf = self.gaussian_conditional.quantized_cdf.tolist()
        cdf_lengths = self.gaussian_conditional.cdf_length.reshape(-1).int().tolist()
        offsets = self.gaussian_conditional.offset.reshape(-1).int().tolist()
        
        for slice_idx, y_slice in enumerate(y_slices):
            support = torch.cat([params] + y_hat_slices, dim=1)
            ns = self.num_slices_list[slice_idx]
            
            # Get means and scales with full context
            ctx_params = torch.zeros(b, ns * 2, h, w, device=z_hat.device)
            y_hat_slice = torch.zeros_like(y_slice)
            
            # 4-stage encoding with checkerboard pattern
            y0, y1, y2, y3 = self.demux(y_slice)
            y_hat_0, y_hat_1, y_hat_2, y_hat_3 = [torch.zeros_like(y0) for _ in range(4)]
            
            for stage_idx in range(4):
                # Update context based on already-coded positions
                if stage_idx > 0:
                    y_hat_slice = self.mux(y_hat_0, y_hat_1, y_hat_2, y_hat_3)
                    ctx_list = [
                        self.context_prediction_1[slice_idx],
                        self.context_prediction_2[slice_idx],
                        self.context_prediction_3[slice_idx],
                    ]
                    for ctx_pred in ctx_list[:stage_idx]:
                        ctx_params = ctx_params + ctx_pred(y_hat_slice)
                
                gaussian_params = self.entropy_parameters[slice_idx](
                    torch.cat([support, ctx_params], dim=1)
                )
                scales, means = gaussian_params.chunk(2, dim=1)
                
                # Get current checkerboard position
                s0, s1, s2, s3 = self.demux(scales)
                m0, m1, m2, m3 = self.demux(means)
                
                current_y = [y0, y1, y2, y3][stage_idx]
                current_s = [s0, s1, s2, s3][stage_idx]
                current_m = [m0, m1, m2, m3][stage_idx]
                
                indexes = self.gaussian_conditional.build_indexes(current_s)
                y_q = self.gaussian_conditional.quantize(current_y, "symbols", current_m)
                y_hat_current = y_q + current_m
                
                symbols_list.extend(y_q.reshape(-1).tolist())
                indexes_list.extend(indexes.reshape(-1).tolist())
                
                if stage_idx == 0:
                    y_hat_0 = y_hat_current
                elif stage_idx == 1:
                    y_hat_1 = y_hat_current
                elif stage_idx == 2:
                    y_hat_2 = y_hat_current
                else:
                    y_hat_3 = y_hat_current
            
            y_hat_slices.append(self.mux(y_hat_0, y_hat_1, y_hat_2, y_hat_3))
        
        encoder.encode_with_indexes(symbols_list, indexes_list, cdf, cdf_lengths, offsets)
        y_strings = encoder.flush()
        
        return {
            "strings": [y_strings, z_strings],
            "shape": z.size()[-2:],
        }
    
    def decompress(self, strings, shape):
        """Decompress bitstream to image."""
        z_hat = self.entropy_bottleneck.decompress(strings[1], shape)
        params = self.h_s(z_hat)
        
        b, c, h, w = params.size()
        
        decoder = RansDecoder()
        decoder.set_stream(strings[0])
        
        cdf = self.gaussian_conditional.quantized_cdf.tolist()
        cdf_lengths = self.gaussian_conditional.cdf_length.reshape(-1).int().tolist()
        offsets = self.gaussian_conditional.offset.reshape(-1).int().tolist()
        
        y_hat_slices = []
        
        for slice_idx in range(5):
            support = torch.cat([params] + y_hat_slices, dim=1)
            ns = self.num_slices_list[slice_idx]
            
            ctx_params = torch.zeros(b, ns * 2, h, w, device=z_hat.device)
            y_hat_0 = torch.zeros(b, ns, h // 2, w // 2, device=z_hat.device)
            y_hat_1 = torch.zeros_like(y_hat_0)
            y_hat_2 = torch.zeros_like(y_hat_0)
            y_hat_3 = torch.zeros_like(y_hat_0)
            
            for stage_idx in range(4):
                if stage_idx > 0:
                    y_hat_slice = self.mux(y_hat_0, y_hat_1, y_hat_2, y_hat_3)
                    ctx_list = [
                        self.context_prediction_1[slice_idx],
                        self.context_prediction_2[slice_idx],
                        self.context_prediction_3[slice_idx],
                    ]
                    for ctx_pred in ctx_list[:stage_idx]:
                        ctx_params = ctx_params + ctx_pred(y_hat_slice)
                
                gaussian_params = self.entropy_parameters[slice_idx](
                    torch.cat([support, ctx_params], dim=1)
                )
                scales, means = gaussian_params.chunk(2, dim=1)
                
                s0, s1, s2, s3 = self.demux(scales)
                m0, m1, m2, m3 = self.demux(means)
                
                current_s = [s0, s1, s2, s3][stage_idx]
                current_m = [m0, m1, m2, m3][stage_idx]
                
                indexes = self.gaussian_conditional.build_indexes(current_s)
                num_symbols = indexes.numel()
                
                symbols = decoder.decode_stream(
                    indexes.reshape(-1).tolist(), cdf, cdf_lengths, offsets
                )
                symbols = torch.tensor(symbols, device=z_hat.device).reshape(indexes.shape)
                y_hat_current = symbols + current_m
                
                if stage_idx == 0:
                    y_hat_0 = y_hat_current
                elif stage_idx == 1:
                    y_hat_1 = y_hat_current
                elif stage_idx == 2:
                    y_hat_2 = y_hat_current
                else:
                    y_hat_3 = y_hat_current
            
            y_hat_slices.append(self.mux(y_hat_0, y_hat_1, y_hat_2, y_hat_3))
        
        y_hat = torch.cat(y_hat_slices, dim=1)
        x_hat = self.g_s(y_hat).clamp_(0, 1)
        
        return {"x_hat": x_hat}
    
    def update(self, force=False):
        """Update entropy model CDFs."""
        updated = self.entropy_bottleneck.update(force=force)
        self.gaussian_conditional.update_scale_table(get_scale_table())
        return updated
    
    def load_state_dict(self, state_dict, strict=True):
        """Load state dict with buffer updates."""
        update_registered_buffers(
            self.entropy_bottleneck,
            "entropy_bottleneck",
            ["_quantized_cdf", "_offset", "_cdf_length"],
            state_dict,
        )
        update_registered_buffers(
            self.gaussian_conditional,
            "gaussian_conditional",
            ["_quantized_cdf", "_offset", "_cdf_length", "scale_table"],
            state_dict,
        )
        super().load_state_dict(state_dict, strict=strict)


def elic(quality: int = 6, pretrained: bool = False, **kwargs):
    """
    Load ELIC model.
    
    Args:
        quality: Quality level 1-9 (higher = better quality, larger files)
        pretrained: Load pretrained weights (when available)
        
    Returns:
        ELIC model instance
    """
    if quality < 1 or quality > 9:
        raise ValueError(f"Quality must be 1-9, got {quality}")
    
    model = ELIC(**kwargs)
    
    if pretrained:
        # TODO: Load pretrained weights when available
        warnings.warn(
            "Pretrained weights not yet available. "
            "Model initialized with random weights."
        )
    
    return model
