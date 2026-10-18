# Palm-line student training pack

Self-contained Phase 2/3 code from [`../plan.md`](../plan.md) (RGB-native
`mit_b0` UNet student, distilled from the `mit_b5` teacher's post-processed
masks). Meant to be copied whole to a GPU machine once
[`../pipeline/generate_pseudo_labels.py`](../pipeline/generate_pseudo_labels.py)
has produced and you've spot-checked a `data/` directory.

## What's in here vs. what stays behind

- **This pack** (`model.py`, `dataset.py`, `losses.py`, `metrics.py`,
  `train.py`, `export_onnx.py`): no dependency on MediaPipe or the teacher
  checkpoint, just needs an already-labeled `data/` directory. Everything
  needed to train and export the student.
- **The `pipeline/` folder**: `generate_pseudo_labels.py` (Phase 1)
  and `label_tool.py`, which stay on the source machine since they need
  the teacher checkpoint
  (`unet_palm_epoch_encoder_radxa_crop25.pth`, 324 MB), MediaPipe's hand
  landmarker, and (for the label tool) a browser.
- **Not built yet**: Phase 4, the client webapp that consumes the exported
  ONNX model. Separate follow-up once you're happy with a trained model.

## 1. Generate pseudo-labels (source machine, not here)

From the parent directory:

```
python generate_pseudo_labels.py --out_dir training_pack/data
```

The heuristic pre-filter (`manifest.csv`'s `pass_filter` column, driven by
`--min_skeleton_len`) catches obviously-missing/truncated lines but won't
catch hallucinated or misplaced ones -- the teacher's RGB output isn't
reliable enough to trust unreviewed.

## 1.5. Review and fix masks by hand (source machine, not here)

```
python ../label_tool.py --data_dir training_pack/data
```

Opens a small local web app (`http://127.0.0.1:8765/`) for paging through
`data/images/*.png`, painting/erasing each line class directly over the
photo (brush + eraser, per-class colors, undo), and saving corrected masks
back to `data/masks/<stem>.png`. Review state goes to `data/reviewed.csv`
(kept separate from `manifest.csv`, which the batch script owns and may
still be writing to) -- `edited`/`approved` stems are included in training
even if the heuristic filter rejected them, and `rejected` stems are
excluded even if the heuristic filter passed them. A human verdict always
overrides the heuristic; see `dataset.py`'s module docstring for the exact
precedence rule.

## 2. scp this pack to the GPU box

```
scp -r training_pack user@gpu-box:~/palm-training
```

(Do this after step 1 so `data/` comes along with the code.)

## 3. Set up the environment on the GPU box

```
# CUDA-enabled torch first -- match the wheel to your driver's CUDA version
# (check with `nvidia-smi`); see https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

pip install -r requirements.txt

python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## 4. Train

```
python train.py --data_dir data --out_dir runs/exp1 --epochs 150 --batch_size 16
```

Useful flags (defaults match `plan.md` Phase 2):

| Flag | Default | Notes |
|---|---|---|
| `--encoder` | `mit_b0` | swap to e.g. `timm-mobilenetv3_large_100` per plan.md's fallback |
| `--img_size` | 512 | |
| `--cldice_weight` | 0.5 | topology-aware centerline loss weight |
| `--distance_weight` | 0.3 | skeleton distance-transform (Chamfer-style) loss weight -- penalizes predicted line mass by distance to the true centerline, so a line in roughly the right place costs less than one with the wrong length/direction, independent of thickness |
| `--distance_warmup_epochs` | 0 | epoch the distance term turns on; 0 is safe since the term is clipped (`--distance_max_px`) and well-defined even for random early predictions |
| `--distance_max_px` | 32.0 | clip distance in pixels (at `--img_size`); bounds how much a single very-wrong prediction can dominate the loss early on |
| `--connectivity_weight` | 0.1 | connected-component regularizer weight |
| `--connectivity_warmup_epochs` | 5 | regularizer stays off until this epoch so early noisy predictions aren't over-penalized |
| `--val_fraction` | 0.1 | held-out split, drawn from `data/manifest.csv` stems |
| `--resume` | — | path to a checkpoint to continue from |

Outputs in `--out_dir`:

- `checkpoints/best.pt` — highest mean foreground Dice on held-out data
- `checkpoints/epoch####.pt` — periodic checkpoints (`--save_every`)
- `train_log.csv` — per-epoch losses, per-class Dice, and two topology/geometry
  diagnostics:
  - `single_comp_{heart,head,life}` — fraction of validation images where
    that class came out as exactly one connected component. Tells you
    whether clDice + the connectivity regularizer are working; watch it
    trend toward 1.0 after the connectivity warmup epoch, per the
    "Verification checklist" in `../plan.md`.
  - `dist_{heart,head,life}_px` — mean distance (pixels, at `--img_size`)
    from the predicted skeleton to the nearest true skeleton pixel, when
    both are present. Tells you whether the distance loss is working;
    watch it trend down. This is about *position/length/direction*
    accuracy, independent of the Dice/single-component metrics above.
- `val_overlays/epoch####_sample##.png` — `base | ground-truth | prediction`
  triptychs, for the visual review `plan.md` also asks for.

## 5. Export to ONNX

```
python export_onnx.py --checkpoint runs/exp1/checkpoints/best.pt --out exported/student.onnx
```

Produces `exported/student.onnx` (fp32), `exported/student_fp16.onnx`
(weights cast to fp16, I/O stays fp32, ~2x smaller — this is the one to hand
to Phase 4 per plan.md's target of ~8-12 MB), and, with `--int8`,
`exported/student_int8.onnx` (dynamic quantization, smaller but lossier).

Each variant is checked against the PyTorch model's own output on random
inputs (`--n_check_batches`, `--atol_fp32` / `--atol_fp16`). A printed
`WARNING: ... exceeded tolerance` means inspect before shipping — it isn't a
hard failure, since e.g. int8 on some weight distributions may legitimately
need a looser tolerance than the 0.05 default. This only covers the
PyTorch-vs-onnxruntime(CPU) half of the parity check; the onnxruntime-web
(browser) half happens in Phase 4.

## Sanity-checking a fresh environment before a long run

Before committing GPU-hours, it's worth confirming the environment actually
works end to end: build the model with `--no-pretrained` (skips the
imagenet-weights download), point `train.py` at a handful of tiny synthetic
images/masks (any small PNGs + a `manifest.csv` with `pass_filter=True`
rows), and run 1-2 epochs at `--img_size 64`. If that runs cleanly through
to a checkpoint, `export_onnx.py` against that checkpoint should too — that
exercises the whole pipeline (dataset -> model -> losses -> optimizer ->
checkpoint -> ONNX export -> parity check) without needing real data or much
compute.
