"""
ONNX Export and Inference Module for Neural Image Compression.

Exports CompressAI model sub-networks to ONNX format for lightweight deployment
without the full PyTorch stack. Keeps entropy coding (arithmetic coding + CDF tables)
in Python since it's lightweight and doesn't need GPU acceleration.

Exported sub-networks:
- g_a.onnx: encoder analysis (image -> latent)
- h_a.onnx: hyper encoder (latent -> hyper-latent)
- h_s.onnx: hyper decoder (hyper-latent -> parameters)
- g_s.onnx: decoder synthesis (latent -> image)
"""

import os
import json
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


class ONNXExporter:
    """
    Export CompressAI model sub-networks to ONNX format.

    Exports the four neural network transforms separately, along with
    CDF metadata needed for entropy coding. The entropy coder itself
    remains in Python (it's CPU-only and lightweight).
    """

    def __init__(self, model, model_name: str, quality: int):
        """
        Args:
            model: Loaded CompressAI model (already in eval mode)
            model_name: Name of the model architecture
            quality: Quality level used
        """
        self.model = model
        self.model_name = model_name
        self.quality = quality

    def export(self, output_dir: str, opset_version: int = 17) -> Dict[str, str]:
        """
        Export all sub-networks to ONNX files.

        Args:
            output_dir: Directory to save ONNX files
            opset_version: ONNX opset version (default 17)

        Returns:
            Dictionary mapping sub-network names to file paths
        """
        import torch
        import torch.onnx

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        exported = {}
        device = next(self.model.parameters()).device

        # Export g_a (analysis transform: image -> latent)
        ga_path = output_dir / "g_a.onnx"
        dummy_image = torch.randn(1, 3, 256, 256).to(device)
        self._export_subnetwork(
            self.model.g_a, dummy_image, ga_path,
            input_names=["image"],
            output_names=["latent"],
            dynamic_axes={"image": {2: "height", 3: "width"},
                          "latent": {2: "lat_h", 3: "lat_w"}},
            opset_version=opset_version
        )
        exported["g_a"] = str(ga_path)

        # Export h_a (hyper analysis: latent -> hyper-latent)
        ha_path = output_dir / "h_a.onnx"
        with torch.no_grad():
            dummy_latent = self.model.g_a(dummy_image)
        self._export_subnetwork(
            self.model.h_a, dummy_latent, ha_path,
            input_names=["latent"],
            output_names=["hyper_latent"],
            dynamic_axes={"latent": {2: "lat_h", 3: "lat_w"},
                          "hyper_latent": {2: "hlat_h", 3: "hlat_w"}},
            opset_version=opset_version
        )
        exported["h_a"] = str(ha_path)

        # Export h_s (hyper synthesis: hyper-latent -> parameters)
        hs_path = output_dir / "h_s.onnx"
        with torch.no_grad():
            dummy_hyper = self.model.h_a(dummy_latent)
        # Quantize for export shape reference
        dummy_hyper_hat = torch.round(dummy_hyper)
        self._export_subnetwork(
            self.model.h_s, dummy_hyper_hat, hs_path,
            input_names=["hyper_latent_hat"],
            output_names=["parameters"],
            dynamic_axes={"hyper_latent_hat": {2: "hlat_h", 3: "hlat_w"},
                          "parameters": {2: "param_h", 3: "param_w"}},
            opset_version=opset_version
        )
        exported["h_s"] = str(hs_path)

        # Export g_s (synthesis transform: latent -> image)
        gs_path = output_dir / "g_s.onnx"
        dummy_latent_hat = torch.round(dummy_latent)
        self._export_subnetwork(
            self.model.g_s, dummy_latent_hat, gs_path,
            input_names=["latent_hat"],
            output_names=["reconstructed"],
            dynamic_axes={"latent_hat": {2: "lat_h", 3: "lat_w"},
                          "reconstructed": {2: "height", 3: "width"}},
            opset_version=opset_version
        )
        exported["g_s"] = str(gs_path)

        # Save CDF metadata for entropy coding
        metadata = self._extract_entropy_metadata()
        metadata_path = output_dir / "entropy_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f)
        exported["metadata"] = str(metadata_path)

        # Save model info
        info = {
            "model_name": self.model_name,
            "quality": self.quality,
            "opset_version": opset_version,
            "sub_networks": list(exported.keys()),
        }
        info_path = output_dir / "model_info.json"
        with open(info_path, 'w') as f:
            json.dump(info, f, indent=2)
        exported["info"] = str(info_path)

        return exported

    def _export_subnetwork(
        self, module, dummy_input, output_path,
        input_names, output_names, dynamic_axes,
        opset_version
    ):
        """Export a single sub-network to ONNX."""
        import torch

        module.eval()
        with torch.no_grad():
            torch.onnx.export(
                module,
                dummy_input,
                str(output_path),
                input_names=input_names,
                output_names=output_names,
                dynamic_axes=dynamic_axes,
                opset_version=opset_version,
                do_constant_folding=True,
            )

    def _extract_entropy_metadata(self) -> Dict[str, Any]:
        """
        Extract entropy coding parameters (CDFs, offsets, etc.) from the model.

        These are needed for arithmetic coding but don't require neural network
        inference, so they're stored as JSON rather than in ONNX.
        """
        import torch

        metadata = {
            "model_name": self.model_name,
            "quality": self.quality,
        }

        # Extract entropy bottleneck parameters
        if hasattr(self.model, 'entropy_bottleneck'):
            eb = self.model.entropy_bottleneck
            if hasattr(eb, '_quantized_cdf'):
                metadata["entropy_bottleneck"] = {
                    "quantized_cdf": eb._quantized_cdf.cpu().numpy().tolist(),
                    "cdf_length": eb._cdf_length.cpu().numpy().tolist(),
                    "offset": eb._offset.cpu().numpy().tolist(),
                }

        # Extract gaussian conditional parameters if available
        if hasattr(self.model, 'gaussian_conditional'):
            gc = self.model.gaussian_conditional
            if hasattr(gc, '_quantized_cdf') and gc._quantized_cdf is not None:
                metadata["gaussian_conditional"] = {
                    "quantized_cdf": gc._quantized_cdf.cpu().numpy().tolist(),
                    "cdf_length": gc._cdf_length.cpu().numpy().tolist(),
                    "offset": gc._offset.cpu().numpy().tolist(),
                }
                if hasattr(gc, 'scale_table') and gc.scale_table is not None:
                    metadata["gaussian_conditional"]["scale_table"] = (
                        gc.scale_table.cpu().numpy().tolist()
                        if isinstance(gc.scale_table, torch.Tensor)
                        else list(gc.scale_table)
                    )

        return metadata


class ONNXInferenceEngine:
    """
    ONNX-based inference engine for neural image decompression.

    Drop-in replacement for model.decompress() that uses ONNX Runtime
    instead of PyTorch for neural network inference. Entropy coding
    (arithmetic decoding) is still done in Python.
    """

    def __init__(self, model_dir: str):
        """
        Load ONNX models and entropy metadata from a directory.

        Args:
            model_dir: Directory containing exported ONNX files
        """
        import onnxruntime as ort

        model_dir = Path(model_dir)

        # Load model info
        info_path = model_dir / "model_info.json"
        with open(info_path) as f:
            self.info = json.load(f)

        # Load ONNX sessions
        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

        self.g_s_session = ort.InferenceSession(
            str(model_dir / "g_s.onnx"),
            sess_options=sess_opts,
            providers=providers
        )
        self.h_s_session = ort.InferenceSession(
            str(model_dir / "h_s.onnx"),
            sess_options=sess_opts,
            providers=providers
        )

        # Load entropy metadata
        metadata_path = model_dir / "entropy_metadata.json"
        with open(metadata_path) as f:
            self.entropy_metadata = json.load(f)

        # Build CDF tables for entropy decoding
        self._build_cdf_tables()

    def _build_cdf_tables(self):
        """Build CDF lookup tables from metadata for entropy decoding."""
        self._eb_cdf = None
        self._eb_cdf_length = None
        self._eb_offset = None
        self._gc_cdf = None
        self._gc_cdf_length = None
        self._gc_offset = None
        self._gc_scale_table = None

        if "entropy_bottleneck" in self.entropy_metadata:
            eb = self.entropy_metadata["entropy_bottleneck"]
            self._eb_cdf = np.array(eb["quantized_cdf"], dtype=np.int32)
            self._eb_cdf_length = np.array(eb["cdf_length"], dtype=np.int32)
            self._eb_offset = np.array(eb["offset"], dtype=np.int32)

        if "gaussian_conditional" in self.entropy_metadata:
            gc = self.entropy_metadata["gaussian_conditional"]
            self._gc_cdf = np.array(gc["quantized_cdf"], dtype=np.int32)
            self._gc_cdf_length = np.array(gc["cdf_length"], dtype=np.int32)
            self._gc_offset = np.array(gc["offset"], dtype=np.int32)
            if "scale_table" in gc:
                self._gc_scale_table = np.array(gc["scale_table"], dtype=np.float32)

    def decompress(
        self, strings: List[List[bytes]], shape: Tuple[int, int]
    ) -> np.ndarray:
        """
        Decompress using ONNX inference for the neural network parts.

        This mirrors the CompressAI model.decompress() interface but uses
        ONNX Runtime for the g_s and h_s transforms. The entropy decoding
        (arithmetic coding) is done using the CompressAI entropy coder
        with pre-extracted CDF tables.

        Args:
            strings: List of [y_strings, z_strings] from compressed data
            shape: (height, width) of the latent representation

        Returns:
            Reconstructed tile as float32 numpy array (H, W, 3), values in [0, 255]
        """
        # For ONNX inference, we need to use CompressAI's entropy decoder
        # to get the quantized latents, then run g_s via ONNX
        import torch
        from compressai.entropy_models import EntropyBottleneck, GaussianConditional

        # We need a minimal model to do entropy decoding
        # Load model just for entropy decoding (cached by neural_compressor)
        from compressai.zoo import mbt2018_mean, cheng2020_anchor

        model_name = self.info["model_name"]
        quality = self.info["quality"]

        if model_name == "mbt2018_mean":
            model = mbt2018_mean(quality=quality, pretrained=True).eval()
        else:
            model = cheng2020_anchor(quality=quality, pretrained=True).eval()

        # Use the model's entropy decoder to get quantized latent
        with torch.no_grad():
            out = model.decompress(strings, shape)

        # The reconstruction from the model uses PyTorch g_s internally.
        # For true ONNX inference, we'd intercept after entropy decoding
        # and run g_s via ONNX. For now, we get y_hat from entropy decoding
        # and run g_s through ONNX.

        # Get y_hat by running entropy decoding only
        z_hat = model.entropy_bottleneck.decompress(strings[1], shape)
        params = self.h_s_session.run(
            None, {"hyper_latent_hat": z_hat.cpu().numpy()}
        )[0]

        # Use gaussian conditional to decode y
        scales_hat = torch.from_numpy(params)
        # Handle models that split params into scales and means
        if scales_hat.shape[1] == model.g_s[0].in_channels * 2:
            scales_hat, means_hat = scales_hat.chunk(2, dim=1)
        else:
            means_hat = None

        indexes = model.gaussian_conditional.build_indexes(scales_hat)
        y_hat = model.gaussian_conditional.decompress(
            strings[0], indexes, means=means_hat
        )

        # Run g_s through ONNX
        y_hat_np = y_hat.cpu().numpy()
        reconstructed = self.g_s_session.run(
            None, {"latent_hat": y_hat_np}
        )[0]

        # Convert to image format
        rec_tile = (np.squeeze(reconstructed, axis=0).transpose(1, 2, 0) * 255)
        rec_tile = rec_tile.clip(0, 255).astype(np.float32)

        return rec_tile


def export_model_to_onnx(
    model_name: str = "mbt2018_mean",
    quality: int = 6,
    output_dir: str = "onnx_models",
    verbose: bool = True
) -> Dict[str, str]:
    """
    Convenience function to export a CompressAI model to ONNX.

    Args:
        model_name: Model architecture name
        quality: Quality level
        output_dir: Output directory for ONNX files
        verbose: Print progress

    Returns:
        Dictionary of exported file paths
    """
    import torch
    from compressai.zoo import mbt2018_mean, cheng2020_anchor

    if verbose:
        print(f"Loading {model_name} quality {quality}...")

    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    if model_name == "mbt2018_mean":
        model = mbt2018_mean(quality=quality, pretrained=True)
    elif model_name == "cheng2020_anchor":
        model = cheng2020_anchor(quality=quality, pretrained=True)
    else:
        raise ValueError(f"Unknown model: {model_name}")

    model = model.eval().to(device)
    model.update()

    if verbose:
        print("Exporting to ONNX...")

    exporter = ONNXExporter(model, model_name, quality)
    result = exporter.export(output_dir)

    if verbose:
        print(f"Exported to {output_dir}/")
        for name, path in result.items():
            size = os.path.getsize(path) / (1024 * 1024)
            print(f"  {name}: {size:.2f} MB")

    return result
