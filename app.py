import os
import uuid
import csv
import io
import json
import base64
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from sentiment_engine import analyze_text_logic, generate_wordcloud
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from config import Config
from models import db, bcrypt, User, AnalysisHistory, Session as UserSession, BatchGroup, PlatformFeedback

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
bcrypt.init_app(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Create database tables
with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    return User.query.get(int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You do not have permission to access the admin panel.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']



def create_session_record(user_id):
    """Create a new session record in database"""
    session_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + app.config['PERMANENT_SESSION_LIFETIME']
    
    new_session = UserSession(
        session_id=session_id,
        user_id=user_id,
        expires_at=expires_at,
        ip_address=request.remote_addr
    )
    db.session.add(new_session)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Error committing to DB: {e}')
    return session_id


# ==================== ROUTES ====================

@app.route('/')
def index():
    """Landing page with dynamic stats and feedback"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    # Calculate System Stats
    try:
        avg_rating = db.session.query(db.func.avg(PlatformFeedback.rating)).scalar() or 0.0
        total_feedback = PlatformFeedback.query.count()
        recent_feedback = PlatformFeedback.query.join(User).order_by(PlatformFeedback.created_at.desc()).limit(3).all()
    except Exception as e:
        print(f"Error fetching feedback stats: {e}")
        avg_rating = 0.0
        total_feedback = 0
        recent_feedback = []
        
    return render_template('index.html', 
                           avg_rating=round(float(avg_rating), 1), 
                           total_feedback=total_feedback,
                           recent_feedback=recent_feedback)


@app.route('/api/demo-analyze', methods=['POST'])
@csrf.exempt
def demo_analyze():
    """Public demo endpoint — no login required. Real sentiment analysis."""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()

    word_count = len(text.split())
    if word_count < 2:
        return jsonify({'error': f'Please enter at least 2 words ({word_count} given).'}), 400
    if len(text) > 500:
        return jsonify({'error': 'Text is too long. Maximum 500 characters.'}), 400

    try:
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity        # -1.0 to +1.0
        subjectivity = blob.sentiment.subjectivity  # 0.0 to 1.0

        # Map polarity to sentiment label + emoji
        if polarity > 0.5:
            label, emoji_icon, color_class = 'Very Positive', '😄', 'accent-success'
        elif polarity > 0.1:
            label, emoji_icon, color_class = 'Positive', '🙂', 'accent-success'
        elif polarity > -0.1:
            label, emoji_icon, color_class = 'Neutral', '😐', 'accent-warning'
        elif polarity > -0.5:
            label, emoji_icon, color_class = 'Negative', '😕', 'accent-danger'
        else:
            label, emoji_icon, color_class = 'Very Negative', '😞', 'accent-danger'

        # Confidence: absolute polarity scaled to 60-99 range for realism
        confidence = round(60 + abs(polarity) * 39, 1)
        subjectivity_pct = round(subjectivity * 100, 1)

        return jsonify({
            'label': label,
            'emoji': emoji_icon,
            'color_class': color_class,
            'confidence': confidence,
            'subjectivity': subjectivity_pct,
            'polarity': round(polarity, 3),
        })
    except Exception as e:
        return jsonify({'error': 'Analysis failed. Please try again.'}), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        errors = []
        if not full_name or len(full_name) < 3 or len(full_name) > 50:
            errors.append('Full name must be between 3 and 50 characters.')
        if not email:
            errors.append('Email is required.')
        if not password or len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm_password:
            errors.append('Passwords do not match.')
        
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html', full_name=full_name, email=email)
        
        new_user = User(full_name=full_name, email=email)
        new_user.set_password(password)
        
        db.session.add(new_user)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'Error committing to DB: {e}')
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login with session-based authentication"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        if not email or not password:
            flash('Email and password are required.', 'danger')
            return render_template('login.html', email=email)
        
        user = User.query.filter_by(email=email, is_deleted=False).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Account is deactivated.', 'danger')
                return render_template('login.html', email=email)
            
            user.update_last_login()
            login_user(user, remember=remember)
            session.permanent = True
            create_session_record(user.user_id)
            
            flash(f'Welcome back, {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
            return render_template('login.html', email=email)
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """User logout"""
    active_session = UserSession.query.filter_by(
        user_id=current_user.user_id,
        is_active=True
    ).order_by(UserSession.created_at.desc()).first()
    
    if active_session:
        active_session.deactivate()
    
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('index'))


@app.route('/submit-platform-feedback', methods=['POST'])
@login_required
def submit_platform_feedback():
    """Submit or update user feedback for the platform"""
    try:
        rating = request.form.get('rating', type=int)
        comment = request.form.get('comment', '').strip()
        
        if not rating or rating < 1 or rating > 5:
            flash('Please provide a valid rating between 1 and 5.', 'warning')
            return redirect(request.referrer or url_for('dashboard'))
            
        # Check if user already submitted feedback
        feedback = PlatformFeedback.query.filter_by(user_id=current_user.user_id).first()
        
        if feedback:
            feedback.rating = rating
            feedback.comment = comment
            feedback.created_at = datetime.utcnow()
            message = 'Thank you! Your feedback has been updated.'
        else:
            feedback = PlatformFeedback(
                user_id=current_user.user_id,
                rating=rating,
                comment=comment
            )
            db.session.add(feedback)
            message = 'Thank you for your valuable feedback!'
            
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'Error committing to DB: {e}')
        flash(message, 'success')
        
    except Exception as e:
        db.session.rollback()
        print(f"Error submitting feedback: {e}")
        flash('An error occurred while submitting your feedback. Please try again.', 'danger')
        
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard with statistics"""
    stats = current_user.get_analysis_stats()
    recent_analyses = AnalysisHistory.query.filter_by(
        user_id=current_user.user_id,
        is_deleted=False
    ).order_by(AnalysisHistory.created_at.desc()).limit(10).all()
    
    # Calculate average confidence for the gauge chart
    avg_confidence = 0
    if stats['total'] > 0:
        all_analyses = AnalysisHistory.query.filter_by(
            user_id=current_user.user_id,
            is_deleted=False
        ).all()
        avg_confidence = round(sum(a.confidence for a in all_analyses) / len(all_analyses), 1) if all_analyses else 0
    
    return render_template('dashboard.html', stats=stats, recent_analyses=recent_analyses, avg_confidence=avg_confidence)


# ==================== ADMIN ROUTES ====================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    """Admin dashboard listing all users"""
    # Exclude the current admin if desired, but here we can show all users with self-protection logic
    users = User.query.filter_by(is_deleted=False).all()
    # Eagerly compute analyses count for display (optional mapping)
    user_data = []
    
    total_system_hits = AnalysisHistory.query.filter_by(is_deleted=False).count()
    total_saved_history = AnalysisHistory.query.filter_by(is_saved=True, is_deleted=False).count()
    
    for user in users:
        total_hits = AnalysisHistory.query.filter_by(user_id=user.user_id, is_deleted=False).count()
        total_saved = AnalysisHistory.query.filter_by(user_id=user.user_id, is_saved=True, is_deleted=False).count()
        manual_hits = AnalysisHistory.query.filter_by(user_id=user.user_id, analysis_type='manual', is_deleted=False).count()
        
        # V4 Intelligence: Distinguish between Batch Files and Batch Lines (Analyses)
        batch_files_count = BatchGroup.query.filter_by(user_id=user.user_id, is_deleted=False).count()
        batch_lines_count = AnalysisHistory.query.filter_by(user_id=user.user_id, analysis_type='batch', is_deleted=False).count()
        
        user_data.append({
            'user': user,
            'total_hits': total_hits,
            'total_saved': total_saved,
            'manual_hits': manual_hits,
            'batch_files_count': batch_files_count,
            'batch_lines_count': batch_lines_count
        })
        
    all_feedback = PlatformFeedback.query.join(User).order_by(PlatformFeedback.created_at.desc()).all()
    return render_template('admin_dashboard.html', user_data=user_data, total_system_hits=total_system_hits, total_saved_history=total_saved_history, all_feedback=all_feedback)


@app.route('/admin/user/<int:user_id>')
@login_required
@admin_required
def admin_user_view(user_id):
    """View specific user's activity"""
    user = User.query.get_or_404(user_id)
    analyses = AnalysisHistory.query.filter_by(
        user_id=user_id,
        is_deleted=False
    ).order_by(AnalysisHistory.created_at.desc()).all()
    return render_template('admin_user_view.html', target_user=user, analyses=analyses)


@app.route('/admin/user/<int:user_id>/toggle_active', methods=['POST'])
@login_required
@admin_required
def admin_toggle_active(user_id):
    """Toggle user active status"""
    user = User.query.get_or_404(user_id)
    if user.user_id == current_user.user_id:
        flash('You cannot deactivate your own admin account.', 'danger')
        return redirect(url_for('admin_dashboard'))
        
    user.is_active = not user.is_active
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Error committing to DB: {e}')
    
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.full_name} has been {status}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    """Cascade delete a user and all their history"""
    user = User.query.get_or_404(user_id)
    if user.user_id == current_user.user_id:
        flash('You cannot delete your own admin account.', 'danger')
        return redirect(url_for('admin_dashboard'))
        
    user.soft_delete()
    
    flash(f'User {user.full_name} and all their data were permanently deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/analyze', methods=['GET', 'POST'])
@login_required
def analyze():
    """Text analysis page - supports both single and batch processing"""
    if request.method == 'POST':
        process_mode = request.form.get('process_mode', 'combined')
        files = request.files.getlist('file')
        if files and any(f.filename for f in files):
            if process_mode == 'separate' and len(files) > 1:
                queue_items = []
                for file in files:
                    if not file.filename or not allowed_file(file.filename):
                        continue
                    
                    # Generate a unique path to safely store the file on disk
                    original_name = file.filename
                    safe_name = secure_filename(original_name)
                    unique_filename = f"{uuid.uuid4().hex}_{safe_name}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    file.save(filepath)
                    
                    queue_items.append({
                        'original_name': original_name,
                        'filepath': filepath,
                        'status': 'pending'
                    })
                
                if queue_items:
                    session['multi_batch_queue'] = queue_items
                    return redirect(url_for('batch_queue'))
                else:
                    flash('No valid files found for separate batch processing.', 'danger')
                    return redirect(url_for('analyze'))
            
            # If combined, proceed synchronously as a single merged batch
            lines = []
            file_names = []
            
            for file in files:
                if not file.filename: continue
                if not allowed_file(file.filename):
                    flash(f'Skipped {file.filename}: Only .txt files are supported.', 'warning')
                    continue
                
                try:
                    content = file.read().decode('utf-8')
                    file_lines = [line.strip() for line in content.split('\n') if line.strip()]
                    lines.extend(file_lines)
                    file_names.append(file.filename)
                except UnicodeDecodeError:
                    flash(f'Skipped {file.filename}: Encoding error. Please ensure UTF-8 encoding.', 'warning')
            
            if len(lines) == 0:
                flash('Uploaded files are empty or contain no valid text.', 'danger')
                return redirect(url_for('analyze'))
            
            # Single line short text -> single analysis
            if len(lines) == 1 and len(lines[0]) < 500 and len(file_names) == 1:
                text = lines[0]
                word_count = len(text.split())
                if word_count < 2:
                    flash('Text must contain at least 2 words.', 'danger')
                    return redirect(url_for('analyze'))
                
                result = analyze_text_logic(text)
                
                # Auto-log hit
                new_analysis = AnalysisHistory(
                    user_id=current_user.user_id,
                    analysis_type='batch',
                    text=text,
                    text_preview=text[:200] + '...' if len(text) > 200 else text,
                    sentiment=result['sentiment'],
                    confidence=result['confidence'],
                    polarity=result['polarity'],
                    language=result.get('language'),
                    wordcloud_path=result.get('wordcloud_base64'),
                    recommended_action=result.get('recommended_action'),
                    clarity=result.get('clarity', 0),
                    is_saved=False
                )
                new_analysis.set_keywords(result['positive_words'], result['negative_words'])
                
                # STORAGE OPTIMIZATION: Do not store chart_data for auto-logs
                
                db.session.add(new_analysis)
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f'Error committing to DB: {e}')

                session['last_analysis'] = {
                    'type': 'single',
                    'analysis_id': new_analysis.analysis_id
                }
                return redirect(url_for('results'))
            else:
                # BATCH PROCESSING
                batch_results = []
                all_positive_words = []
                all_negative_words = []
                full_text_aggregate = ""
                
                for i, line in enumerate(lines[:100], 1):
                    if len(line) >= 10:
                        result = analyze_text_logic(line)
                        full_text_aggregate += line + " "
                        all_positive_words.extend(result['positive_words'])
                        all_negative_words.extend(result['negative_words'])
                        
                        batch_results.append({
                            'id': i,
                            'text': line,
                            'text_preview': line[:100] + '...' if len(line) > 100 else line,
                            'sentiment': result['sentiment'],
                            'polarity': result['polarity'],
                            'confidence': result['confidence'],
                            'positive_words': result['positive_words'],
                            'negative_words': result['negative_words'],
                            'language': result['language'],
                            'recommended_action': result['recommended_action'],
                            'clarity': result.get('clarity', 0),
                            'wordcloud': result.get('wordcloud_base64')
                        })
                
                if not batch_results:
                    flash('No valid text lines found in uploaded files (minimum 2 words per line).', 'danger')
                    return redirect(url_for('analyze'))
                
                total = len(batch_results)
                positive = sum(1 for r in batch_results if r['sentiment'] == 'Positive')
                negative = sum(1 for r in batch_results if r['sentiment'] == 'Negative')
                neutral = sum(1 for r in batch_results if 'Neutral' in r['sentiment'])
                avg_confidence = sum(r['confidence'] for r in batch_results) / total
                
                # BATCH PROCESSING LOGIC
                # Summarize results across the entire batch
                total = len(batch_results)
                positive = sum(1 for r in batch_results if 'Positive' in r['sentiment'])
                negative = sum(1 for r in batch_results if 'Negative' in r['sentiment'])
                neutral = sum(1 for r in batch_results if 'Neutral' in r['sentiment'])
                avg_confidence = sum(r['confidence'] for r in batch_results) / total
                
                # Determine overall recommended action and sentiment
                if positive >= negative and positive >= neutral:
                    overall_sentiment = "Mostly Positive"
                    overall_action = "Overall Positive: Great feedback, consider sharing as testimonials."
                elif negative >= positive and negative >= neutral:
                    overall_sentiment = "Mostly Negative"
                    overall_action = "Overall Negative: High Priority! Investigate customer issues immediately."
                else:
                    overall_sentiment = "Mixed / Neutral"
                    overall_action = "Overall Neutral: Monitor sentiment trends in future batches."
                    
                # Generate global wordcloud for the batch
                from collections import Counter
                top_pos = [w[0] for w in Counter(all_positive_words).most_common(30)]
                top_neg = [w[0] for w in Counter(all_negative_words).most_common(30)]
                overall_wordcloud = generate_wordcloud(full_text_aggregate.split(), top_pos, top_neg)
                
                combined_filename = ", ".join(file_names)
                if len(file_names) > 2:
                    combined_filename = f"{len(file_names)} files: {', '.join(file_names[:2])}..."
                elif len(combined_filename) > 50:
                    combined_filename = combined_filename[:47] + "..."
                
                # Auto-log Batch - Save summary info for retrieval
                summary_payload = {
                    'overall_wordcloud': overall_wordcloud,
                    'overall_action': overall_action
                }
                
                batch_group = BatchGroup(
                    user_id=current_user.user_id,
                    batch_name=combined_filename,
                    file_name=combined_filename,
                    total_items=total,
                    positive_count=positive,
                    negative_count=negative,
                    neutral_count=neutral,
                    avg_confidence=round(avg_confidence, 1),
                    overall_sentiment=overall_sentiment,
                    batch_summary=json.dumps(summary_payload)
                )
                db.session.add(batch_group)
                try:
                    db.session.commit() # Commit early to lock in the ID
                    print(f"[DEBUG] BatchGroup created successfully with ID: {batch_group.batch_id}")
                except Exception as e:
                    db.session.rollback()
                    flash(f'Database error initializing batch: {str(e)}', 'danger')
                    return redirect(url_for('analyze'))

                # Save all batch results as hits (not saved yet)
                for res in batch_results:
                    new_item = AnalysisHistory(
                        user_id=current_user.user_id,
                        batch_id=batch_group.batch_id,
                        analysis_type='batch',
                        text=res['text'],
                        text_preview=res['text_preview'],
                        sentiment=res['sentiment'],
                        confidence=res['confidence'],
                        polarity=res['polarity'],
                        language=res.get('language'),
                        wordcloud_path=res.get('wordcloud_base64'),
                        recommended_action=res.get('recommended_action'),
                        clarity=res.get('clarity', 0),
                        is_saved=False
                    )
                    new_item.set_keywords(res['positive_words'], res['negative_words'])
                    
                    # STORAGE OPTIMIZATION: Do not store chart_data for auto-logs
                    
                    db.session.add(new_item)
                
                try:
                    db.session.commit()
                    print(f"[DEBUG] AnalysisHistory items saved for batch: {batch_group.batch_id}")
                except Exception as e:
                    db.session.rollback()
                    flash(f'Database error during batch save: {str(e)}', 'danger')
                    return redirect(url_for('analyze'))

                session['last_analysis'] = {
                    'type': 'batch',
                    'batch_id': batch_group.batch_id
                }
                return redirect(url_for('batch_results'))
            
        else:
            # Manual text entry
            text = request.form.get('text', '').strip()
            
            if not text:
                flash('Please enter text or upload a file.', 'danger')
                return redirect(url_for('analyze'))
            
            word_count = len(text.split())
            if word_count < 2:
                flash('Text must contain at least 2 words.', 'danger')
                return redirect(url_for('analyze'))
            
            if len(text) > app.config['MAX_TEXT_LENGTH']:
                flash(f'Text exceeds maximum length.', 'danger')
                return redirect(url_for('analyze'))
            
            result = analyze_text_logic(text)
            
            # Auto-log manual hit
            new_analysis = AnalysisHistory(
                user_id=current_user.user_id,
                analysis_type='manual',
                text=text,
                text_preview=text[:200] + '...' if len(text) > 200 else text,
                sentiment=result['sentiment'],
                confidence=result['confidence'],
                polarity=result['polarity'],
                language=result.get('language'),
                wordcloud_path=result.get('wordcloud_base64'),
                recommended_action=result.get('recommended_action'),
                clarity=result.get('clarity', 0),
                is_saved=False
            )
            new_analysis.set_keywords(result['positive_words'], result['negative_words'])
            
            # STORAGE OPTIMIZATION: Do not store chart_data for auto-logs
            
            db.session.add(new_analysis)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f'Error committing to DB: {e}')

            session['last_analysis'] = {
                'type': 'single',
                'analysis_id': new_analysis.analysis_id
            }
            
            return redirect(url_for('results'))
    
    return render_template('analyze.html', max_length=app.config['MAX_TEXT_LENGTH'])


@app.route('/batch_queue')
@login_required
def batch_queue():
    """Display the queued files waiting to be processed separately"""
    queue_items = session.get('multi_batch_queue', [])
    # Pass original index along with the item to avoid indexing mismatch after filtering
    active_items = []
    for i, item in enumerate(queue_items):
        if item.get('status') == 'pending':
            # Create a shallow copy and add the original positional index
            item_with_index = item.copy()
            item_with_index['original_index'] = i
            active_items.append(item_with_index)
    
    if not active_items:
        flash('No files pending in the queue.', 'info')
    
    return render_template('batch_queue.html', queue_items=active_items)


@app.route('/analyze_queue/<int:index>', methods=['GET', 'POST'])
@login_required
def analyze_queue(index):
    """Process a specific file from the queue and redirect to its batch_results"""
    if request.method == 'GET':
        return redirect(url_for('batch_queue'))
        
    queue_items = session.get('multi_batch_queue', [])
    batch_group = None
    
    if index < 0 or index >= len(queue_items):
        flash('Invalid queue item.', 'danger')
        return redirect(url_for('batch_queue'))
        
    item = queue_items[index]
    
    if item.get('status') != 'pending':
        flash(f'File {item["original_name"]} was already processed.', 'warning')
        return redirect(url_for('batch_queue'))
        
    filepath = item['filepath']
    if not os.path.exists(filepath):
        flash(f'File {item["original_name"]} not found on server.', 'danger')
        # Mark as missing so it drops out of the queue
        queue_items[index]['status'] = 'missing'
        session['multi_batch_queue'] = queue_items
        return redirect(url_for('batch_queue'))
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        flash(f'Encoding error reading {item["original_name"]}.', 'danger')
        queue_items[index]['status'] = 'error'
        session['multi_batch_queue'] = queue_items
        return redirect(url_for('batch_queue'))
        
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    
    if len(lines) == 0:
        flash(f'{item["original_name"]} is empty or contains no valid text.', 'danger')
        queue_items[index]['status'] = 'error'
        session['multi_batch_queue'] = queue_items
        return redirect(url_for('batch_queue'))

    # BATCH PROCESSING
    batch_results = []
    all_positive_words = []
    all_negative_words = []
    full_text_aggregate = ""
    
    for i, line in enumerate(lines[:100], 1):
        if len(line) >= 10:
            result = analyze_text_logic(line)
            full_text_aggregate += line + " "
            all_positive_words.extend(result['positive_words'])
            all_negative_words.extend(result['negative_words'])
            
            batch_results.append({
                'id': i,
                'text': line,
                'text_preview': line[:100] + '...' if len(line) > 100 else line,
                'sentiment': result['sentiment'],
                'polarity': result['polarity'],
                'confidence': result['confidence'],
                'positive_words': result['positive_words'],
                'negative_words': result['negative_words'],
                'language': result['language'],
                'recommended_action': result['recommended_action'],
                'clarity': result.get('clarity', 0),
                'wordcloud': result.get('wordcloud_base64')
            })
    
    if not batch_results:
        flash(f'No valid lines found in {item["original_name"]} (minimum 2 words per line).', 'danger')
        queue_items[index]['status'] = 'error'
        session['multi_batch_queue'] = queue_items
        return redirect(url_for('batch_queue'))
    
    total = len(batch_results)
    positive = sum(1 for r in batch_results if r['sentiment'] == 'Positive')
    negative = sum(1 for r in batch_results if r['sentiment'] == 'Negative')
    neutral = sum(1 for r in batch_results if 'Neutral' in r['sentiment'])
    avg_confidence = sum(r['confidence'] for r in batch_results) / total
    
    if positive >= negative and positive >= neutral:
        overall_sentiment = "Mostly Positive"
        overall_action = "Overall Positive: Great feedback, consider sharing as testimonials."
    elif negative >= positive and negative >= neutral:
        overall_sentiment = "Mostly Negative"
        overall_action = "Overall Negative: High Priority! Investigate customer issues immediately."
    else:
        overall_sentiment = "Mixed / Neutral"
        overall_action = "Overall Neutral: Monitor sentiment trends in future batches."
        
    from collections import Counter
    top_pos = [w[0] for w in Counter(all_positive_words).most_common(30)]
    top_neg = [w[0] for w in Counter(all_negative_words).most_common(30)]
    overall_wordcloud = generate_wordcloud(full_text_aggregate.split(), top_pos, top_neg)
    
    # Auto-log Batch - Save summary info for retrieval
    summary_payload = {
        'overall_wordcloud': overall_wordcloud,
        'overall_action': overall_action
    }
    
    batch_group = BatchGroup(
        user_id=current_user.user_id,
        batch_name=item['original_name'],
        file_name=item['original_name'],
        total_items=total,
        positive_count=positive,
        negative_count=negative,
        neutral_count=neutral,
        avg_confidence=round(avg_confidence, 1),
        overall_sentiment=overall_sentiment,
        batch_summary=json.dumps(summary_payload)
    )
    db.session.add(batch_group)
    try:
        db.session.commit()
        print(f"[DEBUG] BatchGroup created via Queue with ID: {batch_group.batch_id}")
    except Exception as e:
        db.session.rollback()
        flash(f'Database error initializing queue batch: {str(e)}', 'danger')
        return redirect(url_for('batch_queue'))

    # Save all batch results
    for res in batch_results:
        new_analysis_item = AnalysisHistory(
            user_id=current_user.user_id,
            batch_id=batch_group.batch_id,
            analysis_type='batch',
            text=res['text'],
            text_preview=res['text_preview'],
            sentiment=res['sentiment'],
            confidence=res['confidence'],
            polarity=res['polarity'],
            language=res.get('language'),
            wordcloud_path=res.get('wordcloud_base64'),
            recommended_action=res.get('recommended_action'),
            clarity=res.get('clarity', 0),
            is_saved=False
        )
        new_analysis_item.set_keywords(res['positive_words'], res['negative_words'])
        db.session.add(new_analysis_item)
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Database error during queue processing: {str(e)}', 'danger')
        return redirect(url_for('batch_queue'))

    # Mark as processed in queue
    queue_items[index]['status'] = 'completed'
    session['multi_batch_queue'] = queue_items
    
    session['last_analysis'] = {
        'type': 'batch',
        'batch_id': batch_group.batch_id
    }
    return redirect(url_for('batch_results'))


@app.route('/batch_results', methods=['GET', 'POST'])
@login_required
def batch_results():
    """Display batch analysis results"""
    session_data = session.get('last_analysis')
    
    if not session_data or session_data.get('type') != 'batch':
        flash('No batch analysis data found.', 'warning')
        return redirect(url_for('analyze'))
    
    batch_id = session_data.get('batch_id')
    print(f"[DEBUG] Looking up BatchGroup ID: {batch_id} for user: {current_user.user_id}")
    
    if not batch_id:
        flash('Invalid session: batch_id is missing.', 'warning')
        return redirect(url_for('analyze'))

    # Using modern Session.get()
    batch_group = db.session.get(BatchGroup, batch_id)
    
    if not batch_group or batch_group.user_id != current_user.user_id:
        flash(f'Batch analysis record not found (ID: {batch_id}).', 'danger')
        return redirect(url_for('analyze'))
    
    # Reconstruct analysis_data for the template
    analyses = AnalysisHistory.query.filter_by(batch_id=batch_id).all()
    
    # Calculate percentages for the summary
    total = batch_group.total_items
    pos_pct = round((batch_group.positive_count / total * 100), 1) if total > 0 else 0
    neg_pct = round((batch_group.negative_count / total * 100), 1) if total > 0 else 0
    neu_pct = round((batch_group.neutral_count / total * 100), 1) if total > 0 else 0
    
    # Determine overall action accurately
    if batch_group.positive_count >= batch_group.negative_count and batch_group.positive_count >= batch_group.neutral_count:
        overall_action = "Overall Positive: Great feedback, consider sharing as testimonials."
    elif batch_group.negative_count >= batch_group.positive_count and batch_group.negative_count >= batch_group.neutral_count:
        overall_action = "Overall Negative: High Priority! Investigate customer issues immediately."
    else:
        overall_action = "Overall Neutral: Monitor sentiment trends in future batches."

    # Identify global wordcloud (it's stored in the first analysis item's batch_summary or similar, 
    # but the old logic was passing it in the session. We should fetch it from the first analysis linked to this batch 
    # if it's stored there, or re-generate. Actually, BatchGroup doesn't store the overall wordcloud path. 
    # Let's check where it's stored.)
    # In my previous refactor, the batch overall wordcloud was just in the session. 
    # WE MUST STORE IT SOMEWHERE. 
    # I'll use the 'batch_summary' field of the BatchGroup to store serialized summary data INCLUDING the wordcloud.
    
    import json
    summary_data = {}
    if batch_group.batch_summary:
        summary_data = json.loads(batch_group.batch_summary)

    analysis_data = {
        'type': 'batch',
        'batch_id': batch_group.batch_id,
        'file_name': batch_group.file_name,
        'total': batch_group.total_items,
        'positive': batch_group.positive_count,
        'negative': batch_group.negative_count,
        'neutral': batch_group.neutral_count,
        'stats': {
            'Positive': batch_group.positive_count,
            'Negative': batch_group.negative_count,
            'Neutral': batch_group.neutral_count
        },
        'chart_labels': json.dumps(['Positive', 'Negative', 'Neutral']),
        'chart_values': json.dumps([batch_group.positive_count, batch_group.negative_count, batch_group.neutral_count]),
        'positive_pct': pos_pct,
        'negative_pct': neg_pct,
        'neutral_pct': neu_pct,
        'avg_confidence': batch_group.avg_confidence,
        'overall_sentiment': batch_group.overall_sentiment,
        'overall_action': overall_action,
        'overall_wordcloud': summary_data.get('overall_wordcloud'),
        'results': []
    }

    for i, a in enumerate(analyses, 1):
        pos_w, neg_w = a.get_keywords()
        analysis_data['results'].append({
            'id': i,
            'text': a.text,
            'text_preview': a.text_preview,
            'sentiment': a.sentiment,
            'confidence': a.confidence,
            'polarity': a.polarity,
            'positive_words': pos_w,
            'negative_words': neg_w,
            'language': a.language,
            'recommended_action': a.recommended_action,
            'clarity': a.clarity or 0
        })
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save_all':
            batch_id = analysis_data.get('batch_id')
            if batch_id:
                items = AnalysisHistory.query.filter_by(batch_id=batch_id, user_id=current_user.user_id).all()
                results_map = {res['text']: res for res in analysis_data['results']}
                
                for item in items:
                    item.is_saved = True
                    res = results_map.get(item.text)
                    if res:
                        item.set_chart_data({
                            'text': res['text'],
                            'text_preview': res['text_preview'],
                            'sentiment': res['sentiment'],
                            'confidence': res['confidence'],
                            'polarity': res['polarity'],
                            'positive_words': res['positive_words'],
                            'negative_words': res['negative_words']
                        })
                
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f'Error committing to DB: {e}')
                flash(f'Batch analyses saved to history.', 'success')
            else:
                flash('Could not find batch data to save.', 'danger')
            return redirect(url_for('history'))
        
        elif action == 'export_csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Line #', 'Text', 'Sentiment', 'Confidence (%)', 'Polarity'])
            
            for result in analysis_data['results']:
                writer.writerow([
                    result['id'],
                    result['text_preview'],
                    result['sentiment'],
                    result['confidence'],
                    result['polarity']
                ])
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode()),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'batch_{analysis_data["file_name"]}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            )
    
    # Removed basename sanitization for Base64 support
        
    return render_template('batch_results.html', 
                           analysis=analysis_data, 
                           wordcloud_data=analysis_data.get('overall_wordcloud'))


@app.route('/results', methods=['GET', 'POST'])
@login_required
def results():
    """Display and save analysis results"""
    session_data = session.get('last_analysis')
    
    if not session_data or session_data.get('type') != 'single':
        flash('No analysis data found. Please analyze text first.', 'warning')
        return redirect(url_for('analyze'))
    
    analysis_id = session_data.get('analysis_id')
    analysis = AnalysisHistory.query.get(analysis_id)
    
    if not analysis or analysis.user_id != current_user.user_id:
        flash('Analysis record not found.', 'danger')
        return redirect(url_for('analyze'))
    
    # Reconstruct data object for template
    pos_words, neg_words = analysis.get_keywords()
    analysis_data = {
        'type': 'single',
        'analysis_id': analysis.analysis_id,
        'text': analysis.text,
        'text_preview': analysis.text_preview,
        'sentiment': analysis.sentiment,
        'polarity': analysis.polarity,
        'confidence': analysis.confidence,
        'positive_words': pos_words,
        'negative_words': neg_words,
        'language': analysis.language,
        'recommended_action': analysis.recommended_action,
        'wordcloud': analysis.wordcloud_path
    }
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save':
            analysis_id = analysis_data.get('analysis_id')
            if analysis_id:
                analysis = AnalysisHistory.query.get(analysis_id)
                if analysis and analysis.user_id == current_user.user_id:
                    analysis.is_saved = True
                    # CRITICAL: Capture the actual session analysis data into chart_data column
                    analysis.set_chart_data(analysis_data)
                    try:
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        print(f'Error committing to DB: {e}')
                    flash('Analysis saved to history.', 'success')
                else:
                    flash('Analysis record not found.', 'danger')
            else:
                flash('No analysis ID found to save.', 'danger')
            return redirect(url_for('history'))
        
        elif action == 'export_csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Source', 'Batch Name', 'Text', 'Sentiment', 'Confidence (%)', 'Polarity', 'Date'])
            writer.writerow([
                'Manual',
                '-',
                analysis_data['text_preview'],
                analysis_data['sentiment'],
                analysis_data['confidence'],
                analysis_data['polarity'],
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ])
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode()),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            )
    
    # Removed basename sanitization for Base64 support
    
    return render_template('results.html', 
                           analysis=analysis_data, 
                           wordcloud_data=analysis_data.get('wordcloud'))


@app.route('/history')
@login_required
def history():
    """View analysis history with batch and manual separated"""
    view_type = request.args.get('view', 'all')
    batch_id = request.args.get('batch_id', type=int)
    search = request.args.get('search', '')
    sentiment_filter = request.args.get('sentiment', '')
    
    # Get batch groups for sidebar
    batch_groups = BatchGroup.query.filter_by(
        user_id=current_user.user_id, 
        is_deleted=False
    ).order_by(BatchGroup.created_at.desc()).all()
    
    # Build query
    if batch_id:
        query = AnalysisHistory.query.filter_by(
            user_id=current_user.user_id,
            batch_id=batch_id,
            is_deleted=False,
            is_saved=True # Strict filtering
        )
        selected_batch = BatchGroup.query.get(batch_id)
    elif view_type == 'manual':
        query = AnalysisHistory.query.filter_by(
            user_id=current_user.user_id,
            analysis_type='manual',
            batch_id=None,
            is_deleted=False,
            is_saved=True # Strict filtering
        )
        selected_batch = None
    elif view_type == 'batch':
        query = AnalysisHistory.query.filter_by(
            user_id=current_user.user_id,
            analysis_type='batch',
            is_deleted=False,
            is_saved=True # Strict filtering
        )
        selected_batch = None
    else:
        query = AnalysisHistory.query.filter_by(
            user_id=current_user.user_id,
            is_deleted=False,
            is_saved=True # Strict filtering
        )
        selected_batch = None
    
    # Apply filters
    if search:
        query = query.filter(AnalysisHistory.text_preview.contains(search))
    if sentiment_filter:
        query = query.filter_by(sentiment=sentiment_filter)
    
    analyses = query.order_by(AnalysisHistory.created_at.desc()).paginate(
        page=request.args.get('page', 1, type=int), 
        per_page=10, 
        error_out=False
    )
    
    return render_template('history.html', 
                         analyses=analyses, 
                         batch_groups=batch_groups,
                         selected_batch=selected_batch,
                         view_type=view_type,
                         search=search, 
                         sentiment_filter=sentiment_filter)


@app.route('/download_pdf', methods=['POST'])
@login_required
def download_pdf():
    """Generate and download a PDF report of the analysis"""
    analysis_data = session.get('last_analysis')
    
    if not analysis_data or analysis_data.get('type') != 'single':
        flash('No analysis data found for PDF generation.', 'warning')
        return redirect(url_for('analyze'))
        
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Title
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, height - 50, "Sentiment Analysis Report")
    
    # Metadata
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"User: {current_user.full_name}")
    c.drawString(50, height - 100, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Results
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 140, "Analysis Results:")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 160, f"Sentiment Label:  {analysis_data['sentiment']}")
    c.drawString(50, height - 180, f"Confidence Score: {analysis_data['confidence']}%")
    c.drawString(50, height - 200, f"Polarity: {analysis_data['polarity']}")
    
    # Summary of text
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 240, "Text Summary:")
    c.setFont("Helvetica", 12)
    
    # Simple lines wrap for text
    text_preview = analysis_data['text_preview']
    y_position = height - 260
    
    words = text_preview.split()
    line = ""
    for word in words:
        if c.stringWidth(line + word, "Helvetica", 12) < width - 100:
            line += word + " "
        else:
            c.drawString(50, y_position, line)
            line = word + " "
            y_position -= 20
    c.drawString(50, y_position, line)
    
    c.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mimetype='application/pdf'
    )

@app.route('/download_batch_pdf', methods=['POST'])
@login_required
def download_batch_pdf():
    """Generate and download a PDF report of the batch analysis"""
    analysis_data = session.get('last_analysis')
    
    if not analysis_data or analysis_data.get('type') != 'batch':
        flash('No batch analysis data found for PDF generation.', 'warning')
        return redirect(url_for('analyze'))
        
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Title
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 50, f"Batch Analysis Report: {analysis_data['file_name']}")
    
    # Metadata
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"User: {current_user.full_name}")
    c.drawString(50, height - 100, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.drawString(50, height - 120, f"Total Items: {analysis_data['total']}")
    
    # Overall Summary
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 160, "Overall Summary:")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 180, f"Positive: {analysis_data['positive']} ({analysis_data['positive_pct']}%)")
    c.drawString(50, height - 200, f"Negative: {analysis_data['negative']} ({analysis_data['negative_pct']}%)")
    c.drawString(50, height - 220, f"Neutral: {analysis_data['neutral']} ({analysis_data['neutral_pct']}%)")
    c.drawString(50, height - 240, f"Average Confidence: {analysis_data['avg_confidence']}%")
    if analysis_data.get('overall_action'):
        c.drawString(50, height - 260, f"Overall Action: {analysis_data['overall_action']}")
        
    y = height - 280
    wc_data = analysis_data.get('overall_wordcloud')
    if wc_data:
        from reportlab.lib.utils import ImageReader
        try:
            if wc_data.endswith(('.png', '.jpg', '.jpeg')) or wc_data.startswith('wordcloud_'):
                img_path = os.path.join(app.config['UPLOAD_FOLDER'], wc_data)
                if os.path.exists(img_path):
                    img = ImageReader(img_path)
                    c.drawImage(img, 50, y - 180, width=350, height=175, preserveAspectRatio=True)
                    y -= 200
            else:
                # Base64 data
                img_data = base64.b64decode(wc_data)
                img = ImageReader(io.BytesIO(img_data))
                c.drawImage(img, 50, y - 180, width=350, height=175, preserveAspectRatio=True)
                y -= 200
        except Exception as e:
            print(f"PDF WordCloud error: {e}")
                
    # Table headers
    y -= 20
    c.setFont("Helvetica-Bold", 10)
    if y < 50:
        c.showPage()
        y = height - 50
        c.setFont("Helvetica-Bold", 10)
        
    c.drawString(50, y, "Line #")
    c.drawString(100, y, "Sentiment")
    c.drawString(180, y, "Confidence")
    c.drawString(250, y, "Text Preview")
    
    c.setFont("Helvetica", 9)
    y -= 20
    
    for result in analysis_data['results']: 
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, "Line #")
            c.drawString(100, y, "Sentiment")
            c.drawString(180, y, "Confidence")
            c.drawString(250, y, "Text Preview")
            c.setFont("Helvetica", 9)
            y -= 20
            
        c.drawString(50, y, str(result['id']))
        c.drawString(100, y, str(result['sentiment']))
        c.drawString(180, y, f"{result['confidence']}%")
        
        text = result['text_preview']
        if len(text) > 80:
            text = text[:80] + "..."
        c.drawString(250, y, text)
        y -= 20
        
    c.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mimetype='application/pdf'
    )

@app.route('/export_item/<int:analysis_id>')
@login_required
def export_item(analysis_id):
    """Export an individual analysis record to CSV, Excel, or PDF"""
    fmt = request.args.get('fmt', 'pdf')
    analysis = AnalysisHistory.query.get_or_404(analysis_id)
    if analysis.user_id != current_user.user_id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('history'))
        
    if analysis.analysis_type == 'batch' and analysis.batch_id:
        if fmt == 'pdf':
            return redirect(url_for('export_batch_pdf', batch_id=analysis.batch_id))
        return redirect(url_for('export_batch', batch_id=analysis.batch_id, fmt=fmt))

@app.route('/export_batch/<string:batch_id>')
@login_required
def export_batch(batch_id, override_fmt=None):
    """Export an entire batch analysis to CSV, Excel, or PDF"""
    fmt = override_fmt or request.args.get('fmt', 'pdf')
    
    # We must construct a DataFrame or dictionary for all items in the batch
    batch_analyses = AnalysisHistory.query.filter_by(
        batch_id=batch_id,
        user_id=current_user.user_id,
        is_deleted=False
    ).all()
    
    if not batch_analyses:
        flash('Batch not found or unauthorized.', 'danger')
        return redirect(url_for('history'))
        
    import pandas as pd
    
    # Extract common batch info
    group_name = batch_analyses[0].batch_group.batch_name if batch_analyses[0].batch_group else "Batch"
    
    data = []
    for item in batch_analyses:
        data.append({
            'ID': item.analysis_id,
            'Date': item.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'Text': item.text,
            'Sentiment': item.sentiment,
            'Confidence': item.confidence,
            'Polarity': item.polarity,
            'Language': item.language or 'en',
            'Recommended Action': item.recommended_action
        })
        
    df = pd.DataFrame(data)
    
    if fmt == 'csv':
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name=f"{group_name}_export.csv")
        
    elif fmt == 'excel':
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Batch Results')
        output.seek(0)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f"{group_name}_export.xlsx")
        
    elif fmt == 'pdf':
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        batch_summary = batch_analyses[0].get_batch_summary() if batch_analyses else None

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, f"Batch Export: {group_name}")
        c.setFont("Helvetica", 12)
        c.drawString(50, height - 80, f"Total Items: {len(data)}")
        c.drawString(50, height - 100, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        y = height - 140
        
        if batch_summary:
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, y, "Overall Summary:")
            c.setFont("Helvetica", 12)
            c.drawString(50, y - 20, f"Positive: {batch_summary.get('positive', 0)} ({batch_summary.get('positive_pct', 0)}%)")
            c.drawString(50, y - 40, f"Negative: {batch_summary.get('negative', 0)} ({batch_summary.get('negative_pct', 0)}%)")
            c.drawString(50, y - 60, f"Neutral: {batch_summary.get('neutral', 0)} ({batch_summary.get('neutral_pct', 0)}%)")
            c.drawString(50, y - 80, f"Average Confidence: {batch_summary.get('avg_confidence', 0)}%")
            
            y_offset = 100
            if batch_summary.get('overall_action'):
                c.drawString(50, y - y_offset, f"Overall Action: {batch_summary.get('overall_action')}")
                y_offset += 20
                
            y = y - y_offset
            wc_data = batch_summary.get('overall_wordcloud')
            if wc_data:
                from reportlab.lib.utils import ImageReader
                try:
                    if wc_data.endswith(('.png', '.jpg', '.jpeg')) or wc_data.startswith('wordcloud_'):
                        img_path = os.path.join(app.config.get('UPLOAD_FOLDER', 'static/uploads'), wc_data)
                        if os.path.exists(img_path):
                            img = ImageReader(img_path)
                            c.drawImage(img, 50, y - 180, width=350, height=175, preserveAspectRatio=True)
                            y -= 200
                    else:
                        # Base64 data
                        img_data = base64.b64decode(wc_data)
                        img = ImageReader(io.BytesIO(img_data))
                        c.drawImage(img, 50, y - 180, width=350, height=175, preserveAspectRatio=True)
                        y -= 200
                except Exception as e:
                    print(f"Failed to draw wordcloud: {e}")
            
            y -= 20
            
        if y < 100:
            c.showPage()
            y = height - 50
            
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Line #")
        c.drawString(100, y, "Sentiment")
        c.drawString(180, y, "Confidence")
        c.drawString(250, y, "Text Preview")
        
        c.setFont("Helvetica", 9)
        y -= 20
        
        for idx, item in enumerate(data, 1):
            if y < 50:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica-Bold", 10)
                c.drawString(50, y, "Line #")
                c.drawString(100, y, "Sentiment")
                c.drawString(180, y, "Confidence")
                c.drawString(250, y, "Text Preview")
                c.setFont("Helvetica", 9)
                y -= 20
                
            c.drawString(50, y, str(idx))
            c.drawString(100, y, str(item['Sentiment']))
            c.drawString(180, y, f"{item['Confidence']}%")
            
            text = item['Text']
            if len(text) > 80:
                text = text[:80] + "..."
            c.drawString(250, y, text)
            y -= 20
            
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f"{group_name}_export.pdf")
        
    else:
        flash('Invalid format requested.', 'danger')
        return redirect(url_for('history'))

@app.route('/export_batch_pdf/<string:batch_id>')
@login_required
def export_batch_pdf(batch_id):
    """Generate a dedicated professional multi-page PDF report for a batch"""
    return export_batch(batch_id, override_fmt='pdf')




@app.route('/view_analysis/<int:analysis_id>')
@login_required
def view_analysis(analysis_id):
    """View saved analysis with charts - works for both manual and batch items"""
    batch_summary_json = "null"  # Unified initialization at start
    analysis = AnalysisHistory.query.get_or_404(analysis_id)
    
    if analysis.user_id != current_user.user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('history'))
    
    # Get chart data with robust fallback
    try:
        chart_data_obj = analysis.get_chart_data()
        
        # Fallback Calculation: If JSON blob is missing or empty, build it on-the-fly
        if not chart_data_obj:
            chart_data_obj = {
                'sentiment': analysis.sentiment,
                'polarity': analysis.polarity,
                'confidence': analysis.confidence,
                'positive_words': analysis.get_positive_words(),
                'negative_words': analysis.get_negative_words()
            }
    except Exception as e:
        # Emergency fallback if even DB fields fail
        chart_data_obj = {
            'sentiment': 'Neutral',
            'polarity': 0,
            'confidence': 50,
            'positive_words': [],
            'negative_words': []
        }
    
    # Pass clean JSON string for JS consumption
    import json
    json_data = json.dumps(chart_data_obj)
    
    # Prepare data for template
    view_data = {
        'type': 'single',
        'analysis_id': analysis.analysis_id,
        'text': analysis.text,
        'text_preview': analysis.text_preview,
        'sentiment': chart_data_obj.get('sentiment', analysis.sentiment),
        'polarity': chart_data_obj.get('polarity', analysis.polarity),
        'confidence': chart_data_obj.get('confidence', analysis.confidence),
        'positive_words': chart_data_obj.get('positive_words', analysis.get_positive_words()),
        'negative_words': chart_data_obj.get('negative_words', analysis.get_negative_words()),
        'language': analysis.language,
        'wordcloud': analysis.wordcloud_path,
        'recommended_action': analysis.recommended_action,
        'created_at': analysis.created_at,
        'analysis_type': analysis.analysis_type
    }
    
    # If this is a batch item, also get batch summary
    if analysis.analysis_type == 'batch' and analysis.batch_group:
        view_data['batch_name'] = analysis.batch_group.batch_name
        view_data['batch_id'] = analysis.batch_id
        
        # Pull stats directly from the BatchGroup model
        summary_obj = {
            'positive': analysis.batch_group.positive_count,
            'negative': analysis.batch_group.negative_count,
            'neutral': analysis.batch_group.neutral_count,
            'total': analysis.batch_group.total_items
        }
        view_data['batch_summary'] = summary_obj
        batch_summary_json = json.dumps(summary_obj)
    
    return render_template('view_analysis.html', 
                           analysis=view_data, 
                           chart_data=json_data,
                           batch_summary_json=batch_summary_json,
                           wordcloud_data=view_data.get('wordcloud'))


@app.route('/view_batch/<int:batch_id>')
@login_required
def view_batch_full(batch_id):
    """View complete batch with all charts and statistics"""
    batch = BatchGroup.query.get_or_404(batch_id)
    
    if batch.user_id != current_user.user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('history'))
    
    # Get batch summary from first item
    first_item = AnalysisHistory.query.filter_by(
        batch_id=batch_id,
        user_id=current_user.user_id
    ).first()
    
    batch_summary = None
    if first_item:
        batch_summary = first_item.get_batch_summary()
    
    # If no stored summary, build from current data
    if not batch_summary:
        analyses = AnalysisHistory.query.filter_by(
            batch_id=batch_id,
            user_id=current_user.user_id,
            is_deleted=False
        ).all()
        
        if not analyses:
            flash('No items found for this batch.', 'warning')
            return redirect(url_for('history'))

        total = len(analyses)
        positive = sum(1 for a in analyses if a.sentiment == 'Positive')
        negative = sum(1 for a in analyses if a.sentiment == 'Negative')
        neutral = sum(1 for a in analyses if 'Neutral' in a.sentiment)
        avg_confidence = sum(a.confidence for a in analyses) / total if total > 0 else 0
        
        # Wordcloud recovery: Look for a wordcloud from any item if batch doesn't have one
        overall_wordcloud = next((a.wordcloud_path for a in analyses if a.wordcloud_path), None)
        batch_summary = {
            'total': total,
            'positive': positive,
            'negative': negative,
            'neutral': neutral,
            'stats': {
                'Positive': positive,
                'Negative': negative,
                'Neutral': neutral
            },
            'chart_labels': json.dumps(['Positive', 'Negative', 'Neutral']),
            'chart_values': json.dumps([positive, negative, neutral]),
            'positive_pct': round((positive/total)*100, 1) if total > 0 else 0,
            'negative_pct': round((negative/total)*100, 1) if total > 0 else 0,
            'neutral_pct': round((neutral/total)*100, 1) if total > 0 else 0,
            'avg_confidence': round(avg_confidence, 1),
            'overall_wordcloud': overall_wordcloud,
            'overall_action': "Multiple entries analyzed. Review individual results for specific insights.",
            'results': [{
                'id': a.analysis_id,
                'text': a.text,
                'text_preview': a.text_preview,
                'sentiment': a.sentiment,
                'polarity': a.polarity,
                'confidence': a.confidence,
                'language': a.language,
                'wordcloud': a.wordcloud_path,
                'recommended_action': a.recommended_action
            } for a in analyses]
        }
    
    return render_template('view_batch_full.html', 
                           batch=batch, 
                           analysis=batch_summary,
                           wordcloud_data=batch_summary.get('overall_wordcloud'))


@app.route('/batch/<int:batch_id>')
@login_required
def view_batch(batch_id):
    """View specific batch group details (original route - redirects to new)"""
    return redirect(url_for('view_batch_full', batch_id=batch_id))


@app.route('/batch/delete/<int:batch_id>', methods=['POST'])
@login_required
def delete_batch(batch_id):
    """Soft delete entire batch group"""
    batch = BatchGroup.query.get_or_404(batch_id)
    
    if batch.user_id != current_user.user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('history'))
    
    batch.soft_delete()
    flash(f'Batch "{batch.batch_name}" deleted.', 'success')
    return redirect(url_for('history'))


@app.route('/history/delete/<int:analysis_id>', methods=['POST'])
@login_required
def delete_analysis(analysis_id):
    """Delete a specific analysis"""
    analysis = AnalysisHistory.query.get_or_404(analysis_id)
    
    if analysis.user_id != current_user.user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('history'))
    
    analysis.is_deleted = True
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Error committing to DB: {e}')
    flash('Analysis deleted.', 'success')
    return redirect(url_for('history'))


@app.route('/history/clear_all', methods=['POST'])
@login_required
def clear_all_history():
    """Clear all history for current user"""
    # Soft delete all analyses
    analyses = AnalysisHistory.query.filter_by(
        user_id=current_user.user_id,
        is_deleted=False
    ).all()
    
    count = 0
    for analysis in analyses:
        analysis.is_deleted = True
        count += 1
    
    # Soft delete all batch groups
    batches = BatchGroup.query.filter_by(
        user_id=current_user.user_id,
        is_deleted=False
    ).all()
    
    batch_count = 0
    for batch in batches:
        batch.is_deleted = True
        batch_count += 1
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'Error committing to DB: {e}')
    
    flash(f'Cleared {count} analyses and {batch_count} batch files from history.', 'success')
    return redirect(url_for('history'))


@app.route('/export', methods=['GET', 'POST'])
@login_required
def export_data():
    """Export history with various options"""
    if request.method == 'POST':
        export_type = request.form.get('export_type', 'all')
        selected_batches = request.form.getlist('batch_ids')
        include_manual = request.form.get('include_manual') == 'on'
        fmt = request.form.get('format', 'csv')
        
        data = []
        
        # Export manual results
        if export_type in ['all', 'manual'] or (export_type == 'selected' and include_manual):
            manual_analyses = AnalysisHistory.query.filter_by(
                user_id=current_user.user_id,
                analysis_type='manual',
                is_deleted=False
            ).all()
            
            for analysis in manual_analyses:
                data.append({
                    'Source': 'Manual',
                    'Batch Name': '-',
                    'Text': analysis.text_preview,
                    'Sentiment': analysis.sentiment,
                    'Confidence': analysis.confidence,
                    'Polarity': analysis.polarity,
                    'Language': analysis.language or '-',
                    'Date': analysis.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
        
        # Export batch results
        if export_type in ['all', 'batch'] or export_type == 'selected':
            batch_query = AnalysisHistory.query.filter_by(
                user_id=current_user.user_id,
                analysis_type='batch',
                is_deleted=False
            )
            
            if export_type == 'selected' and selected_batches:
                batch_query = batch_query.filter(AnalysisHistory.batch_id.in_(selected_batches))
            
            batch_analyses = batch_query.all()
            
            for analysis in batch_analyses:
                batch_name = analysis.batch_group.batch_name if analysis.batch_group else '-'
                data.append({
                    'Source': 'Batch',
                    'Batch Name': batch_name,
                    'Text': analysis.text_preview,
                    'Sentiment': analysis.sentiment,
                    'Confidence': analysis.confidence,
                    'Polarity': analysis.polarity,
                    'Language': analysis.language or '-',
                    'Date': analysis.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
        
        if not data:
            flash('No records found to export.', 'warning')
            return redirect(url_for('export_data'))
            
        import pandas as pd
        df = pd.DataFrame(data)
        
        if fmt == 'csv':
            output = io.StringIO()
            df.to_csv(output, index=False)
            output.seek(0)
            flash(f'{len(data)} records exported to CSV.', 'success')
            return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name=f'export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
            
        elif fmt == 'excel':
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Export Data')
            output.seek(0)
            flash(f'{len(data)} records exported to Excel.', 'success')
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
            
        elif fmt == 'pdf':
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=letter)
            width, height = letter
            
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, height - 50, "Complete History Export")
            c.setFont("Helvetica", 12)
            c.drawString(50, height - 80, f"Total Items: {len(data)}")
            c.drawString(50, height - 100, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            y = height - 140
            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, y, "Type")
            c.drawString(90, y, "Batch Name")
            c.drawString(180, y, "Sentiment")
            c.drawString(240, y, "Conf.")
            c.drawString(280, y, "Text Preview")
            
            c.setFont("Helvetica", 9)
            y -= 20
            
            for item in data:
                if y < 50:
                    c.showPage()
                    y = height - 50
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(40, y, "Type")
                    c.drawString(90, y, "Batch Name")
                    c.drawString(180, y, "Sentiment")
                    c.drawString(240, y, "Conf.")
                    c.drawString(280, y, "Text Preview")
                    c.setFont("Helvetica", 9)
                    y -= 20
                    
                c.drawString(40, y, str(item['Source']))
                batch_n = str(item['Batch Name'])
                if len(batch_n) > 15: batch_n = batch_n[:12] + "..."
                c.drawString(90, y, batch_n)
                c.drawString(180, y, str(item['Sentiment']))
                c.drawString(240, y, f"{item['Confidence']}%")
                
                text = item['Text']
                if len(text) > 60:
                    text = text[:60] + "..."
                c.drawString(280, y, text)
                y -= 20
                
            c.save()
            buffer.seek(0)
            flash(f'{len(data)} records exported to PDF.', 'success')
            return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf')
            
        else:
            flash('Invalid format requested.', 'danger')
            return redirect(url_for('export_data'))
    
    # GET request - show export options
    batch_groups = BatchGroup.query.filter_by(
        user_id=current_user.user_id,
        is_deleted=False
    ).order_by(BatchGroup.created_at.desc()).all()
    
    manual_count = AnalysisHistory.query.filter_by(
        user_id=current_user.user_id,
        analysis_type='manual',
        is_deleted=False
    ).count()
    
    return render_template('export.html', 
                         batch_groups=batch_groups,
                         manual_count=manual_count)


@app.route('/export_history')
@login_required
def export_history():
    """Quick export all history"""
    return redirect(url_for('export_data'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile management"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            full_name = request.form.get('full_name', '').strip()
            
            if not full_name or len(full_name) < 3:
                flash('Full name must be at least 3 characters.', 'danger')
            else:
                current_user.full_name = full_name
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f'Error committing to DB: {e}')
                flash('Profile identity information updated successfully.', 'success')
        
        elif action == 'change_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            if not current_user.check_password(current_password):
                flash('Failed to update your password. Please verify your current password.', 'danger')
            elif len(new_password) < 8:
                flash('New password must be at least 8 characters.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            else:
                current_user.set_password(new_password)
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f'Error committing to DB: {e}')
                flash('Password changed successfully.', 'success')
        
        return redirect(url_for('profile'))
    
    stats = current_user.get_analysis_stats()
    return render_template('profile.html', stats=stats)


@app.route('/api/stats')
@login_required
def api_stats():
    """Return JSON statistics for Chart.js"""
    stats = current_user.get_analysis_stats()
    return jsonify({
        'labels': ['Positive', 'Negative', 'Neutral'],
        'data': [stats['positive'], stats['negative'], stats['neutral']],
        'percentages': [stats['positive_pct'], stats['negative_pct'], stats['neutral_pct']]
    })


@app.errorhandler(404)
def not_found_error(error):
    return render_template('base.html', error='Page not found'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('base.html', error='Internal server error'), 500


with app.app_context():
    db.create_all()



# --- Trend Chart APIs Additions ---
@app.route('/api/stats/trend')
@login_required
def user_trend_stats():
    # Calculate last 7 days for current user
    from datetime import datetime, timedelta
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=6)
    
    # Query database
    history = db.session.query(
        db.func.date(AnalysisHistory.created_at).label('date'),
        AnalysisHistory.sentiment
    ).filter(
        AnalysisHistory.user_id == current_user.user_id,
        AnalysisHistory.is_deleted == False,
        AnalysisHistory.created_at >= start_date
    ).all()
    
    # Structure data
    dates = [(start_date + timedelta(days=i)).strftime('%m-%d') for i in range(7)]
    pos_counts = {d: 0 for d in dates}
    neg_counts = {d: 0 for d in dates}
    
    for row in history:
        # sqlite date returns YYYY-MM-DD
        try:
            d_str = row.date.split('-', 1)[1] if row.date else ''
            # map to mm-dd
            if d_str in pos_counts:
                if 'Positive' in row.sentiment:
                    pos_counts[d_str] += 1
                elif 'Negative' in row.sentiment:
                    neg_counts[d_str] += 1
        except:
            pass
            
    return jsonify({
        'labels': dates,
        'positive': [pos_counts[d] for d in dates],
        'negative': [neg_counts[d] for d in dates]
    })

@app.route('/api/admin/trend')
@login_required
@admin_required
def admin_trend_stats():
    from datetime import datetime, timedelta
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=6)
    
    # Query database for all active analyses
    history = db.session.query(
        db.func.date(AnalysisHistory.created_at).label('date'),
        AnalysisHistory.sentiment
    ).filter(
        AnalysisHistory.is_deleted == False,
        AnalysisHistory.created_at >= start_date
    ).all()
    
    dates = [(start_date + timedelta(days=i)).strftime('%m-%d') for i in range(7)]
    pos_counts = {d: 0 for d in dates}
    neg_counts = {d: 0 for d in dates}
    
    for row in history:
        try:
            d_str = row.date.split('-', 1)[1] if row.date else ''
            if d_str in pos_counts:
                if 'Positive' in row.sentiment:
                    pos_counts[d_str] += 1
                elif 'Negative' in row.sentiment:
                    neg_counts[d_str] += 1
        except:
            pass
            
    return jsonify({
        'labels': dates,
        'positive': [pos_counts[d] for d in dates],
        'negative': [neg_counts[d] for d in dates]
    })
# ----------------------------------

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)