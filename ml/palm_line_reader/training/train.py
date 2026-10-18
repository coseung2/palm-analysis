#!/usr/bin/env python3
"""Phase 2 -- student training loop. See ../plan.md.

Run on the GPU box after scp'ing this training_pack/ directory (with data/
populated by generate_pseudo_labels.py) over:

    python train.py --data_dir data --out_dir runs/exp1 --epochs 150 --batch_size 16
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from dataset import PalmLineDataset, build_train_transform, build_val_transform, split_stems
from losses import LINE_NAMES, PalmLineLoss, line_classes
from metrics import component_counts, dice_per_class, mean_skeleton_distance_px, single_component_rate
from model import build_student_model

CLASS_COLORS = {0: (0, 0, 0), 1: (255, 0, 0), 2: (0, 0, 255), 3: (0, 255, 0), 4: (255, 200, 0)}
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data_dir", default="data")
    ap.add_argument("--out_dir", default="runs/exp1")
    ap.add_argument("--encoder", default="mit_b0")
    ap.add_argument("--pretrained", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--img_size", type=int, default=512)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--batch_size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--weight_decay", type=float, default=1e-4)
    ap.add_argument("--val_fraction", type=float, default=0.1)
    ap.add_argument("--num_workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cldice_weight", type=float, default=0.5)
    ap.add_argument("--distance_weight", type=float, default=0.3)
    ap.add_argument("--distance_warmup_epochs", type=int, default=0)
    ap.add_argument("--distance_max_px", type=float, default=32.0)
    ap.add_argument("--connectivity_weight", type=float, default=0.1)
    ap.add_argument("--connectivity_warmup_epochs", type=int, default=5)
    ap.add_argument("--num_lines", type=int, choices=(3, 4), default=3, help="4 adds the fate line (mask value 4)")
    ap.add_argument(
        "--class_weights",
        default="1,1,1,2",
        help="comma-separated, background first; default doubles the life line, the weakest class of exp2. "
        "Use one more value with --num_lines 4.",
    )
    ap.add_argument(
        "--strong_aug",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="wide zoom/close-up/rotation and camera degradations (see dataset.py); --no-strong_aug is exp2",
    )
    ap.add_argument(
        "--select_metric",
        choices=("fg_dice", "min_line_dice"),
        default="min_line_dice",
        help="checkpoint selection; min_line_dice stops a strong heart/head average hiding a weak life line",
    )
    ap.add_argument("--val_every", type=int, default=1)
    ap.add_argument("--save_every", type=int, default=10)
    ap.add_argument(
        "--overlay_samples", type=int, default=4, help="val images to dump overlays for at each validation pass"
    )
    ap.add_argument("--resume", default=None)
    ap.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--device", default=None)
    return ap.parse_args()


def denormalize_to_uint8(img_chw: np.ndarray) -> np.ndarray:
    img = img_chw.transpose(1, 2, 0) * IMAGENET_STD + IMAGENET_MEAN
    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


def colorize_mask(mask: np.ndarray) -> np.ndarray:
    out = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for c, color in CLASS_COLORS.items():
        if c == 0:
            continue
        out[mask == c] = color
    return out


def save_overlay(image_chw: np.ndarray, pred_mask: np.ndarray, target_mask: np.ndarray, path: Path) -> None:
    from PIL import Image

    base = denormalize_to_uint8(image_chw)

    def blend(color_mask: np.ndarray) -> np.ndarray:
        out = base.copy()
        m = np.any(color_mask > 0, axis=2)
        out[m] = (base[m].astype(np.float32) * 0.5 + color_mask[m].astype(np.float32) * 0.5).astype(np.uint8)
        return out

    combined = np.concatenate([base, blend(colorize_mask(target_mask)), blend(colorize_mask(pred_mask))], axis=1)
    Image.fromarray(combined).save(path)


@torch.no_grad()
def run_validation(model, loader, device, epoch, overlay_dir, overlay_samples, distance_max_px, num_classes, foreground):
    model.eval()
    dice_sums = {c: 0.0 for c in range(num_classes)}
    n_batches = 0
    all_counts = {c: [] for c in foreground}
    dist_sums = {c: 0.0 for c in foreground}
    dist_n = {c: 0 for c in foreground}
    overlays_saved = 0

    for images, targets in loader:
        images = images.to(device)
        targets = targets.to(device)
        logits = model(images)
        pred = torch.argmax(logits, dim=1)

        d = dice_per_class(pred, targets, num_classes)
        for c in range(num_classes):
            dice_sums[c] += d[c]
        n_batches += 1

        counts = component_counts(pred, foreground)
        for c in foreground:
            all_counts[c].extend(counts[c])

        dists = mean_skeleton_distance_px(pred, targets, foreground, distance_max_px)
        for c in foreground:
            if not np.isnan(dists[c]):
                dist_sums[c] += dists[c]
                dist_n[c] += 1

        if overlay_dir is not None and overlays_saved < overlay_samples:
            images_np = images.cpu().numpy()
            pred_np = pred.cpu().numpy()
            targets_np = targets.cpu().numpy()
            for i in range(images_np.shape[0]):
                if overlays_saved >= overlay_samples:
                    break
                save_overlay(
                    images_np[i],
                    pred_np[i],
                    targets_np[i],
                    overlay_dir / f"epoch{epoch:04d}_sample{overlays_saved:02d}.png",
                )
                overlays_saved += 1

    mean_dice = {c: dice_sums[c] / max(1, n_batches) for c in range(num_classes)}
    rates = single_component_rate(all_counts)
    mean_dists = {c: (dist_sums[c] / dist_n[c] if dist_n[c] else float("nan")) for c in foreground}
    return mean_dice, rates, mean_dists


def save_checkpoint(path, model, optimizer, scheduler, epoch, best_val_dice, args):
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "epoch": epoch,
            "best_val_dice": best_val_dice,
            "encoder": args.encoder,
            "img_size": args.img_size,
            "num_lines": args.num_lines,
            "select_metric": args.select_metric,
        },
        path,
    )


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device = (
        torch.device(args.device) if args.device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
    )
    print(f"device: {device}")

    out_dir = Path(args.out_dir)
    ckpt_dir = out_dir / "checkpoints"
    overlay_dir = out_dir / "val_overlays"
    for d in (ckpt_dir, overlay_dir):
        d.mkdir(parents=True, exist_ok=True)

    train_stems, val_stems = split_stems(args.data_dir, val_fraction=args.val_fraction, seed=args.seed)
    print(f"train: {len(train_stems)} samples, val: {len(val_stems)} samples")

    num_classes, foreground = line_classes(args.num_lines)
    names = {c: LINE_NAMES[c - 1] for c in foreground}
    class_weights = [float(v) for v in args.class_weights.split(",")] if args.class_weights else None

    train_ds = PalmLineDataset(
        args.data_dir, build_train_transform(args.img_size, strong=args.strong_aug), stems=train_stems
    )
    val_ds = PalmLineDataset(args.data_dir, build_val_transform(args.img_size), stems=val_stems)

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=(device.type == "cuda"),
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=max(1, args.batch_size // 2),
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=(device.type == "cuda"),
    )

    model = build_student_model(
        encoder_name=args.encoder, encoder_weights=("imagenet" if args.pretrained else None), classes=num_classes
    ).to(device)
    loss_fn = PalmLineLoss(
        num_classes=num_classes,
        foreground_classes=foreground,
        class_weights=class_weights,
        cldice_weight=args.cldice_weight,
        distance_weight=args.distance_weight,
        distance_warmup_epochs=args.distance_warmup_epochs,
        distance_max_px=args.distance_max_px,
        connectivity_weight=args.connectivity_weight,
        connectivity_warmup_epochs=args.connectivity_warmup_epochs,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    use_amp = args.amp and device.type == "cuda"
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)

    start_epoch = 0
    best_val_dice = -1.0
    if args.resume:
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        scheduler.load_state_dict(ckpt["scheduler"])
        start_epoch = ckpt["epoch"] + 1
        best_val_dice = ckpt.get("best_val_dice", -1.0)
        print(f"resumed from {args.resume} at epoch {start_epoch}")

    log_path = out_dir / "train_log.csv"
    log_fields = [
        "epoch",
        "train_total",
        "train_ce",
        "train_dice",
        "train_cldice",
        "train_distance",
        "train_connectivity",
        "val_dice_bg",
        *[f"val_dice_{n}" for n in names.values()],
        "val_fg_dice",
        "val_min_line_dice",
        *[f"single_comp_{n}" for n in names.values()],
        *[f"dist_{n}_px" for n in names.values()],
        "lr",
        "seconds",
    ]
    write_header = not log_path.exists()
    log_file = open(log_path, "a", newline="")
    log_writer = csv.DictWriter(log_file, fieldnames=log_fields)
    if write_header:
        log_writer.writeheader()

    for epoch in range(start_epoch, args.epochs):
        t0 = time.time()
        loss_fn.set_epoch(epoch)
        model.train()

        running = {"total": 0.0, "ce": 0.0, "dice": 0.0, "cldice": 0.0, "distance": 0.0, "connectivity": 0.0}
        n_steps = 0

        for images, targets in train_loader:
            images = images.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device.type, enabled=use_amp):
                logits = model(images)
                out = loss_fn(logits, targets)
                loss = out["total"]

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            running["total"] += loss.item()
            for k in ("ce", "dice", "cldice", "distance", "connectivity"):
                running[k] += float(out[k])
            n_steps += 1

        scheduler.step()
        for k in running:
            running[k] /= max(1, n_steps)

        row = {
            "epoch": epoch,
            "train_total": running["total"],
            "train_ce": running["ce"],
            "train_dice": running["dice"],
            "train_cldice": running["cldice"],
            "train_distance": running["distance"],
            "train_connectivity": running["connectivity"],
            "lr": optimizer.param_groups[0]["lr"],
        }

        if (epoch + 1) % args.val_every == 0 or epoch == args.epochs - 1:
            mean_dice, rates, mean_dists = run_validation(
                model,
                val_loader,
                device,
                epoch,
                overlay_dir,
                args.overlay_samples,
                args.distance_max_px,
                num_classes,
                foreground,
            )
            fg_dice = float(np.mean([mean_dice[c] for c in foreground]))
            min_line_dice = float(min(mean_dice[c] for c in foreground))
            row["val_dice_bg"] = mean_dice[0]
            row["val_fg_dice"] = fg_dice
            row["val_min_line_dice"] = min_line_dice
            for c, n in names.items():
                row[f"val_dice_{n}"] = mean_dice[c]
                row[f"single_comp_{n}"] = rates[c]
                row[f"dist_{n}_px"] = mean_dists[c]
            print(
                f"epoch {epoch}: train_total={running['total']:.4f} val_fg_dice={fg_dice:.4f} "
                f"min_line_dice={min_line_dice:.4f} "
                + " ".join(
                    f"{n}(dice={mean_dice[c]:.3f} single={rates[c]:.2f} dist={mean_dists[c]:.1f}px)"
                    for c, n in names.items()
                )
            )

            score = min_line_dice if args.select_metric == "min_line_dice" else fg_dice
            if score > best_val_dice:
                best_val_dice = score
                save_checkpoint(ckpt_dir / "best.pt", model, optimizer, scheduler, epoch, best_val_dice, args)
        else:
            print(f"epoch {epoch}: train_total={running['total']:.4f}")

        row["seconds"] = time.time() - t0
        log_writer.writerow(row)
        log_file.flush()

        if (epoch + 1) % args.save_every == 0 or epoch == args.epochs - 1:
            save_checkpoint(ckpt_dir / f"epoch{epoch:04d}.pt", model, optimizer, scheduler, epoch, best_val_dice, args)

    log_file.close()
    print(f"done. best val {args.select_metric}: {best_val_dice:.4f}. checkpoints in {ckpt_dir}")


if __name__ == "__main__":
    main()
