---
name: invokeai
description: Use when the user wants to generate or edit images locally without a per-image inference API charge, or asks for a beginner-friendly local image-generation setup with InvokeAI.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
volte_usata: 1
---

# Local Image Generation with InvokeAI

InvokeAI is a free, open-source application for running image models on the user's computer. Local generation avoids a provider's per-image API charge; it still uses the computer's hardware, electricity, disk space, and model downloads. InvokeAI can also connect to external models that may be billed, so confirm that generation is local.

## Before setup

1. Clarify whether the user wants local generation or a hosted service. Choose this skill for local generation; use the `image_gen` tool when a hosted provider is fine (see below), and `huggingface-image-gen` only when they specifically want Hugging Face Inference.
2. Check whether InvokeAI is already installed before proposing installation. If installation is needed, explain that it downloads software and large model files and get the user's confirmation before installing or changing system/network settings.
3. Check the current [InvokeAI system requirements](https://invoke.ai/start-here/system-requirements/) for the selected model and operating system. Requirements vary by model and resolution; as rough Windows/Linux guidelines, the official table lists SD 1.5 at 4 GB VRAM / 8 GB RAM, SDXL at 8 GB VRAM / 16 GB RAM, and FLUX.1 at 10 GB VRAM / 32 GB RAM. Lower-memory operation may be slower and is not guaranteed to work for every model.
4. If hardware is uncertain, ask for the GPU model, VRAM, system RAM, free disk space, and Windows version before recommending a model. Do not promise that a particular GPU or CPU-only setup will work from these rough figures alone. Invoke's current docs differ on Windows GPU support; do not assume AMD-on-Windows support without checking the latest requirements.

## Install and launch on Windows

1. Use the official [InvokeAI download page](https://invoke.ai/download/) and its Windows Invoke Launcher installer. Do not install from an unofficial mirror.
2. After the user approves installation, run the installer and open the Invoke Launcher. In the Launcher, choose **Install**, follow its prompts, and then launch the created installation from the Launcher or desktop shortcut.
3. Use the Launcher to install or select a model that fits the available hardware. Check that model's license and any usage restrictions in its official model documentation before use, especially for commercial work. The InvokeAI software license does not grant rights to model weights.
4. Generate a small test image first. Verify the output file exists, opens, and is saved in the location the user expects before reporting success.

## When `image_gen` is the simpler answer

Orchestra has a built-in `image_gen` tool: it calls OpenAI Images, Google
Gemini, or OpenRouter with a key that is already configured in the Opzioni
panel and saves the file under `immagini/` in the project. It needs no
installation and returns the image to the chat. OpenRouter exposes many
image models (FLUX, Seedream, GPT Image, Gemini): set `provider="openrouter"`
and pass the catalog slug in `modello`, and call it once with
`elenco_modelli=true` to list the slugs and see which models accept a
reference image. It also edits an existing image: pass a project path, a data
URL, or `ultimo` to use the image the user just attached. It bills per image
or in image tokens on the provider account (OpenRouter has no free image
model), so state that before calling it and never present it as free. Use this
skill instead when the user wants generation on their own machine, without a
per-image charge, and has the hardware for it.

## Choose the right free option

- **Local InvokeAI:** no per-image inference service fee when using a locally installed model; requires compatible hardware, disk space, and time for downloads.
- **Hosted APIs (`image_gen`):** billed per image or per image token on the provider account. Free credits and trials can change, and outputs may have privacy, commercial-use, or public-display restrictions; verify current official pricing and terms before promising "free".
- Never describe a free software download as unlimited free generation, and never imply the model itself is unrestricted.

## Rules

- Never install software, download multi-gigabyte models, change network settings, or create a hosted account without the user's informed approval.
- Keep API keys out of prompts, scripts, shell history, and generated outputs. Local-only workflows do not need an API key.
- Do not upload a user's private image to a hosted provider without explicit consent; local processing is the privacy-preserving choice only if the selected workflow really runs locally.
- If requirements, model availability, pricing, or licensing have changed, check the official links above rather than relying on old instructions.
