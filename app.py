import os
import json
import uuid
import time
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for

from captcha_generator import CaptchaGenerator

app = Flask(__name__)
app.secret_key = 'captcha-demo-secret-key-2024'

DATA_FILE = 'captcha_data.json'
MAX_RECORDS = 100

captcha_gen = CaptchaGenerator()


class DataStore:
    def __init__(self):
        self.data = {
            'submissions': [],
            'corrections': [],
            'captcha_stats': defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0}),
            'sessions': {}
        }
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.data['submissions'] = loaded.get('submissions', [])
                    self.data['corrections'] = loaded.get('corrections', [])
                    stats = loaded.get('captcha_stats', {})
                    for k, v in stats.items():
                        self.data['captcha_stats'][k] = v
            except Exception as e:
                print(f"Load data error: {e}")

    def save(self):
        try:
            save_data = {
                'submissions': self.data['submissions'],
                'corrections': self.data['corrections'],
                'captcha_stats': dict(self.data['captcha_stats'])
            }
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Save data error: {e}")

    def add_submission(self, captcha_text, user_input, is_correct, ip=None):
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'captcha_text': captcha_text.upper(),
            'user_input': user_input.upper() if user_input else '',
            'is_correct': is_correct,
            'ip': ip
        }
        self.data['submissions'].insert(0, record)
        if len(self.data['submissions']) > MAX_RECORDS:
            self.data['submissions'] = self.data['submissions'][:MAX_RECORDS]

        key = captcha_text.upper()
        self.data['captcha_stats'][key]['total'] += 1
        if is_correct:
            self.data['captcha_stats'][key]['correct'] += 1
        else:
            self.data['captcha_stats'][key]['wrong'] += 1

        self.save()
        return record

    def add_correction(self, original_text, correct_text, ip=None):
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'original_text': original_text.upper(),
            'correct_text': correct_text.upper(),
            'ip': ip
        }
        self.data['corrections'].insert(0, record)
        self.save()
        self.update_mutation_corpus()
        return record

    def get_recent_submissions(self, limit=100):
        return self.data['submissions'][:limit]

    def get_captcha_stats(self, limit=50):
        items = sorted(
            self.data['captcha_stats'].items(),
            key=lambda x: x[1]['total'],
            reverse=True
        )
        result = []
        for text, stats in items[:limit]:
            accuracy = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0
            result.append({
                'text': text,
                'correct': stats['correct'],
                'wrong': stats['wrong'],
                'total': stats['total'],
                'accuracy': round(accuracy, 1)
            })
        return result

    def get_correction_texts(self):
        return [c['correct_text'] for c in self.data['corrections'] if c.get('correct_text')]

    def update_mutation_corpus(self):
        corpus = self.get_correction_texts()
        captcha_gen.set_mutation_corpus(corpus)

    def get_summary(self):
        total_submissions = len(self.data['submissions'])
        correct_count = sum(1 for s in self.data['submissions'] if s['is_correct'])
        wrong_count = total_submissions - correct_count
        accuracy = (correct_count / total_submissions * 100) if total_submissions > 0 else 0
        return {
            'total_submissions': total_submissions,
            'correct_count': correct_count,
            'wrong_count': wrong_count,
            'accuracy': round(accuracy, 1),
            'total_corrections': len(self.data['corrections']),
            'unique_captchas': len(self.data['captcha_stats'])
        }

    def store_session_captcha(self, session_id, captcha_text):
        self.data['sessions'][session_id] = {
            'text': captcha_text.upper(),
            'created_at': time.time()
        }

    def get_session_captcha(self, session_id):
        data = self.data['sessions'].get(session_id)
        if data and (time.time() - data['created_at']) < 300:
            return data['text']
        return None

    def clear_session_captcha(self, session_id):
        if session_id in self.data['sessions']:
            del self.data['sessions'][session_id]


store = DataStore()
store.update_mutation_corpus()


@app.route('/')
def index():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return render_template('index.html')


@app.route('/captcha/image')
def get_captcha_image():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    difficulty = request.args.get('difficulty', 'normal')
    captcha_gen.set_difficulty(difficulty)
    
    buffer, text = captcha_gen.generate_image()
    store.store_session_captcha(session['session_id'], text)
    
    return send_file(buffer, mimetype='image/png')


@app.route('/captcha/verify', methods=['POST'])
def verify_captcha():
    data = request.get_json() or request.form
    user_input = data.get('captcha', '').strip()
    
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': '会话已过期，请刷新页面'}), 400
    
    correct_text = store.get_session_captcha(session_id)
    if not correct_text:
        return jsonify({'success': False, 'message': '验证码已过期，请刷新'}), 400
    
    is_correct = user_input.upper() == correct_text.upper()
    ip = request.remote_addr
    
    store.add_submission(correct_text, user_input, is_correct, ip)
    store.clear_session_captcha(session_id)
    
    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_text': correct_text if not is_correct else None,
        'message': '验证成功！' if is_correct else '验证失败'
    })


@app.route('/captcha/correct', methods=['POST'])
def submit_correction():
    data = request.get_json() or request.form
    original_text = data.get('original_text', '').strip()
    correct_text = data.get('correct_text', '').strip()
    
    if not original_text or not correct_text:
        return jsonify({'success': False, 'message': '请提供完整信息'}), 400
    
    ip = request.remote_addr
    record = store.add_correction(original_text, correct_text, ip)
    
    return jsonify({
        'success': True,
        'message': '纠错已提交，感谢您的反馈！',
        'record': record
    })


@app.route('/admin')
def admin_panel():
    return render_template('admin.html')


@app.route('/api/stats')
def api_stats():
    summary = store.get_summary()
    submissions = store.get_recent_submissions(100)
    captcha_stats = store.get_captcha_stats(50)
    
    return jsonify({
        'summary': summary,
        'submissions': submissions,
        'captcha_stats': captcha_stats
    })


@app.route('/api/difficulty', methods=['POST'])
def set_difficulty():
    data = request.get_json() or request.form
    difficulty = data.get('difficulty', 'normal')
    if difficulty not in ['normal', 'hard']:
        return jsonify({'success': False, 'message': '无效的难度级别'}), 400
    captcha_gen.set_difficulty(difficulty)
    return jsonify({'success': True, 'difficulty': difficulty})


@app.route('/api/captcha', methods=['GET'])
def api_get_captcha():
    difficulty = request.args.get('difficulty', 'normal')
    captcha_gen.set_difficulty(difficulty)
    
    api_key = request.headers.get('X-API-Key', 'demo')
    session_id = f"api_{api_key}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    buffer, text = captcha_gen.generate_image()
    store.store_session_captcha(session_id, text)
    
    return jsonify({
        'success': True,
        'session_id': session_id,
        'captcha_text': text,
        'image_data': buffer.getvalue().hex(),
        'expires_at': int(time.time() + 300)
    })


@app.route('/api/captcha/<session_id>/verify', methods=['POST'])
def api_verify_captcha(session_id):
    data = request.get_json() or request.form
    user_input = data.get('captcha', '').strip()
    
    correct_text = store.get_session_captcha(session_id)
    if not correct_text:
        return jsonify({'success': False, 'message': '验证码已过期或不存在'}), 404
    
    is_correct = user_input.upper() == correct_text.upper()
    ip = request.remote_addr
    
    store.add_submission(correct_text, user_input, is_correct, ip)
    store.clear_session_captcha(session_id)
    
    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_text': correct_text
    })


@app.route('/api/corrections')
def api_corrections():
    return jsonify({
        'success': True,
        'corrections': store.data['corrections'][:100],
        'corpus': store.get_correction_texts()
    })


@app.route('/api/generate_from_corrections', methods=['POST'])
def generate_from_corrections():
    data = request.get_json() or request.form
    count = int(data.get('count', 5))
    count = min(max(count, 1), 20)
    
    corpus = store.get_correction_texts()
    if not corpus:
        return jsonify({'success': False, 'message': '暂无纠错数据可用'}), 400
    
    captcha_gen.set_mutation_corpus(corpus)
    captcha_gen.set_difficulty('hard')
    
    samples = []
    for _ in range(count):
        buffer, text = captcha_gen.generate_image()
        samples.append({
            'text': text,
            'image_data': buffer.getvalue().hex()
        })
    
    return jsonify({
        'success': True,
        'samples': samples,
        'corpus_size': len(corpus)
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
