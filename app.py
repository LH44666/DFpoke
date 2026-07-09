import os
import re
import base64
import sqlite3
import secrets
import threading
import time
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, jsonify, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

def hash_password(password):
    return generate_password_hash(password, method='pbkdf2:sha256')

def verify_password(stored_hash, password):
    return check_password_hash(stored_hash, password)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=30)

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dfpoke.db')

SUITS = ['spade', 'heart', 'diamond', 'club']
SUIT_NAMES = {'spade': '♠', 'heart': '♥', 'diamond': '♦', 'club': '♣'}
RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
SPECIAL = ['joker_black', 'joker_red', 'card_box']
SPECIAL_NAMES = {'joker_black': '小王', 'joker_red': '大王', 'card_box': '牌盒'}
ANNOUNCE_CARDS = {'joker_black': '小王', 'joker_red': '大王', 'card_box': '牌盒'}

ALL_CARDS = [f"{suit}_{rank}" for suit in SUITS for rank in RANKS] + SPECIAL
TOTAL = len(ALL_CARDS)  # 55


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA busy_timeout=5000')
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.context_processor
def inject_announcements():
    try:
        db = get_db()
        rows = db.execute(
            'SELECT username, event_type, card_key, created_at FROM announcements ORDER BY id DESC LIMIT 5'
        ).fetchall()
        items = []
        cst = timezone(timedelta(hours=8))
        for r in rows:
            try:
                utc_dt = datetime.strptime(r['created_at'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                t = utc_dt.astimezone(cst).strftime('%Y-%m-%d %H:%M')
            except Exception:
                t = r['created_at'][:16] if r['created_at'] else ''
            if r['event_type'] == 'complete':
                msg = f"{r['username']} 于 {t} 集齐了全部 {TOTAL} 张牌！"
            else:
                card_cn = ANNOUNCE_CARDS.get(r['card_key'], r['card_key'])
                msg = f"{r['username']} 于 {t} 获得了 {card_cn}"
            items.append({'msg': msg})
        return {'announcements': items}
    except Exception:
        return {'announcements': []}



def init_db():
    db = sqlite3.connect(DATABASE, timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        show_in_leaderboard INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    try:
        db.execute('ALTER TABLE users ADD COLUMN show_in_leaderboard INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass
    db.execute('''CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        card_key TEXT NOT NULL,
        owned INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, card_key)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        event_type TEXT NOT NULL,
        card_key TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(username, event_type, card_key)
    )''')
    db.commit()
    db.close()


def init_user_cards(db, user_id):
    for card_key in ALL_CARDS:
        db.execute(
            'INSERT OR IGNORE INTO cards (user_id, card_key, owned) VALUES (?, ?, 0)',
            (user_id, card_key)
        )
    db.commit()


@app.route('/')
def index():
    db = get_db()
    users = db.execute('''
        SELECT u.username, u.created_at,
               COUNT(CASE WHEN c.owned = 1 THEN 1 END) as collected,
               ? as total
        FROM users u
        LEFT JOIN cards c ON u.id = c.user_id
        WHERE u.show_in_leaderboard = 1
        GROUP BY u.id
        HAVING collected < ?
        ORDER BY collected DESC, u.created_at ASC
        LIMIT 10
    ''', (TOTAL, TOTAL)).fetchall()
    total_users = db.execute('SELECT COUNT(*) as cnt FROM users').fetchone()['cnt']
    completed_users = db.execute('''
        SELECT COUNT(*) as cnt FROM (
            SELECT u.id FROM users u
            JOIN cards c ON u.id = c.user_id
            GROUP BY u.id
            HAVING COUNT(CASE WHEN c.owned = 1 THEN 1 END) = ?
        )
    ''', (TOTAL,)).fetchone()['cnt']
    keywords = get_daily_keywords()
    return render_template('index.html', users=users, total=TOTAL, keywords=keywords,
                           total_users=total_users, completed_users=completed_users)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('用户名和密码不能为空', 'error')
            return redirect(url_for('register'))
        if len(username) < 2 or len(username) > 20:
            flash('用户名长度需要在2-20个字符之间', 'error')
            return redirect(url_for('register'))
        if not username.isalnum():
            flash('用户名只能包含字母和数字', 'error')
            return redirect(url_for('register'))
        if len(password) < 4:
            flash('密码至少4个字符', 'error')
            return redirect(url_for('register'))
        db = get_db()
        existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            flash('用户名已存在', 'error')
            return redirect(url_for('register'))
        db.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, hash_password(password))
        )
        db.commit()
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        init_user_cards(db, user['id'])
        session.permanent = True
        session['user'] = username
        flash('注册成功！', 'success')
        return redirect(url_for('user_page', username=username))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and verify_password(user['password_hash'], password):
            session.permanent = True
            session['user'] = username
            flash('登录成功！', 'success')
            return redirect(url_for('user_page', username=username))
        flash('用户名或密码错误', 'error')
        return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('已退出登录', 'success')
    return redirect(url_for('index'))


@app.route('/<username>')
def user_page(username):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        abort(404)
    cards = db.execute(
        'SELECT card_key, owned FROM cards WHERE user_id = ? ORDER BY id',
        (user['id'],)
    ).fetchall()
    card_map = {c['card_key']: c['owned'] for c in cards}
    is_owner = session.get('user') == username
    collected = sum(1 for v in card_map.values() if v)
    show_in_lb = user['show_in_leaderboard'] if 'show_in_leaderboard' in user.keys() else 1
    return render_template(
        'tracker.html',
        username=username,
        card_map=card_map,
        suits=SUITS,
        suit_names=SUIT_NAMES,
        ranks=RANKS,
        special=SPECIAL,
        special_names=SPECIAL_NAMES,
        is_owner=is_owner,
        collected=collected,
        total=TOTAL,
        show_in_lb=show_in_lb
    )


@app.route('/<username>/toggle', methods=['POST'])
def toggle_card(username):
    if session.get('user') != username:
        return jsonify({'error': '无权限'}), 403
    db = get_db()
    user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    card_key = request.json.get('card_key')
    if card_key not in ALL_CARDS:
        return jsonify({'error': '无效的卡牌'}), 400
    card = db.execute(
        'SELECT owned FROM cards WHERE user_id = ? AND card_key = ?',
        (user['id'], card_key)
    ).fetchone()
    new_val = 0 if card['owned'] else 1
    db.execute(
        'UPDATE cards SET owned = ? WHERE user_id = ? AND card_key = ?',
        (new_val, user['id'], card_key)
    )
    db.commit()
    collected = db.execute(
        'SELECT COUNT(*) as cnt FROM cards WHERE user_id = ? AND owned = 1',
        (user['id'],)
    ).fetchone()['cnt']

    if new_val == 1:
        if card_key in ANNOUNCE_CARDS:
            try:
                db.execute(
                    'INSERT INTO announcements (username, event_type, card_key) VALUES (?, ?, ?)',
                    (username, 'special', card_key)
                )
                db.commit()
            except sqlite3.IntegrityError:
                pass
        if collected == TOTAL:
            try:
                db.execute(
                    'INSERT INTO announcements (username, event_type, card_key) VALUES (?, ?, ?)',
                    (username, 'complete', '')
                )
                db.commit()
            except sqlite3.IntegrityError:
                pass

    return jsonify({'owned': new_val, 'collected': collected, 'total': TOTAL})


@app.route('/<username>/toggle_leaderboard', methods=['POST'])
def toggle_leaderboard(username):
    if session.get('user') != username:
        return jsonify({'error': '无权限'}), 403
    db = get_db()
    user = db.execute('SELECT id, show_in_leaderboard FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    new_val = 0 if user['show_in_leaderboard'] else 1
    db.execute('UPDATE users SET show_in_leaderboard = ? WHERE id = ?', (new_val, user['id']))
    db.commit()
    return jsonify({'show_in_leaderboard': new_val})



BAIDU_API_KEY = os.environ.get('BAIDU_API_KEY', '')
BAIDU_SECRET_KEY = os.environ.get('BAIDU_SECRET_KEY', '')

SUIT_CN_TO_KEY = {'黑桃': 'spade', '红桃': 'heart', '方片': 'diamond', '梅花': 'club'}
RANK_CN_TO_KEY = {
    'A': 'A', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7',
    '8': '8', '9': '9', '10': '10', 'J': 'J', 'Q': 'Q', 'K': 'K',
}
SPECIAL_CN_TO_KEY = {'小王': 'joker_black', '大王': 'joker_red', '牌盒': 'card_box'}


def get_baidu_token():
    url = (
        'https://aip.baidubce.com/oauth/2.0/token'
        f'?grant_type=client_credentials&client_id={BAIDU_API_KEY}&client_secret={BAIDU_SECRET_KEY}'
    )
    req = urllib.request.Request(url, method='POST', data=b'')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())['access_token']


VALID_RANKS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
SAFE_OCR_FIX = {'B': '8'}


def parse_cards_from_texts(texts):
    found = set()
    for text in texts:
        text = text.strip()
        for sp_cn, sp_key in SPECIAL_CN_TO_KEY.items():
            if text == sp_cn:
                found.add(sp_key)
        for suit_cn, suit_key in SUIT_CN_TO_KEY.items():
            pos = 0
            while True:
                idx = text.find(suit_cn, pos)
                if idx == -1:
                    break
                rest = text[idx + len(suit_cn):]
                if rest[:2] == '10':
                    found.add(f'{suit_key}_10')
                elif rest:
                    ch = SAFE_OCR_FIX.get(rest[0], rest[0])
                    if ch in ('A','2','3','4','5','6','7','8','9','J','Q','K'):
                        found.add(f'{suit_key}_{ch}')
                pos = idx + len(suit_cn)
    return [c for c in found if c in ALL_CARDS]


@app.route('/<username>/ocr', methods=['POST'])
def ocr_cards(username):
    if session.get('user') != username:
        return jsonify({'error': '无权限'}), 403
    file = request.files.get('image')
    if not file:
        return jsonify({'error': '未选择图片'}), 400
    img_data = file.read()
    size_mb = len(img_data) / 1024 / 1024
    print(f'[OCR] Received image: {size_mb:.1f}MB', flush=True)
    if len(img_data) > 10 * 1024 * 1024:
        return jsonify({'error': '图片太大，请不要超过10MB'}), 400

    if BAIDU_API_KEY and BAIDU_SECRET_KEY:
        try:
            print('[OCR] Getting Baidu token...', flush=True)
            token = get_baidu_token()
            print('[OCR] Token OK, calling OCR API...', flush=True)
            img_b64 = base64.b64encode(img_data).decode()
            body = urllib.parse.urlencode({'image': img_b64}).encode()
            req = urllib.request.Request(
                f'https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={token}',
                data=body,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            texts = [w['words'] for w in result.get('words_result', [])]
            print(f'[OCR] Baidu returned {len(texts)} texts: {texts}', flush=True)
            cards = parse_cards_from_texts(texts)
            return jsonify({'cards': cards, 'engine': 'baidu', 'raw_count': len(texts)})
        except Exception as e:
            print(f'[OCR] Baidu error: {e}', flush=True)
            return jsonify({'error': 'baidu_failed', 'fallback': True}), 200

    return jsonify({'error': 'no_api_key', 'fallback': True}), 200


DELTA_API = 'https://delta-test-api.shallow.ink'
FINGERPRINT = secrets.token_hex(20)

daily_keywords = {'list': [], 'fetched_date': None}
daily_keywords_lock = threading.Lock()


def get_anon_token():
    req = urllib.request.Request(
        f'{DELTA_API}/api/v1/auth/anonymous-token',
        data=json.dumps({'fingerprint': FINGERPRINT}).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data['data']['token']


def fetch_daily_keywords():
    try:
        token = get_anon_token()
        req = urllib.request.Request(
            f'{DELTA_API}/api/v1/df/tools/dailykeyword',
            headers={'X-Anonymous-Token': token}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        cst = timezone(timedelta(hours=8))
        today = datetime.now(cst).strftime('%Y-%m-%d')
        with daily_keywords_lock:
            daily_keywords['list'] = data['data']['list']
            daily_keywords['fetched_date'] = today
    except Exception as e:
        print(f'[DailyKeyword] fetch error: {e}')


def daily_refresh_loop():
    while True:
        cst = timezone(timedelta(hours=8))
        now = datetime.now(cst)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=1, microsecond=0)
        wait = (tomorrow - now).total_seconds()
        time.sleep(wait)
        fetch_daily_keywords()


def get_daily_keywords():
    cst = timezone(timedelta(hours=8))
    today = datetime.now(cst).strftime('%Y-%m-%d')
    with daily_keywords_lock:
        if daily_keywords['fetched_date'] == today and daily_keywords['list']:
            return dict(daily_keywords)
    fetch_daily_keywords()
    with daily_keywords_lock:
        result = dict(daily_keywords)
        print(f'[DailyKeyword] returning: list has {len(result.get("list", []))} items, date={result.get("fetched_date")}')
        return result


init_db()

refresh_thread = threading.Thread(target=daily_refresh_loop, daemon=True)
refresh_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
