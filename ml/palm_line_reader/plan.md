# Palm Fortune Webapp — RGB Student Model Plan

## Goal

Replace the NIR-trained MiT-B5 UNet (324 MB, server-side, heavy post-processing)
with a small RGB-native segmentation model that runs fully client-side in a
live webapp: MediaPipe hand tracking for ROI capture, a distilled student
network for palm line segmentation, no server inference.

## Background

- Teacher: `unet_palm_epoch_encoder_radxa_crop25.pth` — SMP UNet, `mit_b5`
  encoder, 1-channel (grayscale) input, 4 classes (background / heart / head /
  life), 1024×1024. Trained on NIR imagery.
- Feeding it RGB webcam frames works but only after the heavy post-processing
  in `infer.py` (closing → largest component → skeletonize → branch pruning →
  dilation).
- Key insight: train the student **on the post-processed masks**, so the
  cleanup pipeline is baked into the model and never needs porting to JS.

## Target architecture

| Component | Choice | Fallback / alternative |
|---|---|---|
| Student model | SMP UNet, `mit_b0` encoder (~3.7M param encoder) | `timm-mobilenetv3_large_100` if WASM-only perf matters more |
| Input | 3-channel RGB palm crop, 512×512 | — |
| Output | 4-class mask (bg / heart / head / life) | — |
| Hand ROI (client) | MediaPipe Hand Landmarker JS (WASM) | — |
| Inference runtime | ONNX Runtime Web, WebGPU backend | WASM+SIMD fallback (automatic) |
| Weights format | ONNX, fp16 (~8–12 MB) | int8 quantized (~5 MB) if download size matters |

Constraints that drove these choices:

- **Resolution is the budget, not params.** 1024² is a non-starter in-browser;
  a tight fingers-up palm crop keeps thin lines legible at 512².
- **Same encoder family as teacher** (`mit_b0` vs `mit_b5`) distills well and
  is a one-line change to existing SMP training code.
- **Plain ops only** (conv + standard attention) so ONNX export runs on every
  web backend without custom kernels.

Expected performance: ~15–30+ fps on WebGPU laptops; 0.5–2 s/frame on
WASM-only devices — acceptable because segmentation runs once per captured
frame, not per video frame (see UX below).

## Phase 1 — Pseudo-label generation

1. Collect/assemble RGB palm dataset (webcam-quality, varied lighting, both
   hands, varied skin tones if possible).
2. Run every image through the existing pipeline:
   `hand_preprocess.crop_and_rotate_hand` → teacher inference → full
   post-processing (`post_process_palm_line_mask` per class).
   Adapt `infer.py` into a batch script that saves, per image:
   - the oriented 1024² crop (resized to 512² for training)
   - the post-processed 4-class label mask (512²)
3. **Filter.** Spot-check overlays; drop frames where any line is missing,
   truncated, or hallucinated (teacher output on RGB is imperfect — e.g. the
   short life line on the 2026-07-07 webcam test). Bad pseudo-labels are
   training noise. A quick heuristic pre-filter: reject masks where a class's
   skeleton length is below a threshold, then eyeball the survivors.

## Phase 2 — Student training

1. Model: `smp.Unet(encoder_name="mit_b0", encoder_weights="imagenet", in_channels=3, classes=4)` at 512×512.
2. Input is **RGB** (that's the point — learn RGB-native features, drop the
   NIR mismatch).
3. Augmentation, heavy on photometric:
   - color jitter / white balance shifts / brightness-contrast (webcam WB varies wildly)
   - slight rotation (±10°) and crop/margin jitter to tolerate imperfect MediaPipe crops
   - horizontal flip **only if** left/right hands are both in scope (flip labels consistently)
4. Loss — must push the model to predict **one continuous line per palm line
   class** (the pseudo-labels are already single-component skeletons thanks to
   the post-processing, so the labels support this):
   - Base: CE + Dice on the 4-class masks.
   - **clDice** (centerline Dice, via differentiable soft-skeletonization) —
     the standard topology-aware loss for thin tubular structures; directly
     rewards an unbroken centerline rather than per-pixel overlap, so a line
     predicted with a gap is penalized much harder than plain Dice would.
   - **Connectivity regularizer:** per line class, penalize predicted mass
     outside the largest connected component (compute components on the
     thresholded prediction, penalize the softmax probability of the smaller
     fragments). Cheap, differentiable through the probabilities, and directly
     encodes "exactly one component per class". Enable after a few warmup
     epochs so early noisy predictions aren't over-penalized.
   - (Heavier alternative if fragments persist: a Betti-number/persistent-
     homology topology loss enforcing β₀ = 1 per class — principled but slow;
     only reach for it if clDice + the regularizer aren't enough.)
   - Optional: feature-distillation loss from the B5 teacher's encoder stages
     — nice-to-have, not required.
5. Track **connected components per class** as a validation metric alongside
   Dice; the target is exactly 1 per present line, and it's the metric that
   tells you the continuity losses are working.
6. Validate on a held-out set with per-class Dice on the skeletonized lines +
   visual overlay review, mirroring how the teacher was evaluated.

## Phase 3 — Export & quantization

1. Export to ONNX (opset ≥ 17), static 1×3×512×512 input.
2. Convert weights to fp16 (free ~2× size cut, negligible quality loss).
3. Verify parity: PyTorch vs onnxruntime (Python) vs onnxruntime-web outputs
   on a fixed test batch.
4. Optional: int8 dynamic quantization if the fp16 file is too heavy for the
   target audience's connections.
5. (Deferred alternative: TFLite + MediaPipe ImageSegmenter JS for a
   single-runtime stack — only if the ONNX path hits a wall; PyTorch→TFLite
   conversion is more brittle.)

## Phase 4 — Client-side webapp

1. **Live loop (every video frame):** MediaPipe Hand Landmarker JS on the
   webcam stream; draw guide overlay ("hold your palm here"), detect when the
   hand is steady, open-palmed, and large enough in frame.
2. **ROI extraction:** reproduce `crop_and_rotate_hand` in canvas transforms —
   rotate so wrist→middle-MCP points up, crop landmark bbox + margin, resize
   to 512². Must match Python preprocessing (same normalization the student
   was trained with).
3. **Capture moment (once per reading):** run the student via ONNX Runtime Web
   (`webgpu` execution provider, WASM fallback). One inference per reading —
   a ~1 s WASM latency reads as "consulting the spirits", so no fps pressure.
4. **Overlay:** argmax → per-class colored mask → alpha-blend onto the crop
   (canvas). No skeletonization client-side — the model outputs clean lines.
5. **Fortune text:** derive simple line features in JS (length, curvature,
   breaks) from the mask and map to fortune templates.
6. Lazy-load the ONNX weights (~10 MB) after page render; cache via service
   worker.

## Verification checklist

- [ ] Pseudo-label overlays spot-checked and filtered
- [ ] Student ≥ teacher-on-RGB quality on held-out overlays (it can exceed the teacher since labels are cleaned)
- [ ] Each predicted palm line is a single connected component on ≥95% of held-out frames (no fragments, no gaps)
- [ ] ONNX/web output parity with PyTorch
- [ ] Works on: Chrome+WebGPU, Chrome WASM-only (flag off), Safari, one mid-range Android phone
- [ ] Cold-load → first reading < 10 s on 4G-class connection

## Assets on this machine

- Teacher + pipeline: `C:\Users\sbarb\Downloads\palm-fortune\`
  (`infer.py`, `unet_palm_epoch_encoder_radxa_crop25.pth`,
  `hand_preprocess.py` — reconstructed 2026-07-07, MediaPipe tasks API,
  `hand_landmarker.task`)
- Sample teacher outputs: `palm-fortune\outputs\`, plus December training-era
  overlays loose in `Downloads` (`overlay_all.png`, `20__*.png`, …)
