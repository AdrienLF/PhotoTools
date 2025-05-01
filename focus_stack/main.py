#!/usr/bin/env python3
"""
Focus Stacking Software

This module provides complete functionality for focus stacking - combining multiple images 
taken at different focus distances to create a single image with extended depth of field.
"""

import os
import sys
import argparse
import glob
from enum import Enum
import numpy as np
import cv2
from tqdm import tqdm
import multiprocessing
from typing import List, Tuple, Dict, Optional, Union, Any


class AlignmentMethod(Enum):
    """Enumeration of available image alignment methods."""
    NONE = "none"
    ECC = "ecc"
    ORB = "orb"


class SharpnessMetric(Enum):
    """Enumeration of available sharpness detection metrics."""
    LAPLACIAN = "laplacian"
    SOBEL = "sobel"
    TENENGRAD = "tenengrad"


class BlendMode(Enum):
    """Enumeration of available blending methods."""
    FEATHERED = "feathered"
    HARD = "hard"


class FocusStacker:
    """
    Main class for focus stacking operations.
    
    This class handles the full pipeline of loading, aligning, analyzing sharpness,
    and blending images to create a focus-stacked result.
    """
    
    def __init__(self, 
                 alignment_method: AlignmentMethod = AlignmentMethod.ECC,
                 sharpness_metric: SharpnessMetric = SharpnessMetric.LAPLACIAN,
                 kernel_size: int = 5,
                 blend_mode: BlendMode = BlendMode.FEATHERED,
                 output_format: str = "png",
                 downscale_factor: float = 1.0,
                 use_multiprocessing: bool = False,
                 verbose: bool = False):
        """
        Initialize the focus stacker with processing parameters.
        
        Args:
            alignment_method: Method to use for image alignment
            sharpness_metric: Metric to evaluate pixel sharpness
            kernel_size: Size of kernel for local sharpness evaluation
            blend_mode: Method for blending selected regions
            output_format: Format for saving the output image
            downscale_factor: Factor to downscale images during processing (1.0 = no downscaling)
            use_multiprocessing: Whether to use multiprocessing for faster processing
            verbose: Whether to output detailed processing information and intermediate results
        """
        self.alignment_method = alignment_method
        self.sharpness_metric = sharpness_metric
        self.kernel_size = kernel_size
        self.blend_mode = blend_mode
        self.output_format = output_format.lower()
        self.downscale_factor = downscale_factor
        self.use_multiprocessing = use_multiprocessing
        self.verbose = verbose
        
        # Validate parameters
        if self.kernel_size % 2 == 0:
            self.kernel_size += 1  # Ensure kernel size is odd
            
        # Validate output format
        if self.output_format not in ['jpg', 'jpeg', 'png', 'tiff', 'tif']:
            raise ValueError(f"Unsupported output format: {self.output_format}")
            
        self.images = []
        self.aligned_images = []
        self.sharpness_maps = []
        self.output_image = None
        
    def load_images(self, image_paths: List[str]) -> None:
        """
        Load input images from provided paths.
        
        Args:
            image_paths: List of paths to images for focus stacking
        
        Raises:
            FileNotFoundError: If an image file cannot be found
            ValueError: If no valid images could be loaded
        """
        if self.verbose:
            print("Loading images...")
            
        self.images = []
        
        for path in tqdm(image_paths, disable=not self.verbose):
            if not os.path.exists(path):
                raise FileNotFoundError(f"Image file not found: {path}")
                
            try:
                img = cv2.imread(path)
                if img is None:
                    print(f"Warning: Could not read image {path}, skipping.")
                    continue
                    
                # Apply downscaling if requested
                if self.downscale_factor != 1.0:
                    width = int(img.shape[1] * self.downscale_factor)
                    height = int(img.shape[0] * self.downscale_factor)
                    img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
                    
                self.images.append(img)
                
                if self.verbose:
                    print(f"Loaded {path}, shape: {img.shape}")
            except Exception as e:
                print(f"Error loading {path}: {str(e)}")
                
        if not self.images:
            raise ValueError("No valid images could be loaded")
            
        if self.verbose:
            print(f"Loaded {len(self.images)} images")
    
    def align_images(self) -> None:
        """
        Align all loaded images to the first image in the stack.
        
        Uses the selected alignment method to register images and correct for
        slight shifts between frames.
        """
        if self.verbose:
            print(f"Aligning images using {self.alignment_method.value} method...")
            
        if len(self.images) < 2:
            self.aligned_images = self.images.copy()
            return
            
        # Use the first image as reference
        reference = self.images[0]
        gray_reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        self.aligned_images = [reference]
        
        for i, img in enumerate(tqdm(self.images[1:], disable=not self.verbose), 1):
            if self.alignment_method == AlignmentMethod.NONE:
                self.aligned_images.append(img)
                continue
                
            gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            if self.alignment_method == AlignmentMethod.ECC:
                # Enhanced Correlation Coefficient alignment
                warp_mode = cv2.MOTION_TRANSLATION
                warp_matrix = np.eye(2, 3, dtype=np.float32)
                criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 1000, 1e-5)
                
                try:
                    _, warp_matrix = cv2.findTransformECC(
                        gray_reference, gray_img, warp_matrix, warp_mode, criteria)
                    aligned = cv2.warpAffine(img, warp_matrix, (reference.shape[1], reference.shape[0]),
                                          flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
                    self.aligned_images.append(aligned)
                except Exception as e:
                    print(f"Warning: ECC alignment failed for image {i}. Using original image. Error: {str(e)}")
                    self.aligned_images.append(img)
                    
            elif self.alignment_method == AlignmentMethod.ORB:
                # ORB feature matching
                orb = cv2.ORB_create()
                kp1, des1 = orb.detectAndCompute(gray_reference, None)
                kp2, des2 = orb.detectAndCompute(gray_img, None)
                
                if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
                    print(f"Warning: Not enough features found in image {i}. Using original image.")
                    self.aligned_images.append(img)
                    continue
                
                # FLANN parameters
                FLANN_INDEX_LSH = 6
                index_params = dict(algorithm=FLANN_INDEX_LSH,
                                    table_number=6,
                                    key_size=12,
                                    multi_probe_level=1)
                search_params = dict(checks=50)
                
                try:
                    flann = cv2.FlannBasedMatcher(index_params, search_params)
                    matches = flann.knnMatch(des1, des2, k=2)
                    
                    # Keep good matches using Lowe's ratio test
                    good_matches = []
                    for match in matches:
                        if len(match) == 2:
                            m, n = match
                            if m.distance < 0.7 * n.distance:
                                good_matches.append(m)
                    
                    if len(good_matches) >= 4:
                        src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                        dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
                        
                        # Find homography
                        M, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0)
                        aligned = cv2.warpPerspective(img, M, (reference.shape[1], reference.shape[0]))
                        self.aligned_images.append(aligned)
                    else:
                        print(f"Warning: Not enough good matches for image {i}. Using original image.")
                        self.aligned_images.append(img)
                except Exception as e:
                    print(f"Warning: ORB alignment failed for image {i}. Using original image. Error: {str(e)}")
                    self.aligned_images.append(img)
        
        if self.verbose:
            print(f"Aligned {len(self.aligned_images)} images")
    
    def compute_sharpness_maps(self) -> None:
        """
        Compute sharpness maps for all aligned images.
        
        Generates a per-pixel measure of local sharpness using the selected
        sharpness metric.
        """
        if self.verbose:
            print(f"Computing sharpness maps using {self.sharpness_metric.value} metric...")
            
        self.sharpness_maps = []
        
        def process_image(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            if self.sharpness_metric == SharpnessMetric.LAPLACIAN:
                # Laplacian variance (most common focus measure)
                lap = cv2.Laplacian(gray, cv2.CV_64F, ksize=self.kernel_size)
                # Calculate variance in local windows
                kernel = np.ones((self.kernel_size, self.kernel_size), np.float32) / (self.kernel_size * self.kernel_size)
                laplacian_abs = np.abs(lap)
                return cv2.filter2D(laplacian_abs, -1, kernel)
                
            elif self.sharpness_metric == SharpnessMetric.SOBEL:
                # Sobel gradient magnitude
                sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=self.kernel_size)
                sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=self.kernel_size)
                magnitude = np.sqrt(sobelx**2 + sobely**2)
                # Apply smoothing to compute local average
                kernel = np.ones((self.kernel_size, self.kernel_size), np.float32) / (self.kernel_size * self.kernel_size)
                return cv2.filter2D(magnitude, -1, kernel)
                
            elif self.sharpness_metric == SharpnessMetric.TENENGRAD:
                # Tenengrad (gradient magnitude squared)
                sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=self.kernel_size)
                sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=self.kernel_size)
                tenengrad = sobelx**2 + sobely**2
                # Apply smoothing to compute local average
                kernel = np.ones((self.kernel_size, self.kernel_size), np.float32) / (self.kernel_size * self.kernel_size)
                return cv2.filter2D(tenengrad, -1, kernel)
        
        if self.use_multiprocessing and len(self.aligned_images) > 1:
            # Use multiprocessing for faster computation
            with multiprocessing.Pool(processes=min(multiprocessing.cpu_count(), len(self.aligned_images))) as pool:
                self.sharpness_maps = list(tqdm(
                    pool.imap(process_image, self.aligned_images),
                    total=len(self.aligned_images),
                    disable=not self.verbose
                ))
        else:
            for img in tqdm(self.aligned_images, disable=not self.verbose):
                self.sharpness_maps.append(process_image(img))
                
        if self.verbose:
            print(f"Computed {len(self.sharpness_maps)} sharpness maps")
            
        # Save debug information if requested
        if self.verbose:
            for i, sharpness_map in enumerate(self.sharpness_maps):
                # Normalize for visualization
                normalized = cv2.normalize(sharpness_map, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
                heatmap = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
                cv2.imwrite(f"sharpness_map_{i:02d}.png", heatmap)
    
    def generate_focus_stack(self) -> None:
        """
        Generate the final focus-stacked image by selecting the sharpest pixels.
        
        Creates a mask based on sharpness values and blends images accordingly.
        """
        if self.verbose:
            print("Generating focus stack...")
            
        if not self.sharpness_maps or not self.aligned_images:
            raise ValueError("Sharpness maps or aligned images are missing. Run align_images() and compute_sharpness_maps() first.")
            
        # Find the regions with maximum sharpness
        sharpness_maps = np.array(self.sharpness_maps)
        shape = self.aligned_images[0].shape
        
        # Get index of maximum sharpness for each pixel
        max_sharp_indices = np.argmax(sharpness_maps, axis=0)
        
        if self.blend_mode == BlendMode.HARD:
            # Hard blending - pick pixels directly from images with max sharpness
            result = np.zeros(shape, dtype=np.uint8)
            for i, img in enumerate(self.aligned_images):
                mask = (max_sharp_indices == i)
                mask_3d = np.stack([mask] * 3, axis=2)
                result = np.where(mask_3d, img, result)
                
        elif self.blend_mode == BlendMode.FEATHERED:
            # Feathered blending - use weighted average based on sharpness values
            
            # Normalize sharpness maps
            sharpness_sum = np.sum(sharpness_maps, axis=0)
            sharpness_sum = np.where(sharpness_sum == 0, 1, sharpness_sum)  # Avoid division by zero
            
            # Create the weighted average
            result = np.zeros(shape, dtype=np.float32)
            
            for i, img in enumerate(self.aligned_images):
                # Calculate weight for this image
                weight = sharpness_maps[i] / sharpness_sum
                weight_3d = np.stack([weight] * 3, axis=2)
                
                # Add weighted contribution
                result += img.astype(np.float32) * weight_3d
                
            # Convert back to uint8
            result = np.clip(result, 0, 255).astype(np.uint8)
            
        self.output_image = result
        
        if self.verbose:
            print("Focus stack generated")
            
    def save_output(self, output_path: str) -> None:
        """
        Save the focus-stacked result to the specified path.
        
        Args:
            output_path: Path to save the output image
            
        Raises:
            ValueError: If no output image has been generated
        """
        if self.output_image is None:
            raise ValueError("No output image has been generated. Run generate_focus_stack() first.")
            
        # Ensure the directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        # Ensure file has correct extension
        if self.output_format in ['jpg', 'jpeg']:
            if not output_path.lower().endswith(('.jpg', '.jpeg')):
                output_path += '.jpg'
            quality_param = [int(cv2.IMWRITE_JPEG_QUALITY), 95]
            cv2.imwrite(output_path, self.output_image, quality_param)
            
        elif self.output_format in ['png']:
            if not output_path.lower().endswith('.png'):
                output_path += '.png'
            compression_param = [int(cv2.IMWRITE_PNG_COMPRESSION), 9]
            cv2.imwrite(output_path, self.output_image, compression_param)
            
        elif self.output_format in ['tif', 'tiff']:
            if not output_path.lower().endswith(('.tif', '.tiff')):
                output_path += '.tiff'
            cv2.imwrite(output_path, self.output_image)
            
        if self.verbose:
            print(f"Saved output to {output_path}")
    
    def process(self, image_paths: List[str], output_path: str) -> None:
        """
        Process a complete focus stack from input paths to output image.
        
        This is a convenience method that runs the full pipeline.
        
        Args:
            image_paths: List of paths to source images
            output_path: Path to save the focus-stacked result
        """
        self.load_images(image_paths)
        self.align_images()
        self.compute_sharpness_maps()
        self.generate_focus_stack()
        self.save_output(output_path)
        
        if self.verbose:
            print("Focus stacking complete!")


def parse_arguments():
    """Parse command line arguments for the focus stacking tool."""
    parser = argparse.ArgumentParser(description='Focus Stack - Create extended depth of field images')
    
    parser.add_argument('input', nargs='+', help='Input image files or glob pattern')
    parser.add_argument('-o', '--output', required=True, help='Output image path')
    
    parser.add_argument('-a', '--align', choices=['none', 'ecc', 'orb'], default='ecc',
                        help='Alignment method (default: ecc)')
                        
    parser.add_argument('-k', '--kernel-size', type=int, default=5,
                        help='Kernel size for sharpness detection (default: 5)')
                        
    parser.add_argument('-s', '--sharpness', choices=['laplacian', 'sobel', 'tenengrad'], 
                        default='laplacian', help='Sharpness metric (default: laplacian)')
                        
    parser.add_argument('-b', '--blend', choices=['feathered', 'hard'], default='feathered',
                        help='Blending mode (default: feathered)')
                        
    parser.add_argument('-f', '--format', choices=['jpg', 'jpeg', 'png', 'tif', 'tiff'], 
                        default='png', help='Output format (default: png)')
                        
    parser.add_argument('-d', '--downscale', type=float, default=1.0,
                        help='Downscale factor for processing (default: 1.0, no downscaling)')
                        
    parser.add_argument('-m', '--multiprocessing', action='store_true',
                        help='Use multiprocessing for faster computation')
                        
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose/debug mode, output intermediate steps')
                        
    return parser.parse_args()


def expand_paths(paths):
    """Expand glob patterns in paths to individual file paths."""
    expanded = []
    for path in paths:
        if '*' in path or '?' in path or '[' in path:
            expanded.extend(sorted(glob.glob(path)))
        else:
            expanded.append(path)
    return expanded


def main():
    """Main entry point for the focus stacking tool."""
    args = parse_arguments()
    
    # Expand any glob patterns in input paths
    input_paths = expand_paths(args.input)
    
    if not input_paths:
        print("Error: No input images found.")
        return 1
    
    # Set up the focus stacker with command line parameters
    stacker = FocusStacker(
        alignment_method=AlignmentMethod(args.align),
        sharpness_metric=SharpnessMetric(args.sharpness),
        kernel_size=args.kernel_size,
        blend_mode=BlendMode(args.blend),
        output_format=args.format,
        downscale_factor=args.downscale,
        use_multiprocessing=args.multiprocessing,
        verbose=args.verbose
    )
    
    try:
        stacker.process(input_paths, args.output)
        return 0
    except Exception as e:
        print(f"Error during focus stacking: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
