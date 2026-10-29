# Guide: adding your own model to VeriVoz

This guide is for someone who **has an anti-spoofing model trained in PyTorch (`.pth`)** and can program in Python. When you finish, your model will show up in the interface next to DF-Arena and XLSR-MLP: with its score in the breakdown, in the forensic timeline and in the threshold calibration.

> **Summary in 6 steps**
> 1. Inspect your `.pth` → `tools\inspect_pth.py`
> 2. Generate the plugin from the template → *Settings › Add model* (or `tools\create_model.py`)
> 3. Paste your architecture into `detector.py`
> 4. Adjust the preprocessing and the output in `detector.py`
> 5. Validate → *Validate* button (or `tools\validate_model.py`)
> 6. Enable it and, if you want, calibrate its threshold with your own audio

All commands are run from the project folder (the one containing `main.py`) with the virtual environment's Python: `.venv\Scripts\python`.

---

## 1. What you need

| You need | Why |
|---|---|
| The weights file (`.pth`, `.pt`, `.ckpt`, `.bin` or `.safetensors`) | These are the trained parameters. |
| **The code of the `nn.Module` class** you trained with (if the `.pth` is a *state_dict*) | A *state_dict* only stores numbers; PyTorch needs the class to know how to connect them. Not needed if your file is TorchScript (`torch.jit.save`). |
| The **exact preprocessing** used in training | Sample rate, normalization, cropping/padding, spectrograms, feature extractor... If it is not identical, the scores will be meaningless. |
| Knowing **which output index means "fake"** | Some people train with `0 = real, 1 = fake` and others use the ASVspoof convention `0 = spoof, 1 = bonafide`. |
| Any extra dependencies your model uses | They are installed into the `.venv` (see section 8). |

---

## 2. How a model works inside VeriVoz

Each model is a **plugin**: a folder inside `plugins/`.

```
plugins/
├── df_arena_1b/          ← example with a Hugging Face model (trust_remote_code)
├── xlsr_mlp/             ← example with a feature extractor + MLP
├── _template/            ← template (folders starting with "_" are ignored)
└── my_model/             ← YOUR PLUGIN
    ├── manifest.json     ← REQUIRED: metadata and configuration
    ├── detector.py       ← REQUIRED: class that loads the model and predicts
    └── weights/
        └── my_model.pth  ← your weights (or a path to them in manifest.json)
```

### Lifecycle (sequential analysis)

The application runs the models **one at a time** so the GPU is not overloaded:

```
for each enabled model:
    det = YourDetector(info, device)   # constructor: do not load anything heavy here
    det.load()                         # loads the weights onto det.device ("cuda" or "cpu")
    for each file:
        for each audio window:         # windows of analysis.window_seconds
            p = det.predict(window)    # or det.predict_batch([windows])
    det.unload()                       # frees VRAM before the next model
```

You do **not** deal with reading files, resampling, splitting into windows, combining scores or drawing anything: the application does that. Your detector only receives chunks of waveform and returns a probability.

### The `predict()` contract

| | |
|---|---|
| **Input** | `numpy.ndarray` `float32`, **mono**, values in **[-1, 1]**, at `sample_rate` Hz (the manifest's). Duration = `window_seconds` (or less if the audio is shorter). |
| **Output** | `float` between **0 and 1** = **probability that the audio is FAKE** (AI / manipulated). |

From that probability the application computes the 0-100 score (applying the model's threshold: the threshold always sits at 50), combines it with the other models and builds the timeline.

---

## 3. Step 1 — Inspect your `.pth`

```bat
.venv\Scripts\python tools\inspect_pth.py C:\path\to\my_model.pth
```

It tells you:

* the **format** (TorchScript, whole model, *state_dict* or checkpoint dictionary, and the key holding the weights);
* the **layers** with their shapes (names must match your class attributes);
* the **first layer** (does it take the raw waveform, a spectrogram or a feature vector?);
* the **last layer** (1 output → `sigmoid`, 2 outputs → `softmax`?);
* other data stored next to the weights (normalization statistics, threshold...).

Real example with the XLSR-MLP checkpoint:

```
Format: dictionary with several entries (checkpoint):
  · 'modelo': OrderedDict (9 keys, 9 tensors)
  · 'media': ndarray shape=(2048,)
  · 'desv': ndarray shape=(2048,)
  · 'umbral': float = 0.5969...
    · First layer with weights: red.0.weight -> Linear(in=2048, out=256)
    · Last layer with weights:  red.4.weight -> Linear(in=256, out=2)
    · The network expects a VECTOR of 2048 features, not the waveform ...
```

> ⚠ Opening a `.pth` that is not TorchScript uses *pickle*, which can execute code. Only do it with files you trust.

---

## 4. Step 2 — Generate the plugin

**From the interface:** *Settings (⚙) › Add model › Add model… › Create from a .pth*

| Field | What to enter |
|---|---|
| Display name | How it will appear in the breakdown (e.g. `My ResNet`). |
| Identifier (id) | Filled in automatically. Lowercase, digits, `_` or `-`. It becomes the folder name. |
| Weights file | Your `.pth`. |
| Sample rate | The one used in training (almost always 16000). |
| Analysis window | Seconds of audio your model expects per input (e.g. 4). |
| Copy the weights | Ticked: copied into `plugins/<id>/weights/`. Unticked: referenced where they are. |

**From the console** (equivalent):

```bat
.venv\Scripts\python tools\create_model.py --name "My ResNet" --pth C:\path\my_resnet.pth --sr 16000 --window 4
```

The plugin is created **disabled**: it will not take part in analyses until you validate and enable it.

---

## 5. Step 3 — Paste your architecture (`detector.py`, section "EDIT 1/3")

Open `plugins/<id>/detector.py` and replace the `MyNet` class with **the same class** you used for training. Attribute names must match the *state_dict* keys you saw in step 1.

```python
class MyNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Sequential(nn.Conv1d(1, 32, 251, stride=10), nn.ReLU(), nn.AdaptiveAvgPool1d(1))
        self.fc = nn.Linear(32, 2)

    def forward(self, x):            # x: (batch, samples)
        x = self.conv(x.unsqueeze(1)).squeeze(-1)
        return self.fc(x)            # logits (batch, 2)
```

If your architecture is spread over several files, copy them into the plugin folder and import them **relatively**:

```python
from .my_architecture import MyNet
```

> If your `.pth` is **TorchScript**, leave this alone: `load()` detects it and loads it without the class.
> If your keys have a `module.` (DataParallel) or `model.` (Lightning) prefix, `load()` tries removing them automatically.
> If your weights are inside a dictionary (`{"state_dict": ..., "epoch": ...}`), `load()` looks for the keys `state_dict`, `model_state_dict`, `model`, `modelo`, `net` and `weights`.

---

## 6. Step 4 — Adjust the output and the preprocessing

### "EDIT 2/3": what the output means

```python
FAKE_INDEX = 1        # index of the "fake" class
OUTPUT = "softmax"    # "softmax" (2+ logits) | "sigmoid" (1 logit) | "probability" (already 0-1)
INVERT = False        # True if your single output value means "real"
```

| Your model returns... | Configuration |
|---|---|
| 2 logits, trained with `0=real, 1=fake` | `OUTPUT="softmax"`, `FAKE_INDEX=1` |
| 2 logits, ASVspoof convention `0=spoof, 1=bonafide` (like DF-Arena) | `OUTPUT="softmax"`, `FAKE_INDEX=0` |
| 1 logit where high = fake | `OUTPUT="sigmoid"` |
| 1 logit where high = real (*bonafide* score) | `OUTPUT="sigmoid"`, `INVERT=True` |
| already a 0-1 probability of fake | `OUTPUT="probability"` |

### "EDIT 3/3": `preprocess()`

It receives the waveform of one window and must return **a tensor** ready for your network (without the batch dimension). Reproduce exactly what you did in training. The template pads by repetition up to the window length; some common examples:

```python
# Peak normalization
wave = wave / (np.abs(wave).max() + 1e-9)

# Log-mel spectrogram (needs torchaudio or librosa in the .venv)
import torchaudio
mel = torchaudio.transforms.MelSpectrogram(sample_rate=self.sample_rate, n_mels=80)
x = torch.log(mel(torch.from_numpy(wave)) + 1e-6)          # (80, frames)
return x.unsqueeze(0)                                       # (1, 80, frames) for a Conv2d
```

If you need expensive objects (a feature extractor, an SSL model, normalization statistics), create them in `load()` and keep them on `self`, like `plugins/xlsr_mlp/detector.py` does with `self.processor`, `self.ssl`, `self.mean` and `self.std`.

### Optional: `predict_batch()` for speed

The template already implements `predict_batch()` by stacking the windows. If your model supports batches, raise `analysis.batch_size` in the manifest (e.g. 8). If it only accepts one input at a time (like DF-Arena), keep `batch_size: 1`.

### Optional: `unload()`

The base class deletes everything you created in `load()` and empties the CUDA cache. Only override it if you open special resources (files, processes...).

---

## 7. `manifest.json` — full reference

```json
{
  "id": "my_resnet",
  "name": "My ResNet",
  "version": "1.0.0",
  "author": "Your name",
  "license": "MIT",
  "order": 100,
  "description": { "en": "ResNet on log-mel, trained on ...", "es": "ResNet sobre log-mel, entrenada en ..." },
  "entry_point": "detector.py:Detector",
  "sample_rate": 16000,
  "weight": 1.0,
  "default_threshold": 0.5,
  "analysis": {
    "window_seconds": 4.0,
    "forensic_window_seconds": 4.0,
    "forensic_hop_seconds": 1.0,
    "batch_size": 1
  },
  "files": { "checkpoint": "weights/my_resnet.pth" },
  "requirements": ["torch", "torchaudio"]
}
```

| Field | Required | Description |
|---|---|---|
| `id` | ✔ | Unique identifier: lowercase, digits, `_`, `-` (2-48). |
| `name` | ✔ | Display name. |
| `entry_point` | ✔ | `file.py:Class` of the detector, relative to the plugin folder. |
| `version`, `author`, `license` | | Informational (shown in Settings). |
| `description` | | Text or `{"en": ..., "es": ...}`. Shown in the breakdown. |
| `order` | | Position in the list (lower = earlier). Default 100. |
| `sample_rate` | | Hz of the waveform passed to `predict()`. Default 16000. |
| `weight` | | Weight of the model in the total score (weighted average). Default 1. |
| `default_threshold` | | Default threshold (0-1). 0.5 recommended. |
| `analysis.window_seconds` | | Length of each window in the standard analysis. `null` = whole file at once (not recommended for long audio). |
| `analysis.forensic_window_seconds` | | Window length of the forensic analysis. |
| `analysis.forensic_hop_seconds` | | Step between forensic windows (timeline resolution). |
| `analysis.batch_size` | | Windows per `predict_batch()` call. |
| `files` | | `{name: path}`. Relative to the plugin folder or absolute. Checked for existence and accessed with `self.file("name")`. |
| `downloads` | | Optional. Where to automatically download the `files` from (see section 7.1). |
| `hardware` | | Optional. Approximate specs shown before downloading and in Settings: `{"params_m": 440, "vram_gb": 3, "ram_gb": 8, "note": {"en": "...", "es": "..."}}`. |
| `family`, `family_name` | | Optional. Groups versions of the same model (e.g. `"df_arena"` / `"DF-Arena"` in the 1B and the 500M): the user chooses which one to download and only one is used at a time. |
| `requirements` | | Informational: packages your detector needs. |
| *other keys* | | Free: your detector reads them with `self.manifest["my_key"]`. |

### 7.1 Automatic weight download (`downloads`)

If you are going to publish your plugin (e.g. on GitHub, where files over 100 MB do not fit), do not include the weights: declare where to download them from. VeriVoz will show the user **what** is downloaded, **from where**, **its size** and **its license**, ask for consent (in the app or in `install.bat`) and verify the SHA-256 of every file. While files are missing, the model is shown as *To download*.

```json
"files": { "checkpoint": "weights/my_resnet.pth", "backbone": "weights/wav2vec2-base" },
"downloads": [
  {
    "name": "My ResNet weights",
    "type": "url",
    "url": "https://raw.githubusercontent.com/user/repo/<commit>/models/my_resnet.pth",
    "page": "https://github.com/user/repo",
    "target": "weights/my_resnet.pth",
    "size": 2130927,
    "sha256": "1cf2c180...",
    "license": "MIT",
    "license_url": "https://github.com/user/repo/blob/main/LICENSE"
  },
  {
    "name": "wav2vec2-base backbone",
    "type": "huggingface",
    "repo": "facebook/wav2vec2-base",
    "revision": "<Hugging Face commit>",
    "target": "weights/wav2vec2-base",
    "files": [
      { "path": "config.json", "size": 1840, "sha256": "..." },
      { "path": "pytorch_model.bin", "size": 380267417, "sha256": "..." }
    ],
    "license": "Apache-2.0",
    "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
    "requires_acceptance": false
  }
]
```

| Field | Description |
|---|---|
| `type` | `url` (one file) or `huggingface` (several files from a Hugging Face repository). |
| `target` | Where it is stored, relative to the plugin folder. Must match the path in `files`. |
| `revision` / commit in the URL | Pin it to a specific commit: what gets downloaded will not change even if the author updates the repository. |
| `size`, `sha256` | Size in bytes and hash. Used to know whether something is missing and to verify the download. |
| `requires_acceptance` | `true` if the license is restrictive: the user must explicitly accept it before downloading. |

How to get a file's size and SHA-256:

```bat
certutil -hashfile weights\my_resnet.pth SHA256
```

On Hugging Face, the public API (`https://huggingface.co/api/models/<repo>?blobs=true`) returns the size and SHA-256 of large files. To check what is missing or download it from the console: `python tools\download_models.py --list`.

> If you retrain your model and upload a new `.pth`, update the commit in the URL, `size` and `sha256` in the manifest.

### API available in your detector (`BaseDetector`)

| Attribute / method | Description |
|---|---|
| `self.device` | `"cuda"` or `"cpu"` (from *Settings › Processing*). Move your model and tensors there. |
| `self.sample_rate` | Rate of the waveform you receive. |
| `self.manifest` | Dictionary with the `manifest.json`. |
| `self.info` | Parsed manifest (`window_seconds`, `batch_size`, ...). |
| `self.plugin_dir` | Plugin folder (`Path`). |
| `self.file(key)` | Absolute path of a file in `files` (clear error if it does not exist). |
| `load()` | **Required.** Load the weights. |
| `predict(wave) -> float` | **Required.** Probability of fake for one window. |
| `predict_batch(waves) -> list[float]` | Optional. Calls `predict()` in a loop by default. |
| `unload()` | Optional. Free memory. |

---

## 8. Extra dependencies

If your detector imports packages that are not installed, install them into the application's virtual environment:

```bat
.venv\Scripts\python -m pip install torchaudio librosa timm
```

List them in the manifest's `requirements` so whoever receives your plugin knows what to install.

---

## 9. Step 5 — Validate

**From the interface:** *Settings › Installed models › Validate* (or the *Validate* button shown after creating the plugin).
**From the console:**

```bat
.venv\Scripts\python tools\validate_model.py my_resnet --audio C:\path\some_real_audio.wav
```

The validator checks, in order: the manifest; that `detector.py` imports and its class inherits from `BaseDetector`; that `load()` works on your device; that `predict()` returns a valid probability with 0.5 s, 3 s and 6 s signals (short, normal and long); that `predict_batch()` matches `predict()`; and, with `--audio`, the full score of an audio file as the interface would compute it.

```
✔ manifest.json is valid
✔ File 'checkpoint' found: ...\plugins\my_resnet\weights\my_resnet.pth
✔ Class 'Detector' imported and inherits from BaseDetector
✔ load() finished in 0.8 s (device: cuda)
✔ predict(noise 0.5 s) = 0.5353  (5 ms)
✔ predict(sweep 3 s) = 0.5489  (1 ms)
✔ predict(noise 6 s) = 0.5391  (1 ms)
✔ predict_batch() is consistent with predict()
✔ Test audio 'some_real_audio.wav': P(fake)=0.0123 · score=1.2/100 · 3 windows · 0.1 s
✔ unload() finished
✔ VALID
```

You can edit `detector.py` and validate again without restarting the application: the validator reloads the code every time.

> **Sanity check:** analyze a few files you know are real and a few you know are fake. If the real ones score high and the fake ones low, `FAKE_INDEX` is probably the wrong way round.

---

## 10. Step 6 — Enable and calibrate

1. *Settings › Installed models*: turn on your model's switch (or press *Enable model* in the validation dialog).
2. (Optional) *Settings › Decision threshold › Calibrate with my audio…*: add real and fake files similar to the ones you will analyze. The equal error rate (EER) threshold of each model is computed and you can apply it. At least 10 of each kind are recommended.

If changes to `manifest.json` are not picked up, press *Settings › Add model › Reload models*.

---

## 11. Importing a ready-made plugin

If someone gives you a complete plugin folder (with `manifest.json`, `detector.py` and weights): *Settings › Add model › Add model… › Import existing plugin*. It is copied into `plugins/` (`files` paths that pointed outside the folder become absolute) and the validator opens. You can also copy the folder into `plugins/` by hand and press *Reload models*.

## 12. Removing a model

*Settings › Danger zone › Remove model…*: choose the model and type its `id` to confirm. By default the plugin folder is **moved** to `user_data/deleted/` (recoverable: move it back to `plugins/`); tick *Delete permanently* to erase it. Files referenced **outside** the plugin folder are never touched.

---

## 13. Reference examples

| Case | Look at |
|---|---|
| *state_dict* + your own class on the waveform | `plugins/_template/detector.py` (the template) |
| SSL extractor + classifier + statistics from the checkpoint | `plugins/xlsr_mlp/detector.py` |
| Hugging Face model with `trust_remote_code` | `plugins/df_arena_1b/detector.py` |
| Automatic download from GitHub and Hugging Face | `downloads` in `plugins/xlsr_mlp/manifest.json` |
| License that requires acceptance (non-commercial) | `downloads` in `plugins/df_arena_1b/manifest.json` |
| Several versions of the same model with their specs | `family` and `hardware` in `plugins/df_arena_1b` and `plugins/df_arena_500m` |

---

## 14. Common errors

| Message | Cause and fix |
|---|---|
| `Paste your model architecture into detector.py` | You have not replaced the `MyNet` class yet (step 3). |
| `Missing key(s) in state_dict` / `Unexpected key(s)` | Your class does not match the training one: different attribute names, extra or missing layers. Compare with `inspect_pth.py`. |
| `size mismatch for ...` | Same names but different dimensions (e.g. `n_mels`, number of channels or classes). |
| `predict(...) = 1.3: it must be a probability between 0 and 1` | You return logits without softmax/sigmoid: check `OUTPUT`. |
| `mat1 and mat2 shapes cannot be multiplied` | The preprocessing does not produce what the first layer expects. Check `preprocess()`. |
| `Expected all tensors to be on the same device` | A tensor created in `load()`/`preprocess()` is not on `self.device`. Use `.to(self.device)`. |
| `CUDA out of memory` | Lower `batch_size` or `window_seconds`, or use the CPU in *Settings › Processing*. |
| `ModuleNotFoundError: No module named 'x'` | Install the dependency into the `.venv` (section 8). For your own modules use relative imports (`from .module import ...`). |
| `'id' only allows lowercase letters...` | Fix `id` in the manifest. |
| `File not found 'checkpoint'` | The `files` path is wrong. Relative paths start at the plugin folder. |
| `predict_batch and predict disagree` (warning) | Your preprocessing depends on the batch (padding, batch normalization, unseeded random noise). Fix the seeds or keep `batch_size: 1`. |

---

## 15. Final checklist

- [ ] `plugins/<id>/manifest.json` with `id`, `name` and `entry_point`.
- [ ] `plugins/<id>/detector.py` with a class inheriting from `BaseDetector` that implements `load()` and `predict()`.
- [ ] Weights in `plugins/<id>/weights/` or the right path in `files`.
- [ ] (If you will publish it) `downloads` with the source, `size`, `sha256` and license of every file.
- [ ] `sample_rate` and `window_seconds` equal to training.
- [ ] Preprocessing identical to training.
- [ ] `predict()` returns the probability of **fake** (not of real).
- [ ] Validation all green.
- [ ] Model enabled in *Settings › Installed models*.
- [ ] (Optional) threshold calibrated with your own audio.
