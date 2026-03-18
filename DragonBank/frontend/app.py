"""
DragonBank - Frontend Web Application
======================================
Interface web pour l'application bancaire DragonBank.
"""

import os
from functools import wraps

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'frontend-secret')
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://backend:5000')


# ============================================
# UTILITAIRES
# ============================================
def api_request(method, endpoint, data=None, token=None):
    """Effectue une requête vers le backend API."""
    url = f"{BACKEND_URL}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    
    try:
        if method == 'GET':
            resp = requests.get(url, headers=headers, timeout=10)
        elif method == 'POST':
            resp = requests.post(url, json=data, headers=headers, timeout=10)
        elif method == 'DELETE':
            resp = requests.delete(url, headers=headers, timeout=10)
        else:
            return None, 'Méthode non supportée'
        
        return resp.json(), resp.status_code
    except requests.exceptions.ConnectionError:
        return {'error': 'Impossible de contacter le serveur'}, 503
    except Exception as e:
        return {'error': str(e)}, 500


def login_required(f):
    """Décorateur pour protéger les routes nécessitant une connexion."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'token' not in session:
            flash('Veuillez vous connecter', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ============================================
# ROUTES PUBLIQUES
# ============================================
@app.route('/')
def home():
    """Page d'accueil."""
    if 'token' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion."""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        data, status = api_request('POST', '/api/auth/login', {
            'email': email,
            'password': password
        })
        
        if status == 200:
            session['token'] = data['token']
            session['user'] = data['user']
            flash(f'Bienvenue {data["user"]["first_name"]} ! 🐉', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(data.get('error', 'Erreur de connexion'), 'danger')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Page d'inscription."""
    if request.method == 'POST':
        form_data = {
            'email': request.form.get('email'),
            'password': request.form.get('password'),
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'phone': request.form.get('phone', ''),
            'address': request.form.get('address', ''),
            'date_of_birth': request.form.get('date_of_birth') or None
        }
        
        # Vérifier confirmation mot de passe
        if request.form.get('password') != request.form.get('confirm_password'):
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('register.html')
        
        data, status = api_request('POST', '/api/auth/register', form_data)
        
        if status == 201:
            session['token'] = data['token']
            session['user'] = data['user']
            flash('Compte créé avec succès ! Un compte courant a été ouvert automatiquement. 🎉', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(data.get('error', 'Erreur lors de l\'inscription'), 'danger')
    
    return render_template('register.html')


@app.route('/logout')
def logout():
    """Déconnexion."""
    session.clear()
    flash('Vous êtes déconnecté', 'info')
    return redirect(url_for('login'))


# ============================================
# ROUTES PROTÉGÉES - DASHBOARD
# ============================================
@app.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord principal."""
    token = session['token']
    
    accounts_data, _ = api_request('GET', '/api/accounts', token=token)
    stats_data, _ = api_request('GET', '/api/stats', token=token)
    transactions_data, _ = api_request('GET', '/api/transactions?limit=5', token=token)
    
    return render_template('dashboard.html',
        user=session.get('user', {}),
        accounts=accounts_data.get('accounts', []),
        stats=stats_data.get('stats', {}),
        recent_transactions=transactions_data.get('transactions', [])
    )


# ============================================
# ROUTES - COMPTES
# ============================================
@app.route('/accounts')
@login_required
def accounts():
    """Liste des comptes bancaires."""
    token = session['token']
    data, status = api_request('GET', '/api/accounts', token=token)
    
    return render_template('accounts.html',
        user=session.get('user', {}),
        accounts=data.get('accounts', [])
    )


@app.route('/accounts/open', methods=['GET', 'POST'])
@login_required
def open_account():
    """Ouverture d'un nouveau compte."""
    if request.method == 'POST':
        token = session['token']
        form_data = {
            'account_type': request.form.get('account_type'),
            'initial_deposit': float(request.form.get('initial_deposit', 0))
        }
        
        data, status = api_request('POST', '/api/accounts', data=form_data, token=token)
        
        if status == 201:
            flash(f'Compte {form_data["account_type"]} ouvert avec succès ! 🎉', 'success')
            return redirect(url_for('accounts'))
        else:
            flash(data.get('error', 'Erreur lors de l\'ouverture du compte'), 'danger')
    
    return render_template('open_account.html', user=session.get('user', {}))


# ============================================
# ROUTES - BÉNÉFICIAIRES
# ============================================
@app.route('/beneficiaries')
@login_required
def beneficiaries():
    """Liste des bénéficiaires."""
    token = session['token']
    data, status = api_request('GET', '/api/beneficiaries', token=token)
    
    return render_template('beneficiaries.html',
        user=session.get('user', {}),
        beneficiaries=data.get('beneficiaries', [])
    )


@app.route('/beneficiaries/add', methods=['GET', 'POST'])
@login_required
def add_beneficiary():
    """Ajout d'un bénéficiaire."""
    if request.method == 'POST':
        token = session['token']
        form_data = {
            'beneficiary_name': request.form.get('beneficiary_name'),
            'account_number': request.form.get('account_number'),
            'bank_name': request.form.get('bank_name', 'DragonBank'),
            'iban': request.form.get('iban', ''),
            'bic': request.form.get('bic', '')
        }
        
        data, status = api_request('POST', '/api/beneficiaries', data=form_data, token=token)
        
        if status == 201:
            flash('Bénéficiaire ajouté avec succès !', 'success')
            return redirect(url_for('beneficiaries'))
        else:
            flash(data.get('error', 'Erreur'), 'danger')
    
    return render_template('add_beneficiary.html', user=session.get('user', {}))


@app.route('/beneficiaries/delete/<beneficiary_id>')
@login_required
def delete_beneficiary(beneficiary_id):
    """Suppression d'un bénéficiaire."""
    token = session['token']
    data, status = api_request('DELETE', f'/api/beneficiaries/{beneficiary_id}', token=token)
    
    if status == 200:
        flash('Bénéficiaire supprimé', 'success')
    else:
        flash(data.get('error', 'Erreur'), 'danger')
    
    return redirect(url_for('beneficiaries'))


# ============================================
# ROUTES - VIREMENTS
# ============================================
@app.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    """Page de virement (interne et entre personnes)."""
    token = session['token']
    
    accounts_data, _ = api_request('GET', '/api/accounts', token=token)
    beneficiaries_data, _ = api_request('GET', '/api/beneficiaries', token=token)
    
    if request.method == 'POST':
        transfer_type = request.form.get('transfer_type')
        amount = float(request.form.get('amount', 0))
        from_account_id = request.form.get('from_account_id')
        description = request.form.get('description', '')
        
        if transfer_type == 'internal':
            to_account_id = request.form.get('to_account_id')
            data, status = api_request('POST', '/api/transfers/internal', {
                'from_account_id': from_account_id,
                'to_account_id': to_account_id,
                'amount': amount,
                'description': description
            }, token=token)
        elif transfer_type == 'person':
            beneficiary_id = request.form.get('beneficiary_id')
            data, status = api_request('POST', '/api/transfers/person', {
                'from_account_id': from_account_id,
                'beneficiary_id': beneficiary_id,
                'amount': amount,
                'description': description
            }, token=token)
        else:
            flash('Type de virement invalide', 'danger')
            return redirect(url_for('transfer'))
        
        if status == 200:
            flash(data.get('message', 'Virement effectué !'), 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(data.get('error', 'Erreur lors du virement'), 'danger')
    
    return render_template('transfer.html',
        user=session.get('user', {}),
        accounts=accounts_data.get('accounts', []),
        beneficiaries=beneficiaries_data.get('beneficiaries', [])
    )


@app.route('/transfer/external', methods=['GET', 'POST'])
@login_required
def transfer_external():
    """Virement externe (depuis/vers autre banque)."""
    token = session['token']
    accounts_data, _ = api_request('GET', '/api/accounts', token=token)
    
    if request.method == 'POST':
        form_data = {
            'account_id': request.form.get('account_id'),
            'amount': float(request.form.get('amount', 0)),
            'external_bank_name': request.form.get('external_bank_name'),
            'external_account_number': request.form.get('external_account_number'),
            'direction': request.form.get('direction'),
            'description': request.form.get('description', '')
        }
        
        data, status = api_request('POST', '/api/transfers/external', form_data, token=token)
        
        if status == 200:
            flash(data.get('message', 'Virement externe effectué !'), 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(data.get('error', 'Erreur'), 'danger')
    
    return render_template('transfer_external.html',
        user=session.get('user', {}),
        accounts=accounts_data.get('accounts', [])
    )


# ============================================
# ROUTES - HISTORIQUE
# ============================================
@app.route('/transactions')
@login_required
def transactions():
    """Historique des transactions."""
    token = session['token']
    account_id = request.args.get('account_id', '')
    
    endpoint = '/api/transactions?limit=100'
    if account_id:
        endpoint += f'&account_id={account_id}'
    
    data, status = api_request('GET', endpoint, token=token)
    accounts_data, _ = api_request('GET', '/api/accounts', token=token)
    
    return render_template('transactions.html',
        user=session.get('user', {}),
        transactions=data.get('transactions', []),
        accounts=accounts_data.get('accounts', []),
        selected_account=account_id
    )


# ============================================
# DÉMARRAGE
# ============================================
if __name__ == '__main__':
    print("🐉 DragonBank Frontend starting on port 8080...")
    app.run(host='0.0.0.0', port=8080, debug=False)