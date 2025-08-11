from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
import os
from werkzeug.security import generate_password_hash, check_password_hash
import dotenv 
config = dotenv.load_dotenv()
import pytz

# Define timezone constants
utc_timezone = pytz.utc
indian_timezone = pytz.timezone('Asia/Kolkata')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'

# Database configuration
# Always use PostgreSQL from environment variable
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Please set it to your PostgreSQL connection string.")

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://')

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Helper function to get current Indian time
def get_indian_time():
    """Get current time in Indian timezone"""
    return datetime.now(indian_timezone)

# Helper function to convert UTC to Indian time
def utc_to_indian(utc_datetime):
    """Convert UTC datetime to Indian timezone"""
    if utc_datetime is None:
        return None
    
    # If the datetime is naive, assume it's UTC
    if utc_datetime.tzinfo is None:
        utc_datetime = utc_datetime.replace(tzinfo=utc_timezone)
    
    # Convert to Indian timezone
    return utc_datetime.astimezone(indian_timezone)

# Helper function to convert Indian time to UTC for storage
def indian_to_utc(indian_datetime):
    """Convert Indian datetime to UTC for database storage"""
    if indian_datetime is None:
        return None
    
    # If the datetime is naive, assume it's Indian timezone
    if indian_datetime.tzinfo is None:
        indian_datetime = indian_timezone.localize(indian_datetime)
    
    # Convert to UTC
    return indian_datetime.astimezone(utc_timezone)

# Database Models
class Employee(db.Model):
    phone_number = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_logged_in = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationship with time logs
    time_logs = db.relationship('TimeLog', backref='employee', lazy=True)

class TimeLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_phone = db.Column(db.String(20), db.ForeignKey('employee.phone_number'), nullable=False)
    login_time = db.Column(db.DateTime, nullable=False)
    logout_time = db.Column(db.DateTime, nullable=True)
    total_hours = db.Column(db.Float, default=0.0)
    date = db.Column(db.Date, nullable=False)

# Custom template filters for timezone conversion
@app.template_filter('indian_time')
def indian_time_filter(utc_datetime):
    """Template filter to convert UTC time to Indian time"""
    indian_time = utc_to_indian(utc_datetime)
    if indian_time:
        return indian_time.strftime('%Y-%m-%d %H:%M:%S IST')
    return 'N/A'

@app.template_filter('indian_time_only')
def indian_time_only_filter(utc_datetime):
    """Template filter to show only time in Indian timezone"""
    indian_time = utc_to_indian(utc_datetime)
    if indian_time:
        return indian_time.strftime('%H:%M:%S')
    return 'N/A'

@app.template_filter('indian_date')
def indian_date_filter(utc_datetime):
    """Template filter to show date in Indian timezone"""
    indian_time = utc_to_indian(utc_datetime)
    if indian_time:
        return indian_time.strftime('%Y-%m-%d')
    return 'N/A'

# Routes


@app.route('/employee', methods=['GET', 'POST'])
def employee_portal():
    if request.method == 'POST':
        name = request.form.get('name').strip()
        phone_number = request.form.get('phone_number').strip()
        
        if not name or not phone_number:
            flash('Please enter both name and phone number', 'error')
            return render_template('employee.html')
        
        # Check if employee exists
        employee = Employee.query.filter_by(phone_number=phone_number).first()
        
        if not employee:
            # Create new employee
            employee = Employee(name=name, phone_number=phone_number)
            db.session.add(employee)
            db.session.commit()
        
        # Get current Indian time
        current_indian_time = get_indian_time()
        current_utc_time = indian_to_utc(current_indian_time)
        
        # Check login status
        if not employee.is_logged_in:
            # Login
            employee.is_logged_in = True
            employee.name = name  # Update name in case it changed
            
            # Create new time log (store in UTC, but based on Indian time)
            time_log = TimeLog(
                employee_phone=employee.phone_number,
                login_time=current_utc_time,
                date=current_indian_time.date()  # Use Indian date
            )
            db.session.add(time_log)
            db.session.commit()
            
            # Show Indian time in flash message
            flash(f'Welcome {name}! You are now logged in at {current_indian_time.strftime("%H:%M:%S IST")}.', 'success')
        else:
            # Logout
            employee.is_logged_in = False
            
            # Update the latest time log
            latest_log = TimeLog.query.filter_by(
                employee_phone=employee.phone_number,
                logout_time=None
            ).first()
            
            if latest_log:
                latest_log.logout_time = current_utc_time
                
                # Calculate total hours using UTC times
                login_time = latest_log.login_time
                if login_time.tzinfo is None:
                    login_time = login_time.replace(tzinfo=timezone.utc)
                
                time_diff = current_utc_time - login_time
                total_hours = round(time_diff.total_seconds() / 3600, 2)
                latest_log.total_hours = total_hours
                
                db.session.commit()
                
                flash(f'Goodbye {name}! You logged out at {current_indian_time.strftime("%H:%M:%S IST")} and worked for {total_hours} hours today.', 'success')
            else:
                flash(f'Goodbye {name}! Logged out successfully at {current_indian_time.strftime("%H:%M:%S IST")}.', 'success')
        
        db.session.commit()
    
    return render_template('employee.html')

@app.route('/hr-login', methods=['GET', 'POST'])
def hr_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'eb123':
            session['hr_logged_in'] = True
            return redirect(url_for('hr_dashboard'))
        else:
            flash('Invalid password', 'error')
    
    return render_template('hr_login.html')

@app.route('/hr-dashboard')
def hr_dashboard():
    if not session.get('hr_logged_in'):
        return redirect(url_for('hr_login'))
    
    # Get filter parameters
    date_filter = request.args.get('date')
    name_filter = request.args.get('name', '').strip()
    
    # Base query
    query = db.session.query(TimeLog, Employee).join(Employee)
    
    # Apply filters
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(TimeLog.date == filter_date)
        except ValueError:
            pass
    
    if name_filter:
        query = query.filter(Employee.name.ilike(f'%{name_filter}%'))
    
    # Get filtered results
    time_logs = query.order_by(TimeLog.login_time.desc()).all()
    
    # Get currently active employees
    active_employees = Employee.query.filter_by(is_logged_in=True).all()
    
    # Get unique dates for the date selector (these are already in Indian timezone dates)
    unique_dates = db.session.query(TimeLog.date).distinct().order_by(TimeLog.date.desc()).all()
    unique_dates = [date[0] for date in unique_dates]
    
    return render_template('hr_dashboard.html', 
                         time_logs=time_logs, 
                         active_employees=active_employees,
                         unique_dates=unique_dates,
                         selected_date=date_filter,
                         selected_name=name_filter)

@app.route('/export-date/<date>')
def export_date(date):
    if not session.get('hr_logged_in'):
        return redirect(url_for('hr_login'))
    
    try:
        export_date = datetime.strptime(date, '%Y-%m-%d').date()
        
        # Get all logs for the specific date
        logs = db.session.query(TimeLog, Employee).join(Employee).filter(
            TimeLog.date == export_date
        ).order_by(TimeLog.login_time).all()
        
        # Format data for export with Indian timezone
        export_data = []
        for time_log, employee in logs:
            # Convert times to Indian timezone for export
            login_indian = utc_to_indian(time_log.login_time)
            logout_indian = utc_to_indian(time_log.logout_time)
            
            export_data.append({
                'name': employee.name,
                'phone_number': employee.phone_number,
                'login_time': login_indian.strftime('%H:%M:%S') if login_indian else '',
                'logout_time': logout_indian.strftime('%H:%M:%S') if logout_indian else 'Still working',
                'total_hours': time_log.total_hours,
                'date': date
            })
        
        return jsonify({
            'date': date,
            'data': export_data,
            'total_records': len(export_data),
            'timezone': 'Asia/Kolkata (IST)'
        })
        
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

@app.route('/hr-logout')
def hr_logout():
    session.pop('hr_logged_in', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

# Initialize database
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
