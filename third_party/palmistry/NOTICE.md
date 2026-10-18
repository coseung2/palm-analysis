# Personal experimental palm-line adapter

Source: https://github.com/yeonsumia/palmistry
Pinned commit: 17610c3f031ee312d3352116eefff9b833e9cafb
Checkpoint: code/checkpoint/checkpoint_aug_epoch70.pth (55,490,203 bytes)
SHA256: 8493d6dc2fa772cd919ddbb9a907d4dd194b8f480f2adeca14ca844140092daf

The repository root supplies Apache-2.0. Its code/model.py attributes
https://github.com/milesial/Pytorch-UNet, whose current license is GPL-3.0.
The adapter's checkpoint-compatible network is adapted from that architecture.
Both source license texts are retained here. This notice does not resolve the
code/checkpoint/training-data provenance or grant additional permissions.
User authorized personal experimental use, not redistribution clearance.

Changes: CPU-only restricted weights loading; strict tensor matching; eval and
inference modes; memory-only PNG overlay; empty/dense prediction suppression;
no palmistry conclusions, no fate-line classification, no photo files or logs.
The upstream raw-logit 0.03 cutoff and nearest-neighbor 256px input are retained.
The adapter uses the existing ROI crop, NOT the upstream full homography and
background-removal pipeline. Real-photo generalization remains unmeasured.
Set PALM_LINE_MODEL_PATH to an explicitly provisioned checkpoint to enable.
Absent/bad checkpoint/runtime yields ordinary original-image analysis.
