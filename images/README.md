# Article Images

This directory contains locally cached images for HelpAGI articles.

## Images

- **agi-vs-narrow-ai.jpg** - AGI vs Narrow AI article hero image
- **ai-agents.jpg** - AI Agents and Autonomous Systems article hero image  
- **docker.jpg** - Docker tutorial article hero image
- **llm-fine-tuning.jpg** - LLM Fine-Tuning Guide article hero image
- **multimodal-ai.jpg** - Multimodal AI Revolution article hero image
- **transformer-architecture.jpg** - Transformer Architecture article hero image

## Usage

These images are automatically downloaded from Unsplash and cached locally. They serve as:
1. **Fallback images** when network is unavailable
2. **Local cache** for faster loading
3. **Offline support** for the app

## Updating Images

To re-download all images:
```bash
./scripts/download_images.sh
```

## Source

All images are sourced from [Unsplash](https://unsplash.com) with proper licensing.
