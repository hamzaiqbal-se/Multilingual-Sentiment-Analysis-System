import os
import torch
import torch.nn.functional as F
from transformers import XLMRobertaForSequenceClassification, XLMRobertaTokenizer

class SentimentModelHandler:
    def __init__(self, model_dir):
        """
        Initializes the XLM-RoBERTa Sentiment Analysis Engine.
        Optimized for English & Roman Urdu (3-Lakh samples).
        """
        self.model_dir = model_dir
        self.device = torch.device("cpu")  # Forced CPU for stability on Ryzen 7
        self.model = None
        self.tokenizer = None
        self.is_loaded = False
        self._load_model()

    def _load_model(self):
        # Check if the directory exists and contains config.json
        config_path = os.path.join(self.model_dir, "config.json")
        
        if not os.path.exists(config_path):
            print(f"[ModelHandler] ERROR: Config not found at {config_path}")
            print(f"[ModelHandler] Current Directory: {os.getcwd()}")
            return
            
        try:
            print(f"[ModelHandler] Loading XLM-RoBERTa from: {self.model_dir}")
            
            # Loading Tokenizer and Model
            self.tokenizer = XLMRobertaTokenizer.from_pretrained(self.model_dir, local_files_only=True)
            self.model = XLMRobertaForSequenceClassification.from_pretrained(self.model_dir, local_files_only=True)
            
            self.model.to(self.device)
            self.model.eval()
            self.is_loaded = True
            print("[ModelHandler] OK: FYP Sentiment Engine (XLM-R) ready.")
        except Exception as e:
            print(f"[ModelHandler] FATAL: Model load failed: {e}")
            self.is_loaded = False

    def predict(self, text):
        if not self.is_loaded or self.model is None:
            return {"sentiment": "Neutral", "confidence": 0.0, "clarity": 0.0, "raw_scores": {}}

        try:
            # 1. Tokenization
            inputs = self.tokenizer(
                text, 
                return_tensors="pt", 
                truncation=True, 
                max_length=128, 
                padding=True
            ).to(self.device)

            # 2. Inference with Temperature Scaling (T=1.5)
            with torch.no_grad():
                outputs = self.model(**inputs)
                logits = outputs.logits
                
                # Sharpen emotional nuances
                scaled_logits = logits / 1.5
                probs = F.softmax(scaled_logits, dim=-1).squeeze().tolist()

            # Mapping: 0: Negative, 1: Neutral, 2: Positive
            p_neg, p_neu, p_pos = probs

            # 3. Dynamic Neutral Penalty Logic (Redistribution)
            if p_neu > p_neg and p_neu > p_pos and p_neu < 0.90:
                penalty = 0.40
                p_neu -= penalty
                
                emotional_sum = p_neg + p_pos
                if emotional_sum > 0:
                    neg_ratio = p_neg / emotional_sum
                    pos_ratio = p_pos / emotional_sum
                else:
                    neg_ratio = pos_ratio = 0.5
                
                p_neg += penalty * neg_ratio
                p_pos += penalty * pos_ratio
                print(f"[ModelHandler] Neutral Penalty Triggered.")

            # Final Winner Selection
            final_scores = {'LABEL_0': p_neg, 'LABEL_1': p_neu, 'LABEL_2': p_pos}
            sorted_scores = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
            
            winner_label, winner_score = sorted_scores[0]
            runner_up_label, runner_up_score = sorted_scores[1]

            mapping = {'LABEL_0': 'Negative', 'LABEL_1': 'Neutral', 'LABEL_2': 'Positive'}
            sentiment = mapping.get(winner_label, 'Neutral')
            clarity = abs(winner_score - runner_up_score)

            return {
                "sentiment": sentiment,
                "confidence": round(winner_score, 4),
                "clarity": round(clarity, 4),
                "raw_scores": final_scores
            }
            
        except Exception as e:
            print(f"[ModelHandler] Prediction error: {e}")
            return {"sentiment": "Neutral", "confidence": 0.0, "clarity": 0.0, "raw_scores": {}}

# --- Path Logic ---
# Yeh line automatically 'model_assets' ka sahi rasta nikaal legi
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "model_assets")

# Check if the folder name is actually 'model_assets' as per your sidebar
if not os.path.exists(MODEL_PATH):
    # Fallback if the folder is named 'assets'
    MODEL_PATH = os.path.join(BASE_DIR, "assets")

model_handler = SentimentModelHandler(MODEL_PATH)

def get_model_prediction(text):
    return model_handler.predict(text)