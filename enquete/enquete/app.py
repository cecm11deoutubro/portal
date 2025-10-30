from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///polls.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Modelos do Banco de Dados
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='estudante')  # admin, funcionario, estudante

class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    question = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text, nullable=False)  # JSON ou string separada por vírgula
    expiration = db.Column(db.DateTime)
    active = db.Column(db.Boolean, default=True)
    total_votes = db.Column(db.Integer, default=0)
    votes = db.relationship('Vote', backref='poll', lazy=True, cascade='all, delete-orphan')

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    option = db.Column(db.String(100), nullable=False)

# Criar tabelas e usuário admin padrão (rode uma vez)
with app.app_context():
    db.create_all()
    
    # Criar usuário admin padrão se não existir
    default_admin = User.query.filter_by(username='admin').first()
    if not default_admin:
        default_admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(default_admin)
        db.session.commit()
        print("Usuário admin padrão criado: username='admin', senha='admin123'")  # Log para confirmação

# Função auxiliar para contar votos
def get_vote_count(poll_id):
    votes = Vote.query.filter_by(poll_id=poll_id).all()
    count = {}
    for vote in votes:
        count[vote.option] = count.get(vote.option, 0) + 1
    return count

# Rota Raiz (Correção do 404)
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Verificar se é estudante (senha = email)
        if '@' in password and password.endswith('@escola.pr.gov.br'):
            # Auto-registro para estudantes
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User(username=username, password_hash=generate_password_hash(password), role='estudante')
                db.session.add(user)
                db.session.commit()
                flash('Registrado como estudante com sucesso!', 'success')
            else:
                flash('Usuário já existe. Faça login.', 'warning')
                return render_template('login.html')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciais inválidas.', 'error')
    
    return render_template('login.html')

# Logout
@app.route('/logout')
def logout():
    session.clear()
    flash('Logout realizado.', 'info')
    return redirect(url_for('login'))

# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Filtrar enquetes ativas (não expiradas e ativas)
    now = datetime.now()
    polls = Poll.query.filter(
        Poll.active == True,
        (Poll.expiration > now) | (Poll.expiration.is_(None))
    ).all()
    
    # Adicionar contagem de votos para cada poll
    for poll in polls:
        poll.vote_count = get_vote_count(poll.id)
    
    return render_template('dashboard.html', polls=polls)

# Votar
@app.route('/vote/<int:poll_id>', methods=['POST'])
def vote(poll_id):
    if 'user_id' not in session:
        flash('Autenticação necessária.', 'error')
        return redirect(url_for('login'))
    
    poll = Poll.query.get_or_404(poll_id)
    if not poll.active or (poll.expiration and poll.expiration < datetime.now()):
        flash('Enquete não está mais ativa.', 'error')
        return redirect(url_for('dashboard'))
    
    option = request.form['option'].strip()
    options_list = [opt.strip() for opt in poll.options.split(',')]
    if option not in options_list:
        flash('Opção inválida.', 'error')
        return redirect(url_for('dashboard'))
    
    # Verificar se já votou
    existing_vote = Vote.query.filter_by(user_id=session['user_id'], poll_id=poll_id).first()
    if existing_vote:
        flash('Você já votou nesta enquete.', 'warning')
        return redirect(url_for('dashboard'))
    
    # Registrar voto
    vote_entry = Vote(user_id=session['user_id'], poll_id=poll_id, option=option)
    db.session.add(vote_entry)
    poll.total_votes += 1
    db.session.commit()
    
    flash('Voto registrado com sucesso!', 'success')
    return redirect(url_for('dashboard'))

# Resultados
@app.route('/results/<int:poll_id>')
def results(poll_id):
    if 'user_id' not in session or session['role'] not in ['admin', 'funcionario']:
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    poll = Poll.query.get_or_404(poll_id)
    vote_count = get_vote_count(poll_id)
    total_votes = poll.total_votes or 0
    options = [opt.strip() for opt in poll.options.split(',')]
    
    return render_template('results.html', poll=poll, options=options, vote_count=vote_count, total_votes=total_votes)

# Criar Enquete (Admin)
@app.route('/create_poll', methods=['GET', 'POST'])
def create_poll():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form['title']
        question = request.form['question']
        options_str = request.form['options']
        expiration_str = request.form.get('expiration')
        
        expiration = None
        if expiration_str:
            try:
                expiration = datetime.strptime(expiration_str, '%Y-%m-%d %H:%M')
            except ValueError:
                flash('Formato de expiração inválido. Use YYYY-MM-DD HH:MM.', 'error')
                return render_template('create_poll.html')
        
        poll = Poll(title=title, question=question, options=options_str, expiration=expiration)
        db.session.add(poll)
        db.session.commit()
        flash('Enquete criada com sucesso!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('create_poll.html')

# Gerenciar Enquetes (Admin)
@app.route('/admin_polls')
def admin_polls():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    polls = Poll.query.all()
    now = datetime.now()
    for poll in polls:
        poll.is_expired = poll.expiration and poll.expiration < now
    return render_template('admin_polls.html', polls=polls)

# Fechar Enquete
@app.route('/close_poll/<int:poll_id>', methods=['POST'])
def close_poll(poll_id):
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('admin_polls'))
    
    poll = Poll.query.get_or_404(poll_id)
    poll.active = False
    db.session.commit()
    flash('Enquete fechada.', 'success')
    return redirect(url_for('admin_polls'))

# Deletar Enquete
@app.route('/delete_poll/<int:poll_id>', methods=['POST'])
def delete_poll(poll_id):
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('admin_polls'))
    
    poll = Poll.query.get_or_404(poll_id)
    db.session.delete(poll)
    db.session.commit()
    flash('Enquete deletada.', 'success')
    return redirect(url_for('admin_polls'))

# Gerenciar Usuários (Admin)
@app.route('/admin_users')
def admin_users():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    return render_template('admin_users.html', users=users)

# Adicionar Usuário (Admin)
@app.route('/admin_add_user', methods=['POST'])
def admin_add_user():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    username = request.form['username']
    password = request.form['password']
    role = request.form.get('role', 'admin')
    
    if User.query.filter_by(username=username).first():
        flash('Usuário já existe.', 'error')
        return redirect(url_for('dashboard'))
    
    user = User(username=username, password_hash=generate_password_hash(password), role=role)
    db.session.add(user)
    db.session.commit()
    flash(f'Usuário {role} adicionado com sucesso!', 'success')
    return redirect(url_for('dashboard'))

# Registrar Novo Admin (Página separada)
@app.route('/admin_register', methods=['GET', 'POST'])
def admin_register():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Usuário já existe.', 'error')
            return render_template('admin_register.html')
        
        user = User(username=username, password_hash=generate_password_hash(password), role='admin')
        db.session.add(user)
        db.session.commit()
        flash('Novo admin registrado!', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin_register.html')

# Enquete Multi-pergunta (Exemplo básico, ajuste conforme necessário)
@app.route('/enquete/<int:enquete_id>', methods=['GET', 'POST'])
def enquete(enquete_id):
    # Aqui você pode carregar perguntas de um JSON ou DB separado
    # Por simplicidade, exemplo com perguntas fixas
    perguntas = [
        {"pergunta": "Qual é a sua opinião sobre o uniforme?", "tipo": "opcoes", "opcoes": ["Gosto", "Não gosto", "Indiferente"]},
        {"pergunta": "Sugestões para melhoria da escola?", "tipo": "texto"}
    ]
    
    if request.method == 'POST':
        data = request.json.get('respostas', [])
        # Salvar respostas (exemplo: log ou DB)
        print(f"Respostas para enquete {enquete_id}: {data}")
        return jsonify({'status': 'success'})
    
    return render_template('enquete.html', perguntas=perguntas, enquete_id=enquete_id)

# Favicon (Correção do 404)
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')  # Crie um arquivo estático se necessário

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Garante que as tabelas existam
    app.run(host='0.0.0.0', port=5000, debug=True)