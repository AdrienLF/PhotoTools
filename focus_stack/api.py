from focus_stack.main import FocusStacker, AlignmentMethod, SharpnessMetric, BlendMode

# Create a focus stacker with custom parameters
stacker = FocusStacker(
    alignment_method=AlignmentMethod.ORB,
    sharpness_metric=SharpnessMetric.LAPLACIAN,
    kernel_size=7,
    blend_mode=BlendMode.FEATHERED,
    output_format="png",
    downscale_factor=1.0,
    use_multiprocessing=True,
    verbose=True
)

# Process images
image_paths = ["image1.jpg", "image2.jpg", "image3.jpg"]
stacker.process(image_paths, "output_stacked.png")

# Or use individual steps for more control
stacker.load_images(image_paths)
stacker.align_images()
stacker.compute_sharpness_maps()
stacker.generate_focus_stack()
stacker.save_output("output_stacked.png")
