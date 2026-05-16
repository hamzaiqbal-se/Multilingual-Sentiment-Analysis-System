from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import json

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(UserMixin, db.Model):
    """User model for authentication and profile management"""
    __tablename__ = 'users'
    
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    full_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    
    # Relationships
    analyses = db.relationship('AnalysisHistory', backref='user', lazy=True, cascade='all, delete-orphan')
    sessions = db.relationship('Session', backref='user', lazy=True, cascade='all, delete-orphan')
    batch_groups = db.relationship('BatchGroup', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def get_id(self):
        return str(self.user_id)
    
    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def check_password(self, password):
        """Verify password against hash"""
        return bcrypt.check_password_hash(self.password_hash, password)
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.utcnow()
        db.session.commit()
    
    def get_analysis_stats(self):
        """Get sentiment analysis statistics for dashboard"""
        total = len([a for a in self.analyses if not a.is_deleted])
        if total == 0:
            return {
                'total': 0,
                'positive': 0,
                'negative': 0,
                'neutral': 0,
                'positive_pct': 0,
                'negative_pct': 0,
                'neutral_pct': 0
            }
        
        positive = sum(1 for a in self.analyses if a.sentiment == 'Positive' and not a.is_deleted)
        negative = sum(1 for a in self.analyses if a.sentiment == 'Negative' and not a.is_deleted)
        neutral = sum(1 for a in self.analyses if a.sentiment == 'Neutral' and not a.is_deleted)
        
        return {
            'total': total,
            'positive': positive,
            'negative': negative,
            'neutral': neutral,
            'positive_pct': round((positive / total) * 100, 1),
            'negative_pct': round((negative / total) * 100, 1),
            'neutral_pct': round((neutral / total) * 100, 1)
        }
    
    def __repr__(self):
        return f'<User {self.email}>'


class BatchGroup(db.Model):
    """Track batch file uploads"""
    __tablename__ = 'batch_groups'
    
    batch_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    batch_name = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    total_items = db.Column(db.Integer, default=0)
    positive_count = db.Column(db.Integer, default=0)
    negative_count = db.Column(db.Integer, default=0)
    neutral_count = db.Column(db.Integer, default=0)
    avg_confidence = db.Column(db.Float, default=0.0)
    overall_sentiment = db.Column(db.String(50), nullable=True)
    batch_summary = db.Column(db.Text, nullable=True)  # JSON for wordclouds and strategic actions
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)
    
    # Relationships
    analyses = db.relationship('AnalysisHistory', backref='batch_group', lazy=True, cascade='all, delete-orphan')
    
    def soft_delete(self):
        """Soft delete this batch and all its analyses"""
        self.is_deleted = True
        for analysis in self.analyses:
            analysis.is_deleted = True
        db.session.commit()
    
    def __repr__(self):
        return f'<BatchGroup {self.batch_name}>'


class AnalysisHistory(db.Model):
    """Store sentiment analysis results"""
    __tablename__ = 'analysis_history'
    
    analysis_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch_groups.batch_id'), nullable=True)
    analysis_type = db.Column(db.String(20), default='manual')  # 'manual' or 'batch'
    text = db.Column(db.Text, nullable=False)
    text_preview = db.Column(db.String(200), nullable=False)
    sentiment = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Integer, nullable=False)
    polarity = db.Column(db.Float, nullable=False)
    positive_words = db.Column(db.Text, default='[]')
    negative_words = db.Column(db.Text, default='[]')
    language = db.Column(db.String(50), nullable=True)
    wordcloud_path = db.Column(db.Text, nullable=True)
    recommended_action = db.Column(db.Text, nullable=True)
    chart_data = db.Column(db.Text, nullable=True)  # JSON string for single analysis charts
    batch_summary = db.Column(db.Text, nullable=True)  # JSON for batch summary data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    clarity = db.Column(db.Integer, nullable=True, default=0)
    is_deleted = db.Column(db.Boolean, default=False)
    is_saved = db.Column(db.Boolean, default=False)
    
    def set_keywords(self, positive, negative):
        """Store extracted keywords as JSON"""
        self.positive_words = json.dumps(positive)
        self.negative_words = json.dumps(negative)
    
    def get_positive_words(self):
        """Retrieve positive keywords"""
        return json.loads(self.positive_words)
    
    def get_negative_words(self):
        return json.loads(self.negative_words)

    def get_keywords(self):
        """Retrieve both positive and negative keywords for templates"""
        return self.get_positive_words(), self.get_negative_words()
    
    def set_chart_data(self, data):
        """Store chart data as JSON"""
        self.chart_data = json.dumps(data)
    
    def get_chart_data(self):
        """Retrieve chart data"""
        return json.loads(self.chart_data) if self.chart_data else None
    
    def set_batch_summary(self, data):
        """Store batch summary as JSON"""
        self.batch_summary = json.dumps(data)
    
    def get_batch_summary(self):
        """Retrieve batch summary"""
        return json.loads(self.batch_summary) if self.batch_summary else None
    
    def to_dict(self):
        """Convert to dictionary for export"""
        return {
            'text_preview': self.text_preview,
            'sentiment': self.sentiment,
            'confidence': self.confidence,
            'polarity': self.polarity,
            'language': self.language,
            'recommended_action': self.recommended_action,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def __repr__(self):
        return f'<AnalysisHistory {self.analysis_id}: {self.sentiment}>'


class Session(db.Model):
    """User session management"""
    __tablename__ = 'sessions'
    
    session_id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    ip_address = db.Column(db.String(45), nullable=True)
    
    def is_expired(self):
        """Check if session has expired"""
        return datetime.utcnow() > self.expires_at
    
    def deactivate(self):
        """Deactivate session"""
        self.is_active = False
        db.session.commit()
    
    def __repr__(self):
        return f'<Session {self.session_id}>'
class PlatformFeedback(db.Model):
    """Store user platform feedback and ratings"""
    __tablename__ = 'platform_feedback'
    
    feedback_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('platform_feedback', lazy=True, cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<PlatformFeedback {self.feedback_id} - Rating: {self.rating}>'
