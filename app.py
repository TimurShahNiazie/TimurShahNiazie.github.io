from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import os
import requests
from datetime import datetime
import json
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')  # Change this in production
app.config['SERVER_NAME'] = 'lifeonloan.tech'

# MongoDB Configuration
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = 'fintech_wealth_app'
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]

# Gemini API Configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"

# Budget Categories
ESSENTIAL_CATEGORIES = ['tuition', 'housing', 'food', 'transportation', 'textbooks']
DISCRETIONARY_CATEGORIES = ['clothing', 'personal_care', 'entertainment', 'electronics',
                            'travel', 'hobbies', 'coffee_snacks']


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if db.users.find_one({'username': username}):
            flash('Username already exists', 'error')
            return redirect(url_for('register'))

        if db.users.find_one({'email': email}):
            flash('Email already registered', 'error')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        db.users.insert_one({
            'username': username,
            'email': email,
            'password': hashed_password,
            'created_at': datetime.utcnow()
        })

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = db.users.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    budgets = list(db.budgets.find({'user_id': user_id}).sort('created_at', -1).limit(5))

    return render_template('dashboard.html', budgets=budgets)


@app.route('/submit', methods=['POST'])
def submit_financial_info():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = session['user_id']
        financial_data = {
            'user_id': user_id,
            'created_at': datetime.utcnow(),
            'essential': {},
            'discretionary': {}
        }

        total_essential = 0
        total_discretionary = 0

        # Process essential expenses
        for category in ESSENTIAL_CATEGORIES:
            amount = float(request.form.get(category, 0))
            financial_data['essential'][category] = amount
            total_essential += amount

        # Process discretionary expenses
        for category in DISCRETIONARY_CATEGORIES:
            amount = float(request.form.get(category, 0))
            financial_data['discretionary'][category] = amount
            total_discretionary += amount

        total_expenses = total_essential + total_discretionary

        # Generate budget visualization
        plot_url = generate_budget_visualization(total_essential, total_discretionary)

        # Get AI advice
        ai_advice = get_gemini_advice(financial_data, total_expenses)

        # Store the complete budget record
        budget_record = {
            'user_id': user_id,
            'data': financial_data,
            'total_essential': total_essential,
            'total_discretionary': total_discretionary,
            'total_expenses': total_expenses,
            'ai_advice': ai_advice,
            'created_at': datetime.utcnow(),
            'visualization': plot_url
        }

        db.budgets.insert_one(budget_record)

        return render_template('results.html',
                               budget=budget_record,
                               plot_url=plot_url,
                               essential_percentage=round((total_essential / total_expenses) * 100, 2),
                               discretionary_percentage=round((total_discretionary / total_expenses) * 100, 2))


def get_gemini_advice(financial_data, total_expenses):
    if not GEMINI_API_KEY:
        return "AI advice is currently unavailable. Please check back later."

    prompt = f"""
    As a financial advisor, analyze this college student's budget:
    Essential Expenses: {json.dumps(financial_data['essential'])}
    Discretionary Expenses: {json.dumps(financial_data['discretionary'])}
    Total Monthly Expenses: ${total_expenses:.2f}

    Provide specific, actionable advice to:
    1. Optimize their spending
    2. Suggest potential savings
    3. Recommend budget allocation improvements
    4. Highlight any concerning spending patterns

    Keep the advice concise, practical, and tailored to a student's lifestyle.
    """

    try:
        headers = {'Content-Type': 'application/json'}
        params = {'key': GEMINI_API_KEY}
        payload = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }

        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=payload)
        response.raise_for_status()

        result = response.json()
        if 'candidates' in result and result['candidates']:
            return result['candidates'][0]['content']['parts'][0]['text']
        return "Could not generate advice at this time. Please try again later."

    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return "AI advice service is temporarily unavailable."


def generate_budget_visualization(essential, discretionary):
    # Create a pie chart
    labels = ['Essential Expenses', 'Discretionary Expenses']
    sizes = [essential, discretionary]
    colors = ['#66b3ff', '#99ff99']

    plt.figure(figsize=(6, 6))
    plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    plt.axis('equal')  # Equal aspect ratio ensures pie is drawn as a circle
    plt.title('Budget Allocation')

    # Save plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)

    # Encode the image to base64
    plot_url = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close()

    return f"data:image/png;base64,{plot_url}"


@app.route('/history')
def budget_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    budgets = list(db.budgets.find({'user_id': user_id}).sort('created_at', -1))

    return render_template('history.html', budgets=budgets)


@app.route('/budget/<budget_id>')
def view_budget(budget_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    budget = db.budgets.find_one({'_id': budget_id, 'user_id': session['user_id']})
    if not budget:
        flash('Budget not found', 'error')
        return redirect(url_for('dashboard'))

    return render_template('budget_detail.html', budget=budget)


if __name__ == '__main__':
    app.run(debug=True)