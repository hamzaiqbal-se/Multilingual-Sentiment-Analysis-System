import os
import uuid
import re
import json
import numpy as np
from langdetect import detect
from wordcloud import WordCloud
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
from model_handler import get_model_prediction

def preprocess_text(text):
    text = text.lower()
    text = ' '.join(text.split())
    return text

def extract_emojis(text):
    uplifting_emojis = ['❤️', '😍', '🥰', '🚀', '🔥', '✨', '💎', '✅', '🌟', '🙌', '👏', '🥳', '🏆', '🥇', '🤩', '💖', '💯', '🔝', '📈', '😇', '😎', '🤝', '🍭', '🌈', '☀️', '🎈', '🎉', '🎊', '🪄', '🦾', '🔋', '🆙']
    critical_emojis = ['😡', '🤮', '👎', '❌', '💀', '🚫', '📉', '💩', '🗑️', '🤬', '🖕', '🙄', '💔', '🥀', '⚠️', '🆘', '😠', '🤢', '🤡', '👺', '💣', '⛈️', '🧊', '🕳️', '🩹', '⛔', '🔞', '🔇', '☣️', '☢️']
    
    found_pos = [char for char in text if char in uplifting_emojis]
    found_neg = [char for char in text if char in critical_emojis]
    
    return found_pos, found_neg

def generate_wordcloud(tokens, positive_words, negative_words):
    if not tokens or len(tokens) < 2:
        return None
        
    text = " ".join(tokens)
    
    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        if word in positive_words: return "green"
        elif word in negative_words: return "red"
        return "gray"
    
    try:
        wordcloud = WordCloud(width=800, height=400, background_color='white', color_func=color_func).generate(text)
        buffer = io.BytesIO()
        plt.figure(figsize=(8, 4))
        plt.imshow(wordcloud, interpolation='bilinear')
        plt.axis('off')
        plt.savefig(buffer, format='png', bbox_inches='tight', pad_inches=0)
        plt.close()
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"WordCloud error: {e}")
        return None

def analyze_text_logic(text):
    prediction_result = get_model_prediction(text)
    
    # Handle error or missing model
    if prediction_result.get('raw_label') == 'ERROR':
        return {
            'sentiment': 'Neutral',
            'polarity': 0.0,
            'confidence': 0,
            'clarity': 0,
            'positive_words': [],
            'negative_words': [],
            'language': 'UNKNOWN',
            'recommended_action': "Model error or not loaded.",
            'tokens': [],
            'wordcloud_base64': None
        }

    cleaned = preprocess_text(text)
    
    # Language Detection (Prioritizing EN and PK)
    words_set = set(cleaned.split())
    roman_urdu_markers = {'hai', 'hain', 'ki', 'ka', 'ko', 'se', 'yeh', 'woh', 'bhi', 'nahi', 'kya', 'aur', 'mein', 'par', 'kese', 'kesa', 'karta', 'karti', 'acha', 'achi', 'bohat', 'bohot', 'sirf', 'zabardast', 'bakwas', 'shukriya', 'theek', 'ho', 'mubarak', 'ala', 'mazay', 'boht'}
    english_common = {'the', 'is', 'at', 'which', 'on', 'this', 'that', 'with', 'from', 'but', 'not', 'very', 'good', 'bad'}
    
    if any(word in words_set for word in roman_urdu_markers):
        language = 'PK'
    elif any(word in words_set for word in english_common):
        language = 'EN'
    else:
        try:
            detected = detect(text).upper()
            # If detected as common false positives for Roman Urdu, force PK
            if detected in ['ID', 'TL', 'TR', 'SO']:
                language = 'PK'
            else:
                language = detected
        except:
            language = 'EN' # Default to EN

    # Extract base variables
    sentiment = prediction_result.get('sentiment', 'Neutral')
    score = prediction_result.get('confidence', 0.0)
    clarity = prediction_result.get('clarity', 0.0)
    raw_scores = prediction_result.get('raw_scores', {})

    # Extract emojis for overrides
    pos_emojis, neg_emojis = extract_emojis(text)

    # Logic Overrides Setup
    text_lower = text.lower()
    negative_keywords = ['bakwas', 'bura', 'fazool', 'worst', 'ghatiya', 'hate', 'bad', 'terrible', 'awful', 'zaya', 'bekar', 'crash', 'freezing', 'hang']
    positive_keywords = ['mubarak', 'ala', 'zabardast', 'best', 'smooth', 'excellent', 'love', 'good', 'happy']
    
    has_negative_keywords = any(w in text_lower for w in negative_keywords)
    has_positive_keywords = any(w in text_lower for w in positive_keywords)
    
    # Final Sentiment Calculation (including engine-level anchors)
    if has_positive_keywords and 'Negative' in sentiment:
        sentiment = 'Positive'
        score = 0.85
    elif has_negative_keywords and 'Positive' in sentiment:
        sentiment = 'Negative'
        score = 0.85
    
    polarity = score if 'Positive' in sentiment else (-score if 'Negative' in sentiment else 0.0)
    confidence = int(round(max(60, min(99, score * 100))))

    # Strong/Regular classification
    if sentiment == 'Positive' and score >= 0.8:
        sentiment = 'Strong Positive'
    elif sentiment == 'Negative' and score >= 0.8:
        sentiment = 'Strong Negative'

    # ENGINE OVERRIDES (Post-Model Intelligence)
    if 'Positive' in sentiment and has_negative_keywords:
        sentiment = 'Negative'
        polarity = -0.6
        confidence = 85
        print("[SentimentEngine OVERRIDE] Forced Negative due to keywords.")

    if len(neg_emojis) > 0:
        sentiment = 'Strong Negative' if len(neg_emojis) > 1 else 'Negative'
        polarity = -0.8
        confidence = 95
        print("[SentimentEngine OVERRIDE] Forced Negative due to emojis.")

    # Rule-Based Recommendation Engine (Dynamic)
    # Check if negative probability is high even if not winner
    neg_prob = raw_scores.get('LABEL_0', 0)
    
    if neg_prob > 0.4:
        rec = "Potential Issue Detected: Low-level negative signals found."
    elif 'Positive' in sentiment:
        rec = "Feature highlighted for marketing"
    elif 'Negative' in sentiment:
        rec = "Customer support follow-up required" if 'Strong' in sentiment else "Check for system bugs"
    else:
        rec = "General information/Fact"

    # Tokens and WordCloud
    tokens = cleaned.split()
    if 'Positive' in sentiment:
        positive_words = tokens + pos_emojis
        negative_words = neg_emojis
    elif 'Negative' in sentiment:
        positive_words = pos_emojis
        negative_words = tokens + neg_emojis
    else:
        positive_words = pos_emojis
        negative_words = neg_emojis

    wordcloud_base64 = generate_wordcloud(tokens, positive_words, negative_words)

    return {
        'sentiment': sentiment,
        'polarity': round(polarity, 3),
        'confidence': confidence,
        'clarity': int(round(clarity * 100)),
        'tokens': tokens,
        'positive_words': positive_words,
        'negative_words': negative_words,
        'language': language,
        'recommended_action': rec,
        'wordcloud_base64': wordcloud_base64
    }
