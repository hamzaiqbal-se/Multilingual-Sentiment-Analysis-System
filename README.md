# Multilingual Sentiment Analysis & Opinion Mining Engine

An advanced Deep Learning-powered Sentiment Analysis system leveraging the state-of-the-art **XLM-RoBERTa** architecture. While natively utilizing cross-lingual language representations across 100+ languages, this engine is fine-tuned and benchmarked to evaluate emotional nuances in complex multilingual contexts, including English and Roman Urdu.

---

## 🚀 Core Architectural Features

To bridge the gap between casual text and deep machine understanding, this engine implements two custom mathematical layers over the standard Transformer outputs:

### 1. Temperature Scaling ($T = 1.5$)
Standard soft-max probabilities can often be overconfident or heavily biased toward "Neutral" classifications in multilingual setups. We implement a temperature scaling factor:
$$\text{Scaled Logits} = \frac{\text{Logits}}{T}$$
This flattens the distribution slightly, sharpening the model's sensitivity to subtle emotional indicators in Roman Urdu slang.

### 2. Dynamic Neutral Penalty Logic
Standard pre-trained models tend to default to a "Safe Neutral" whenever context features overlap across languages. To combat this, a custom threshold heuristic is injected into the pipeline:
* **Trigger:** If `Neutral` is the predicted winner but its confidence score is $< 90\%$.
* **Action:** A localized penalty of $40\%$ ($0.40$) is deducted from the Neutral score.
* **Redistribution:** The deducted weight is dynamically redistributed to the `Positive` and `Negative` channels relative to their initial probabilistic weights.

---

## 🛠️ Tech Stack & Frameworks

* **Core AI Layer:** PyTorch, HuggingFace Transformers, SentencePiece Tokenizer
* **Model Base:** XLM-RoBERTa (Cross-lingual Language Model trained on 100+ languages)
* **Backend Pipeline:** Python 3.10+, Flask, Flask-SQLAlchemy (SQLite)
* **Data Visualization:** Matplotlib, WordCloud (Generates real-time visual frequency analysis of user submissions)
* **Frontend GUI:** HTML5, CSS3, JavaScript, Bootstrap 5

---

## 📂 Repository Blueprint

```text
├── model_assets/          # Local storage for Pre-trained XLM-R Weights (Excluded from Git)
├── static/                # Custom CSS styles, core UI images, and client-side JavaScript
├── templates/             # Bootstrap-powered HTML user interfaces (Dashboard, Analytics)
├── app.py                 # Core Flask application & server routing gateway
├── model_handler.py       # Engine Room: Houses XLM-R tokenization & Neutral Penalty logic
├── sentiment_engine.py    # Analytics Layer: Generates live datasets & graphical WordClouds
├── models.py              # Database Schema configurations (SQLite pipeline)
├── requirements.txt       # Unified list of core dependencies and packages
└── README.md              # Documentation
