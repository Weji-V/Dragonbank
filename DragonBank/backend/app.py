"""
DragonBank - Backend API
========================
API REST pour la gestion bancaire complète.
"""

import os
import uuid
import decimal
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import bcrypt
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify
from flask_cors import CORS

# ============================================
# CONFIGURATION
# ============================================
app = Flask(__name__)
CORS(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://dragonadmin:dragonpass@db:5432/dragonbank')

# ============================================
# UTILITAIRES BASE DE DONNÉES
# ============================================
def get_db_connection():
    """Crée une connexion à la base de données PostgreSQL."""
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    conn.autocommit = False
    return conn


def decimal_to_float(obj):
    """Convertit les objets Decimal en float pour la sérialisation JSON."""
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return obj


def serialize_row(row):
    """Sérialise une ligne de résultat de la DB."""
    if row is None:
        return None
    return {k: decimal_to_float(v) for k, v in dict(row).items()}


def serialize_rows(rows):
    """Sérialise plusieurs lignes."""
    return [serialize_row(row) for row in rows]


# ============================================
# AUTHENTIFICATION JWT
# ============================================
def generate_token(user_id, email):
    """Génère un token JWT."""
    payload = {
        'user_id': str(user_id),
        'email': email,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24),
        'iat': datetime.now(timezone.utc)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def token_required(f):
    """Décorateur pour protéger les routes avec JWT."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
        
        if not token:
            return jsonify({'error': 'Token manquant'}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user_id = data['user_id']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expiré'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token invalide'}), 401
        
        return f(current_user_id, *args, **kwargs)
    return decorated


# ============================================
# ROUTES - SANTÉ
# ============================================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Vérification de santé de l'API."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
        return jsonify({
            'status': 'healthy',
            'service': 'DragonBank Backend API',
            'database': 'connected',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


# ============================================
# ROUTES - AUTHENTIFICATION
# ============================================
@app.route('/api/auth/register', methods=['POST'])
def register():
    """Inscription d'un nouvel utilisateur."""
    data = request.get_json()
    
    required_fields = ['email', 'password', 'first_name', 'last_name']
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({'error': f'Le champ {field} est requis'}), 400
    
    # Validation email
    if '@' not in data['email'] or '.' not in data['email']:
        return jsonify({'error': 'Email invalide'}), 400
    
    # Validation mot de passe (min 6 caractères)
    if len(data['password']) < 6:
        return jsonify({'error': 'Le mot de passe doit contenir au moins 6 caractères'}), 400
    
    # Hash du mot de passe
    password_hash = bcrypt.hashpw(
        data['password'].encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Vérifier si l'email existe déjà
        cur.execute('SELECT id FROM users WHERE email = %s', (data['email'],))
        if cur.fetchone():
            return jsonify({'error': 'Cet email est déjà utilisé'}), 409
        
        # Créer l'utilisateur
        user_id = str(uuid.uuid4())
        cur.execute('''
            INSERT INTO users (id, email, password_hash, first_name, last_name, phone, address, date_of_birth)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, email, first_name, last_name, created_at
        ''', (
            user_id,
            data['email'],
            password_hash,
            data['first_name'],
            data['last_name'],
            data.get('phone', ''),
            data.get('address', ''),
            data.get('date_of_birth')
        ))
        user = cur.fetchone()
        
        # Créer automatiquement un compte courant
        account_number = f"DRG{str(uuid.uuid4().int)[:13].zfill(13)}"
        cur.execute('''
            INSERT INTO accounts (user_id, account_number, account_type, balance)
            VALUES (%s, %s, 'courant', 100.00)
        ''', (user_id, account_number))
        
        conn.commit()
        
        # Générer un token
        token = generate_token(user_id, data['email'])
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (user_id, 'REGISTER', '{"action": "user_registered"}', request.remote_addr))
        conn.commit()
        
        return jsonify({
            'message': 'Inscription réussie',
            'user': serialize_row(user),
            'token': token,
            'account_number': account_number
        }), 201
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur lors de l\'inscription: {str(e)}'}), 500
    finally:
        conn.close()


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Connexion d'un utilisateur."""
    data = request.get_json()
    
    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Email et mot de passe requis'}), 400
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, email, password_hash, first_name, last_name, is_active
            FROM users WHERE email = %s
        ''', (data['email'],))
        user = cur.fetchone()
        
        if not user:
            return jsonify({'error': 'Email ou mot de passe incorrect'}), 401
        
        if not user['is_active']:
            return jsonify({'error': 'Compte désactivé'}), 403
        
        # Vérifier le mot de passe
        if not bcrypt.checkpw(
            data['password'].encode('utf-8'),
            user['password_hash'].encode('utf-8')
        ):
            return jsonify({'error': 'Email ou mot de passe incorrect'}), 401
        
        # Mettre à jour le dernier login
        cur.execute(
            'UPDATE users SET last_login = NOW() WHERE id = %s',
            (str(user['id']),)
        )
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (str(user['id']), 'LOGIN', '{"action": "user_login"}', request.remote_addr))
        
        conn.commit()
        
        token = generate_token(user['id'], user['email'])
        
        return jsonify({
            'message': 'Connexion réussie',
            'token': token,
            'user': {
                'id': str(user['id']),
                'email': user['email'],
                'first_name': user['first_name'],
                'last_name': user['last_name']
            }
        }), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur de connexion: {str(e)}'}), 500
    finally:
        conn.close()


# ============================================
# ROUTES - PROFIL UTILISATEUR
# ============================================
@app.route('/api/user/profile', methods=['GET'])
@token_required
def get_profile(current_user_id):
    """Récupère le profil de l'utilisateur connecté."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, email, first_name, last_name, phone, address, 
                   date_of_birth, created_at, last_login
            FROM users WHERE id = %s
        ''', (current_user_id,))
        user = cur.fetchone()
        
        if not user:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
        
        return jsonify({'user': serialize_row(user)}), 200
    finally:
        conn.close()


# ============================================
# ROUTES - COMPTES BANCAIRES
# ============================================
@app.route('/api/accounts', methods=['GET'])
@token_required
def get_accounts(current_user_id):
    """Récupère tous les comptes de l'utilisateur."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, account_number, account_type, balance, currency, 
                   status, interest_rate, created_at
            FROM accounts 
            WHERE user_id = %s AND status = 'active'
            ORDER BY created_at ASC
        ''', (current_user_id,))
        accounts = cur.fetchall()
        
        return jsonify({'accounts': serialize_rows(accounts)}), 200
    finally:
        conn.close()


@app.route('/api/accounts', methods=['POST'])
@token_required
def open_account(current_user_id):
    """Ouverture d'un nouveau compte bancaire."""
    data = request.get_json()
    account_type = data.get('account_type', 'courant')
    
    valid_types = ['courant', 'livret_a', 'assurance_vie']
    if account_type not in valid_types:
        return jsonify({'error': f'Type de compte invalide. Types valides: {valid_types}'}), 400
    
    # Taux d'intérêt selon le type
    interest_rates = {
        'courant': 0.0000,
        'livret_a': 0.0300,
        'assurance_vie': 0.0200
    }
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Vérifier qu'il n'a pas déjà ce type de compte (sauf courant)
        if account_type != 'courant':
            cur.execute('''
                SELECT id FROM accounts 
                WHERE user_id = %s AND account_type = %s AND status = 'active'
            ''', (current_user_id, account_type))
            if cur.fetchone():
                return jsonify({'error': f'Vous avez déjà un compte {account_type}'}), 409
        
        account_number = f"DRG{str(uuid.uuid4().int)[:13].zfill(13)}"
        initial_balance = float(data.get('initial_deposit', 0))
        
        cur.execute('''
            INSERT INTO accounts (user_id, account_number, account_type, balance, interest_rate)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, account_number, account_type, balance, interest_rate, created_at
        ''', (
            current_user_id,
            account_number,
            account_type,
            initial_balance,
            interest_rates[account_type]
        ))
        account = cur.fetchone()
        
        # Si dépôt initial, créer une transaction
        if initial_balance > 0:
            cur.execute('''
                INSERT INTO transactions (to_account_id, transaction_type, amount, description, status, executed_at)
                VALUES (%s, 'depot', %s, 'Dépôt initial à l''ouverture du compte', 'completed', NOW())
            ''', (str(account['id']), initial_balance))
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (
            current_user_id, 'OPEN_ACCOUNT',
            f'{{"account_type": "{account_type}", "account_number": "{account_number}"}}',
            request.remote_addr
        ))
        
        conn.commit()
        
        return jsonify({
            'message': f'Compte {account_type} ouvert avec succès',
            'account': serialize_row(account)
        }), 201
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur lors de l\'ouverture du compte: {str(e)}'}), 500
    finally:
        conn.close()


@app.route('/api/accounts/<account_id>', methods=['GET'])
@token_required
def get_account_detail(current_user_id, account_id):
    """Détails d'un compte spécifique."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, account_number, account_type, balance, currency, 
                   status, interest_rate, created_at, updated_at
            FROM accounts 
            WHERE id = %s AND user_id = %s
        ''', (account_id, current_user_id))
        account = cur.fetchone()
        
        if not account:
            return jsonify({'error': 'Compte non trouvé'}), 404
        
        return jsonify({'account': serialize_row(account)}), 200
    finally:
        conn.close()


# ============================================
# ROUTES - BÉNÉFICIAIRES
# ============================================
@app.route('/api/beneficiaries', methods=['GET'])
@token_required
def get_beneficiaries(current_user_id):
    """Liste des bénéficiaires de l'utilisateur."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, beneficiary_name, bank_name, account_number, iban, bic, status, created_at
            FROM beneficiaries 
            WHERE user_id = %s
            ORDER BY created_at DESC
        ''', (current_user_id,))
        beneficiaries = cur.fetchall()
        
        return jsonify({'beneficiaries': serialize_rows(beneficiaries)}), 200
    finally:
        conn.close()


@app.route('/api/beneficiaries', methods=['POST'])
@token_required
def add_beneficiary(current_user_id):
    """Ajout d'un nouveau bénéficiaire."""
    data = request.get_json()
    
    required_fields = ['beneficiary_name', 'account_number']
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({'error': f'Le champ {field} est requis'}), 400
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Vérifier que le bénéficiaire n'existe pas déjà
        cur.execute('''
            SELECT id FROM beneficiaries 
            WHERE user_id = %s AND account_number = %s
        ''', (current_user_id, data['account_number']))
        if cur.fetchone():
            return jsonify({'error': 'Ce bénéficiaire existe déjà'}), 409
        
        # Vérifier que ce n'est pas son propre compte
        cur.execute('''
            SELECT id FROM accounts 
            WHERE user_id = %s AND account_number = %s
        ''', (current_user_id, data['account_number']))
        if cur.fetchone():
            return jsonify({'error': 'Vous ne pouvez pas vous ajouter vous-même comme bénéficiaire'}), 400
        
        cur.execute('''
            INSERT INTO beneficiaries (user_id, beneficiary_name, bank_name, account_number, iban, bic)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, beneficiary_name, bank_name, account_number, iban, bic, status, created_at
        ''', (
            current_user_id,
            data['beneficiary_name'],
            data.get('bank_name', 'DragonBank'),
            data['account_number'],
            data.get('iban', ''),
            data.get('bic', '')
        ))
        beneficiary = cur.fetchone()
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (
            current_user_id, 'ADD_BENEFICIARY',
            f'{{"beneficiary_name": "{data["beneficiary_name"]}"}}',
            request.remote_addr
        ))
        
        conn.commit()
        
        return jsonify({
            'message': 'Bénéficiaire ajouté avec succès',
            'beneficiary': serialize_row(beneficiary)
        }), 201
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur: {str(e)}'}), 500
    finally:
        conn.close()


@app.route('/api/beneficiaries/<beneficiary_id>', methods=['DELETE'])
@token_required
def delete_beneficiary(current_user_id, beneficiary_id):
    """Suppression d'un bénéficiaire."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            DELETE FROM beneficiaries 
            WHERE id = %s AND user_id = %s
            RETURNING id
        ''', (beneficiary_id, current_user_id))
        deleted = cur.fetchone()
        
        if not deleted:
            return jsonify({'error': 'Bénéficiaire non trouvé'}), 404
        
        conn.commit()
        return jsonify({'message': 'Bénéficiaire supprimé'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ============================================
# ROUTES - VIREMENTS / TRANSACTIONS
# ============================================
@app.route('/api/transfers/internal', methods=['POST'])
@token_required
def transfer_internal(current_user_id):
    """
    Virement interne entre ses propres comptes.
    """
    data = request.get_json()
    
    required_fields = ['from_account_id', 'to_account_id', 'amount']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Le champ {field} est requis'}), 400
    
    amount = float(data['amount'])
    if amount <= 0:
        return jsonify({'error': 'Le montant doit être positif'}), 400
    
    if data['from_account_id'] == data['to_account_id']:
        return jsonify({'error': 'Les comptes source et destination doivent être différents'}), 400
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Vérifier compte source
        cur.execute('''
            SELECT id, balance, account_number, account_type FROM accounts 
            WHERE id = %s AND user_id = %s AND status = 'active'
        ''', (data['from_account_id'], current_user_id))
        from_account = cur.fetchone()
        
        if not from_account:
            return jsonify({'error': 'Compte source non trouvé'}), 404
        
        if float(from_account['balance']) < amount:
            return jsonify({'error': 'Solde insuffisant'}), 400
        
        # Vérifier compte destination
        cur.execute('''
            SELECT id, account_number, account_type FROM accounts 
            WHERE id = %s AND user_id = %s AND status = 'active'
        ''', (data['to_account_id'], current_user_id))
        to_account = cur.fetchone()
        
        if not to_account:
            return jsonify({'error': 'Compte destination non trouvé'}), 404
        
        # Effectuer le virement
        cur.execute(
            'UPDATE accounts SET balance = balance - %s WHERE id = %s',
            (amount, data['from_account_id'])
        )
        cur.execute(
            'UPDATE accounts SET balance = balance + %s WHERE id = %s',
            (amount, data['to_account_id'])
        )
        
        # Enregistrer la transaction
        description = data.get('description', 
            f"Virement interne {from_account['account_type']} → {to_account['account_type']}")
        cur.execute('''
            INSERT INTO transactions 
            (from_account_id, to_account_id, transaction_type, amount, description, status, executed_at)
            VALUES (%s, %s, 'virement_interne', %s, %s, 'completed', NOW())
            RETURNING id, amount, description, status, created_at
        ''', (data['from_account_id'], data['to_account_id'], amount, description))
        transaction = cur.fetchone()
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (
            current_user_id, 'TRANSFER_INTERNAL',
            f'{{"amount": {amount}, "from": "{from_account["account_number"]}", "to": "{to_account["account_number"]}"}}',
            request.remote_addr
        ))
        
        conn.commit()
        
        return jsonify({
            'message': 'Virement interne effectué avec succès',
            'transaction': serialize_row(transaction)
        }), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur lors du virement: {str(e)}'}), 500
    finally:
        conn.close()


@app.route('/api/transfers/person', methods=['POST'])
@token_required
def transfer_to_person(current_user_id):
    """
    Virement vers une autre personne (bénéficiaire) dans DragonBank.
    """
    data = request.get_json()
    
    required_fields = ['from_account_id', 'beneficiary_id', 'amount']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Le champ {field} est requis'}), 400
    
    amount = float(data['amount'])
    if amount <= 0:
        return jsonify({'error': 'Le montant doit être positif'}), 400
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Vérifier compte source
        cur.execute('''
            SELECT id, balance, account_number FROM accounts 
            WHERE id = %s AND user_id = %s AND status = 'active'
        ''', (data['from_account_id'], current_user_id))
        from_account = cur.fetchone()
        
        if not from_account:
            return jsonify({'error': 'Compte source non trouvé'}), 404
        
        if float(from_account['balance']) < amount:
            return jsonify({'error': 'Solde insuffisant'}), 400
        
        # Vérifier le bénéficiaire
        cur.execute('''
            SELECT id, beneficiary_name, account_number, bank_name 
            FROM beneficiaries 
            WHERE id = %s AND user_id = %s AND status = 'approved'
        ''', (data['beneficiary_id'], current_user_id))
        beneficiary = cur.fetchone()
        
        if not beneficiary:
            return jsonify({'error': 'Bénéficiaire non trouvé ou non approuvé'}), 404
        
        # Chercher le compte destination dans DragonBank
        cur.execute('''
            SELECT id, account_number FROM accounts 
            WHERE account_number = %s AND status = 'active'
        ''', (beneficiary['account_number'],))
        to_account = cur.fetchone()
        
        if not to_account:
            return jsonify({'error': 'Compte bénéficiaire introuvable dans DragonBank'}), 404
        
        # Effectuer le virement
        cur.execute(
            'UPDATE accounts SET balance = balance - %s WHERE id = %s',
            (amount, data['from_account_id'])
        )
        cur.execute(
            'UPDATE accounts SET balance = balance + %s WHERE id = %s',
            (amount, str(to_account['id']))
        )
        
        description = data.get('description', 
            f"Virement à {beneficiary['beneficiary_name']}")
        cur.execute('''
            INSERT INTO transactions 
            (from_account_id, to_account_id, transaction_type, amount, description, status, executed_at)
            VALUES (%s, %s, 'virement_entre_personnes', %s, %s, 'completed', NOW())
            RETURNING id, amount, description, status, created_at
        ''', (data['from_account_id'], str(to_account['id']), amount, description))
        transaction = cur.fetchone()
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (
            current_user_id, 'TRANSFER_PERSON',
            f'{{"amount": {amount}, "beneficiary": "{beneficiary["beneficiary_name"]}"}}',
            request.remote_addr
        ))
        
        conn.commit()
        
        return jsonify({
            'message': f'Virement de {amount}€ à {beneficiary["beneficiary_name"]} effectué',
            'transaction': serialize_row(transaction)
        }), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur lors du virement: {str(e)}'}), 500
    finally:
        conn.close()


@app.route('/api/transfers/external', methods=['POST'])
@token_required
def transfer_external(current_user_id):
    """
    Virement depuis/vers une autre banque (simulé).
    """
    data = request.get_json()
    
    required_fields = ['account_id', 'amount', 'external_bank_name', 'external_account_number', 'direction']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Le champ {field} est requis'}), 400
    
    amount = float(data['amount'])
    if amount <= 0:
        return jsonify({'error': 'Le montant doit être positif'}), 400
    
    direction = data['direction']  # 'incoming' ou 'outgoing'
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Vérifier le compte
        cur.execute('''
            SELECT id, balance, account_number FROM accounts 
            WHERE id = %s AND user_id = %s AND status = 'active'
        ''', (data['account_id'], current_user_id))
        account = cur.fetchone()
        
        if not account:
            return jsonify({'error': 'Compte non trouvé'}), 404
        
        if direction == 'outgoing' and float(account['balance']) < amount:
            return jsonify({'error': 'Solde insuffisant'}), 400
        
        # Effectuer l'opération
        if direction == 'outgoing':
            cur.execute(
                'UPDATE accounts SET balance = balance - %s WHERE id = %s',
                (amount, data['account_id'])
            )
            description = f"Virement sortant vers {data['external_bank_name']} - {data['external_account_number']}"
            from_id = data['account_id']
            to_id = None
        else:  # incoming
            cur.execute(
                'UPDATE accounts SET balance = balance + %s WHERE id = %s',
                (amount, data['account_id'])
            )
            description = f"Virement entrant depuis {data['external_bank_name']} - {data['external_account_number']}"
            from_id = None
            to_id = data['account_id']
        
        description = data.get('description', description)
        
        cur.execute('''
            INSERT INTO transactions 
            (from_account_id, to_account_id, transaction_type, amount, description, 
             status, external_bank_name, external_account_number, executed_at)
            VALUES (%s, %s, 'virement_externe', %s, %s, 'completed', %s, %s, NOW())
            RETURNING id, amount, description, status, created_at
        ''', (from_id, to_id, amount, description, 
              data['external_bank_name'], data['external_account_number']))
        transaction = cur.fetchone()
        
        # Log d'audit
        cur.execute('''
            INSERT INTO audit_logs (user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s)
        ''', (
            current_user_id, 'TRANSFER_EXTERNAL',
            f'{{"amount": {amount}, "direction": "{direction}", "bank": "{data["external_bank_name"]}"}}',
            request.remote_addr
        ))
        
        conn.commit()
        
        return jsonify({
            'message': f'Virement externe {"sortant" if direction == "outgoing" else "entrant"} de {amount}€ effectué',
            'transaction': serialize_row(transaction)
        }), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Erreur: {str(e)}'}), 500
    finally:
        conn.close()


# ============================================
# ROUTES - HISTORIQUE DES TRANSACTIONS
# ============================================
@app.route('/api/transactions', methods=['GET'])
@token_required
def get_transactions(current_user_id):
    """Récupère l'historique des transactions de l'utilisateur."""
    limit = request.args.get('limit', 50, type=int)
    account_id = request.args.get('account_id', None)
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        if account_id:
            cur.execute('''
                SELECT t.id, t.from_account_id, t.to_account_id, t.transaction_type,
                       t.amount, t.currency, t.description, t.status, t.reference,
                       t.external_bank_name, t.external_account_number,
                       t.created_at, t.executed_at,
                       fa.account_number as from_account_number,
                       ta.account_number as to_account_number
                FROM transactions t
                LEFT JOIN accounts fa ON t.from_account_id = fa.id
                LEFT JOIN accounts ta ON t.to_account_id = ta.id
                WHERE (t.from_account_id = %s OR t.to_account_id = %s)
                ORDER BY t.created_at DESC
                LIMIT %s
            ''', (account_id, account_id, limit))
        else:
            cur.execute('''
                SELECT t.id, t.from_account_id, t.to_account_id, t.transaction_type,
                       t.amount, t.currency, t.description, t.status, t.reference,
                       t.external_bank_name, t.external_account_number,
                       t.created_at, t.executed_at,
                       fa.account_number as from_account_number,
                       ta.account_number as to_account_number
                FROM transactions t
                LEFT JOIN accounts fa ON t.from_account_id = fa.id
                LEFT JOIN accounts ta ON t.to_account_id = ta.id
                WHERE fa.user_id = %s OR ta.user_id = %s
                ORDER BY t.created_at DESC
                LIMIT %s
            ''', (current_user_id, current_user_id, limit))
        
        transactions = cur.fetchall()
        
        return jsonify({'transactions': serialize_rows(transactions)}), 200
    finally:
        conn.close()


# ============================================
# ROUTES - STATISTIQUES
# ============================================
@app.route('/api/stats', methods=['GET'])
@token_required
def get_stats(current_user_id):
    """Statistiques du compte utilisateur."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Solde total
        cur.execute('''
            SELECT COALESCE(SUM(balance), 0) as total_balance,
                   COUNT(*) as total_accounts
            FROM accounts 
            WHERE user_id = %s AND status = 'active'
        ''', (current_user_id,))
        balance_stats = cur.fetchone()
        
        # Nombre de transactions ce mois
        cur.execute('''
            SELECT COUNT(*) as monthly_transactions,
                   COALESCE(SUM(CASE WHEN fa.user_id = %s THEN amount ELSE 0 END), 0) as total_sent,
                   COALESCE(SUM(CASE WHEN ta.user_id = %s THEN amount ELSE 0 END), 0) as total_received
            FROM transactions t
            LEFT JOIN accounts fa ON t.from_account_id = fa.id
            LEFT JOIN accounts ta ON t.to_account_id = ta.id
            WHERE (fa.user_id = %s OR ta.user_id = %s)
            AND t.created_at >= date_trunc('month', CURRENT_DATE)
            AND t.status = 'completed'
        ''', (current_user_id, current_user_id, current_user_id, current_user_id))
        transaction_stats = cur.fetchone()
        
        # Nombre de bénéficiaires
        cur.execute('''
            SELECT COUNT(*) as total_beneficiaries
            FROM beneficiaries WHERE user_id = %s
        ''', (current_user_id,))
        ben_stats = cur.fetchone()
        
        return jsonify({
            'stats': {
                'total_balance': decimal_to_float(balance_stats['total_balance']),
                'total_accounts': balance_stats['total_accounts'],
                'monthly_transactions': transaction_stats['monthly_transactions'],
                'total_sent': decimal_to_float(transaction_stats['total_sent']),
                'total_received': decimal_to_float(transaction_stats['total_received']),
                'total_beneficiaries': ben_stats['total_beneficiaries']
            }
        }), 200
    finally:
        conn.close()


# ============================================
# DÉMARRAGE
# ============================================
if __name__ == '__main__':
    print("🐉 DragonBank Backend API starting...")
    print(f"📡 Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'configured'}")
    app.run(host='0.0.0.0', port=5000, debug=False)